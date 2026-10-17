#!/usr/bin/env bash
set -Eeuo pipefail
cd /app
# Never silently migrate an ephemeral filesystem or an unexpected database.
mountpoint -q /var/data || { echo 'Persistent disk missing at /var/data' >&2; exit 1; }
[[ "${DJANGO_DATABASE_PATH:-}" == /var/data/db.sqlite3 ]]
[[ "${DJANGO_MEDIA_ROOT:-}" == /var/data/media ]]
[[ "${DJANGO_DEBUG:-}" == false ]]
[[ "${DJANGO_TRUST_PROXY_HEADERS:-}" == true ]]
[[ "${PORT:-10000}" == 10000 ]]
mkdir -p /var/data/media
chown app:app /var/data /var/data/media
chmod 750 /var/data /var/data/media
umask 027
.venv/bin/python deploy/admin_gate.py
# Remove cleartext gate credentials from the environment inherited by services.
unset ADMIN_GATE_USERNAME ADMIN_GATE_PASSWORD
setpriv --reuid=app --regid=app --init-groups .venv/bin/python manage.py check
setpriv --reuid=app --regid=app --init-groups .venv/bin/python manage.py migrate --noinput
setpriv --reuid=app --regid=app --init-groups .venv/bin/python manage.py migrate --check
nginx -t

# Either process exiting takes down the container; Render can restart it.
# Gunicorn's master and workers run unprivileged; only nginx's master is root.
gunicorn_pid=''
nginx_pid=''
shutdown() {
    trap - TERM INT EXIT
    # setpriv execs Gunicorn: this PID is the master, not a runuser intermediary.
    [[ -z "$gunicorn_pid" ]] || kill -TERM "$gunicorn_pid" 2>/dev/null || true
    [[ -z "$nginx_pid" ]] || kill -QUIT "$nginx_pid" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap 'shutdown; exit 0' TERM INT
trap shutdown EXIT
setpriv --reuid=app --regid=app --init-groups .venv/bin/gunicorn --config deploy/gunicorn.conf.py config.wsgi:application &
gunicorn_pid=$!
nginx -g 'daemon off;' &
nginx_pid=$!
wait -n "$gunicorn_pid" "$nginx_pid"
exit 1
