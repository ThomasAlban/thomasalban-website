#!/usr/bin/env bash
# Disposable container integration checks. Never mounts repository DB/media.
set -Eeuo pipefail
name=website-deployment-smoke
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
args=(--env DJANGO_DEBUG=false
      --env DJANGO_SECRET_KEY=test-only-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ-abcdefghijklmnopqrstuvwxyz
      --env DJANGO_ALLOWED_HOSTS=localhost
      --env DJANGO_SITE_URL=https://localhost
      --env DJANGO_DATABASE_PATH=/var/data/db.sqlite3
      --env DJANGO_MEDIA_ROOT=/var/data/media
      --env DJANGO_TRUST_PROXY_HEADERS=true
      --env ADMIN_GATE_USERNAME=smoke-admin
      --env ADMIN_GATE_PASSWORD=smoke-only-password-0123456789)
# Require the intended error, not an unrelated image/startup failure.
if output=$(docker run --rm "${args[@]}" website-ci 2>&1); then
    echo 'Startup unexpectedly accepted missing disk' >&2; exit 1
fi
[[ "$output" == *'Persistent disk missing at /var/data'* ]]
# Missing admin secrets must also fail closed before any server starts.
if output=$(docker run --rm --tmpfs /var/data "${args[@]}" --env ADMIN_GATE_PASSWORD= website-ci 2>&1); then
    echo 'Startup unexpectedly accepted missing gate password' >&2; exit 1
fi
[[ "$output" == *'Admin gate configuration failed'* ]]
docker run -d --name "$name" --tmpfs /var/data -p 127.0.0.1:10000:10000 "${args[@]}" website-ci
ready=false
for attempt in {1..60}; do
    status=$(curl --silent --show-error --connect-timeout 2 --max-time 3 --output /dev/null --write-out '%{http_code}' http://localhost:10000/healthz/ || true)
    if [[ "$status" == 200 ]]; then ready=true; break; fi
    sleep 2
done
if [[ "$ready" != true ]]; then docker logs "$name"; exit 1; fi
# Synthetic files only; deliberately include HTML disguised as audio.
docker exec --user app "$name" .venv/bin/python -c "import os; from pathlib import Path; os.umask(0o027); p=Path('/var/data/media/audio/2026/10'); p.mkdir(parents=True); (p/'test.mp3').write_bytes(b'0123456789'); (p/'bad.html').write_text('<script>alert(1)</script>'); (p/'fake.mp3').write_text('<script>alert(1)</script>'); (p/'link.mp3').symlink_to('/etc/passwd')"
docker exec "$name" test -x /app/.venv/bin/uv
docker exec --user app "$name" test -r /run/admin-gate/htpasswd
python3 - <<'PY'
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

opener = build_opener(NoRedirect)
def get(path, headers=None, method='GET'):
    try:
        return opener.open(Request('http://localhost:10000' + path, headers=headers or {}, method=method), timeout=5)
    except HTTPError as error:
        return error

r = get('/media/audio/2026/10/test.mp3', {'Range': 'bytes=2-5'})
assert r.status == 206, r.status
assert r.read() == b'2345'
assert r.headers['Content-Range'] == 'bytes 2-5/10'
assert r.headers['Content-Type'] == 'audio/mpeg'
assert r.headers['X-Content-Type-Options'] == 'nosniff'
assert get('/media/audio/2026/10/bad.html').status == 404
assert get('/media/audio/2026/10/link.mp3').status == 403
assert get('/media/audio/2026/10/').status == 404
r = get('/media/audio/2026/10/fake.mp3')
assert r.headers['Content-Type'] == 'audio/mpeg'
assert 'sandbox' in r.headers['Content-Security-Policy']
assert get('/static/admin/css/base.css').status == 200
r = get('/healthz/', {'X-Forwarded-Proto': 'http', 'X-Forwarded-Host': 'evil.example', 'Forwarded': 'proto=http;host=evil.example'})
assert r.status == 200  # Incoming scheme cannot cause a redirect loop.
assert get('/healthz/', {'Host': 'evil.example'}).status == 400
for path in ('/admin', '/admin/', '/admin/login/', '/admin/core/', '/admin/fake.mp3'):
    assert get(path).status == 401, path
wrong = {'Authorization': 'Basic ' + b64encode(b'smoke-admin:wrong-password').decode()}
assert get('/admin/', wrong).status == 401
auth = {'Authorization': 'Basic ' + b64encode(b'smoke-admin:smoke-only-password-0123456789').decode()}
assert get('/admin/', auth).status == 302  # Django login is still required.
assert get('/admin/login/', auth).status == 200
assert get('/static/admin/css/base.css', wrong).status == 200
assert get('/healthz/', wrong).status == 200
# Shared budgets: a burst must get 429 even when forwarded IPs vary.
def burst(path, method='GET', credentials=None):
    def request(i):
        headers = {**(credentials or {}), 'X-Forwarded-For': f'192.0.2.{i}'}
        with get(path, headers, method) as response:
            return response.status
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(request, range(40)))
assert 429 in burst('/admin/login/', credentials=auth)
assert 429 in burst('/admin/')
assert 429 in burst('/contact/', method='POST')
assert get('/healthz/').status == 200
assert get('/media/audio/2026/10/test.mp3').status == 200
PY
# Ensure a migration rerun is harmless on this same disposable mounted disk.
docker exec --user app "$name" .venv/bin/python manage.py migrate --noinput
docker exec --user app "$name" .venv/bin/python manage.py migrate --check
# Exercise PID 1's TERM handler. Timeout/SIGKILL would produce exit 137, not 0.
docker stop --time 35 "$name" >/dev/null
[[ "$(docker inspect --format '{{.State.ExitCode}}' "$name")" == 0 ]]
logs=$(docker logs "$name" 2>&1)
[[ "$logs" == *'Handling signal: term'* ]]
[[ "$logs" == *'Shutting down: Master'* ]]
[[ "$logs" != *'smoke-only-password-0123456789'* ]]
[[ "$logs" != *'smoke-admin'* ]]
