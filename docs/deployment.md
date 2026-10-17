# Render deployment and operations

## Decision and costs

Use GitHub-connected Render Docker hosting: one paid Starter web service and a
1 GB persistent disk at `/var/data` (increase after measuring audio/image needs).
Review current service and disk pricing and region before approving creation.
This document does not purchase, deploy, or commit anything. SQLite is appropriate
for this small single-instance site, not horizontal scaling or high write traffic.

Render's [disk documentation](https://render.com/docs/disks) confirms that disks
exist only at runtime, not build, pre-deploy or one-off jobs. A disk prevents
zero-downtime deploys: Render stops the old instance before starting the new one.
Brief downtime is an accepted design tradeoff, not a promise of instant migrations.
Large migrations can extend it. Do not add a second instance or a preDeployCommand.

## Architecture and exact lifecycle

`Dockerfile` uses Python 3.14 slim, locked dependencies and nginx from Debian's
supported package repository. Rebuild regularly for Python/nginx/security updates.
Gunicorn is locked in `uv.lock`. nginx serves static files and restricted media
with byte ranges; Django's development static server is never used in production.

Build (Render executes the Dockerfile, equivalent locally):

```sh
docker build -t website-ci .
```

Inside the build the dependency command is `./.venv/bin/uv sync --locked --no-dev --inexact`.
Docker and CI start with fresh virtual environments containing only bootstrap tooling;
`--inexact` preserves repository-local uv rather than removing it as an undeclared
application dependency. No previous application environment is reused, so this does
not retain stray application dependencies. Both assert the uv executable survives.
CI uses the same approach without `--no-dev`.
Static collection uses disposable build-only settings, not SMTP credentials or
mounted storage:

```sh
DJANGO_DEBUG=true DJANGO_SECRET_KEY=build-only DJANGO_DATABASE_PATH=/unmounted/db.sqlite3 DJANGO_MEDIA_ROOT=/unmounted/media .venv/bin/python manage.py collectstatic --noinput
```

Start command is Docker's `CMD ["bash", "deploy/start.sh"]`. Leave Render's Docker
command override empty. The script checks an actual `/var/data` mount and exact
storage paths, creates media with app ownership, then runs as the unprivileged app:

```sh
.venv/bin/python manage.py check
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py migrate --check
.venv/bin/gunicorn --config deploy/gunicorn.conf.py config.wsgi:application
```

nginx starts with `nginx -g 'daemon off;'` after `nginx -t`. A small bash supervisor
terminates both processes if either exits and forwards shutdown signals. `setpriv`
execs Gunicorn directly as app, avoiding a runuser process intercepting TERM.
Shutdown sends TERM to Gunicorn and graceful QUIT to nginx, waits for both, and
exits zero for an operator stop. nginx's worker shutdown is bounded at 25 seconds;
Gunicorn's graceful timeout is also 25 seconds. Allow at least 35 seconds when
stopping the container. The smoke test checks clean termination and Gunicorn logs.
nginx's
master/startup run as root for disk ownership and worker setup; nginx workers,
migrations and Gunicorn run as UID 10001 (`app`). Existing restored files must be
owned by that UID. No recursive ownership rewrite is done on each deployment.
One Gunicorn process with four threads limits SQLite write contention. Move to a
managed database before scaling. Test migrations on a restored copy before release;
a failed migration leaves startup unhealthy, rather than serving incompatible code.
Code rollback does not undo a schema change: take a consistent backup beforehand.

`/healthz/` checks a migrated database table and media directory access without
writing or sending mail, returns generic 200/503 and no-store/noindex. It does not
prove SMTP delivery, free disk space or backup freshness. Mount presence is checked
at startup. Static files are baked into the image, outside the persistent disk.

## GitHub and Render setup (owner action required)

1. Push the reviewed repository to GitHub. Enable CI and branch protection requiring
   the `checks` job. CI includes Django checks/full tests/migration drift,
   Docker build and nginx/Gunicorn smoke tests. No deploy
   secrets are required. Fix failing checks before connecting production.
2. Connect that GitHub repo using Render **New Blueprint**, review `render.yaml`,
   choose the production branch and region, and explicitly approve the paid service
   and disk. Auto-deploy is `checksPass`; verify branch/check integration in Render.
   Do not enable previews with production secrets or data.
3. Fill prompted secrets in Render (never commit them). Set `DJANGO_SECRET_KEY` to
   a unique secret at least 50 characters long; Render's 44-character generated
   value is too short for this project's validator. Generate one securely, e.g.
   `.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(64))'` on your
   machine, transfer privately, and do not paste it into logs or chat.
   Also set mandatory `ADMIN_GATE_USERNAME` and `ADMIN_GATE_PASSWORD` as Render
   secrets, separate from Django admin credentials. Username: 1-64 letters, digits,
   dots, underscores or hyphens. Password: unique random 24-128 printable ASCII
   characters without spaces (a password-manager-generated value is recommended).
   Startup fails closed if absent/invalid; local Django tests/builds need neither.
   Rotate by updating Render secrets and redeploying; both values are shared by
   authorized administrators and must be distributed privately.
4. Set `DJANGO_ALLOWED_HOSTS=thomasalban.com,www.thomasalban.com,ACTUAL-SERVICE.onrender.com`
   with the actual service hostname, no wildcard or scheme. The onrender host is
   needed for Render health checks. Keep `DJANGO_SITE_URL=https://thomasalban.com`.
   Blueprint sets the two HTTPS CSRF origins, exact `/var/data/db.sqlite3` and
   `/var/data/media` paths, `DJANGO_DEBUG=false`, proxy trust true, port 10000,
   and HSTS initially zero. `.env.example` documents every environment setting.
5. Configure SMTP backend, provider host, port 587, TLS true, SSL false, username,
   password, verified `DJANGO_DEFAULT_FROM_EMAIL` and `DJANGO_ENQUIRY_EMAIL`.
   For port 465 use TLS false and SSL true. Credentials are not required for build
   or CI; missing/incorrect values can still break live enquiries. Configure the
   provider's SPF and DKIM DNS records and an appropriate DMARC policy. Preserve
   existing MX records. After owner approval, submit one controlled enquiry and
   check inbox/spam and Reply-To; backend acceptance alone is not inbox delivery.
6. Add `thomasalban.com` and `www.thomasalban.com` as custom domains in Render.
   Follow the exact DNS targets Render supplies at the registrar (apex A/ALIAS,
   www CNAME as directed); do not copy historical IP addresses. Remove conflicting
   records, including stale AAAA records if Render instructs it. Verify both in
   Render and wait for certificates. Render provides managed TLS and redirects
   HTTP to HTTPS: [TLS docs](https://render.com/docs/tls). Verify apex/www redirect
   behavior in the dashboard; Django canonicals always use the apex but do not
   themselves redirect host aliases. Keep the onrender hostname for health checks.
7. Use the running service's Shell (not a one-off job) to create the admin:
   `runuser -u app -- .venv/bin/python manage.py createsuperuser`.
   Run `runuser -u app -- .venv/bin/python manage.py check --deploy` there. Review
   intentional HSTS warnings while staged at zero; after verifying HTTPS set 300,
   then increase carefully. Subdomain/preload flags remain false until all affected
   domains can permanently support HTTPS. Do not blindly silence warnings.

## Proxy trust and media security boundary

Only nginx port 10000 is exposed; Gunicorn listens on 127.0.0.1:8000. nginx replaces
`X-Forwarded-Proto` with the constant `https` and clears forwarded host, port,
client-IP and standardized Forwarded headers. Gunicorn scheme-header processing
is disabled; Django trusts only nginx's overwritten scheme header. Incoming values
cannot spoof that decision. This deliberately relies on Render's HTTPS-only public
edge, which redirects HTTP before it reaches the container. It does not rely on
Render sanitizing arbitrary client forwarding headers.

Do not expose this container directly to the internet or another plaintext ingress
and claim it is TLS-secured. Private-network callers are inside the deployment trust
boundary and also get an HTTPS interpretation. Avoid untrusted services in that
network. Host validation is Django's exact allowlist for application routes.
Client-IP based controls cannot use forwarded headers in this configuration;
nginx logs the edge peer, not an authenticated visitor address.

Media is public and same-origin, including uploads attached to unpublished content.
Unpublishing or deleting a database record does not revoke files, links or caches.
nginx allowlists passive image/audio extensions, sets explicit MIME types, nosniff
and a sandbox CSP, denies symlinks and listings, and supports single byte ranges.
No uploaded program is executed; HTML, SVG and other unlisted formats return 404.
Audio validation checks extension/size, not file signatures or malware. Only trusted
admins may upload. Do not use this scheme for public uploads; use isolated storage
and additional validation for that future feature. Maximum whole request is 60 MiB.

## Independent admin gate and shared abuse budgets

nginx Basic authentication protects the entire `/admin` prefix, including the
slashless path and nested routes, before Django. Django's separate login and CSRF
checks still apply. No forwarded-IP trust is involved. Startup uses OpenSSL SHA-512
crypt with a fresh random salt and stdin password input, then writes only a hash
in `/run/admin-gate/htpasswd` (root:app 0640, directory 0750). Cleartext gate values
are unset before spawning servers; they remain secrets in Render/container runtime
configuration, accessible to privileged operators. No values/hashes are logged.
nginx admin error logging is critical-only because auth failures can log usernames.
Access status logs remain available. Authorization is stripped on all proxied
requests, so browsers' Basic credentials never reach Django. Static/media and
health checks do not require the gate. Only use Basic authentication over HTTPS;
it is an independent shared password, not MFA, and browser credential caching can
outlast Django logout. Close the browser session or clear cached authentication.

Budgets in `deploy/nginx.conf` are deliberately **global**, not per visitor/IP:

- Application POST requests: 20/minute, burst 10, covering forms and admin writes.
- All admin requests (including gate attempts): 60/minute, burst 30.
- `/admin/login/` requests, GET or POST: 6/minute, burst 5.

nginx rejects excess requests immediately with 429, before authentication or Django.
Static/media requests do not consume these budgets; health GET/HEAD remains
unaffected. Burst allowances accommodate ordinary editing but all visitors share
each bucket. Attackers can exhaust a budget and temporarily deny legitimate users;
these limits are not a DDoS solution or account-level lockout. Monitor 429 counts,
SMTP quotas and admin usability. Adjust the reviewed nginx constants and redeploy
if needed; there is intentionally no unvalidated environment template for rates.
Keep provider sending quotas and alerting as additional protection.

## Launch blockers and operations

- **Privacy requires owner approval before launch.** Agree and publish accurate
  privacy information covering enquiry fields, recipient/provider, retention and
  deletion, server/Render logs and IP addresses, session/CSRF cookies, and
  YouTube/Spotify connections on page load for supported primary recordings.
  Loading players eagerly without autoplay is the explicit owner preference;
  providers are intentionally contacted without a Load button or site JavaScript.
  This preference does not establish a consent policy. Decide any consent requirements.
  No privacy policy or legal compliance is invented here.
- Enter owner-approved biography and verify the existing homepage introduction.
  In admin create compositions, review real premiere dates (old release dates were
  migrated), descriptions, instrumentation/duration, alt text and image rights.
  Use supported compressed image formats; no automatic resizing exists. Set
  `nunc-dimittis` slug and verified per-recording credits, then publish intentionally.
  Follow README's content-entry guide. Confirm permission for score/audio previews.
- Require strong unique admin passwords, least-privilege staff permissions, and MFA
  on GitHub, Render and mail provider accounts. Django admin currently has no MFA
  or account-specific login throttling. The mandatory independent nginx gate and
  shared budgets above protect production admin; test gate rotation/recovery access.
  Do not treat robots.txt, an obscure URL or CSRF as brute-force protection.
- Forms have honeypot and per-session cooldown plus nginx's shared POST budget.
  Fresh sessions evade the session cooldown, not the shared budget. Agree provider
  sending quotas/alerts and further edge abuse controls if traffic warrants them.
  If adding an external proxy, revisit the trust boundary rather
  than accepting client-supplied forwarding headers. Do not log form bodies,
  credentials or cookies; nginx logs omit query strings, but paths/edge IPs remain.
- Enable Render failure notifications and an independent HTTPS uptime check.
  Alert on 5xx, restarts, SMTP errors, CPU/RAM and disk usage (e.g. 70% warning,
  85% urgent), certificate expiry, and backup age/failures. Define an owner who
  receives alerts. Logs are ephemeral/platform-retained, not a backup.
- Check both domain TLS/redirects, admin login/CSRF, mobile navigation, audio
  seeking (`Range: bytes=0-99` should return 206), previews, and eager primary embeds.
  Verify server-rendered YouTube/Spotify iframes, provider styling, titles, no
  autoplay, external fallback links and credits. No site JavaScript should be
  needed to create the iframe (provider playback may need provider JavaScript).
  Preserve iframe `referrerpolicy="strict-origin-when-cross-origin"`: YouTube needs
  Referer, and `no-referrer` can cause Error 153. Check actual playback and outgoing
  Referer in a live browser; local Django tests cannot verify provider availability
  or browser/privacy-extension restrictions.
  Run live Lighthouse/accessibility checks. Verify canonicals and `/robots.txt`,
  submit `https://thomasalban.com/sitemap.xml` in Google Search Console and Bing
  Webmaster Tools, and inspect `/compositions/nunc-dimittis/` after publication.

## Backup and offline restore

**Do not enter irreplaceable content until an off-host backup and restore rehearsal
have been verified.** Render disk snapshots are supplementary. Never copy a live
SQLite file with plain `cp` and assume it is consistent.

### Create a backup

Pause ALL database/media writers (admin editing, uploads, imports, deletions and
migrations) for the entire command. The SQLite online backup API provides a
consistent database snapshot, including committed WAL data, but cannot atomically
snapshot media with it. The command warns about the write pause; it does not enforce
maintenance mode. Execute as the app user on the disk-owning service, not Render
cron/pre-deploy/one-off compute:

```sh
runuser -u app -- .venv/bin/python manage.py backup_site --destination /var/data/backups --revision YOUR_DEPLOYED_COMMIT_ID
```

`--revision` is optional and defaults to `unknown`; supply the actual deployed code
identifier, never credentials. The destination must be separate from both media
and the database, with 0700 permissions (created that way if absent). The command
prints the unique path of a 0600 uncompressed `.tar` file. It never replaces an
existing backup. Allow space for the archive, database snapshot and largest media
file. Run before migrations and after significant content changes.

Version 1 contains only `database.sqlite3`, regular media files and `manifest.json`.
The manifest records UTC creation time, supplied code revision, directories,
file sizes and SHA-256 checksums (manifest limited to 1 MiB). Empty media directories
are preserved. SQLite
integrity is checked. Paths containing symlinks, hardlinked files, special files,
and hidden/unsafe media names are rejected, not followed or silently omitted.
An existing empty media root is required. No settings, environment files, SMTP
credentials or source tree are collected. Do not place secrets in uploads: database
records, sessions/password hashes and uploaded content remain sensitive and are
included. Filesystem parents must be trusted and not concurrently modified; these
commands are not a sandbox against a local attacker changing paths during a run.

### Validate and restore to fresh paths

Use an isolated offline rehearsal environment with no production mail delivery.
Create private, app-owned parent directories first. The archive must be a regular,
non-hardlinked file on a trusted filesystem. For example:

```sh
runuser -u app -- mkdir -m 700 /var/data/recovery-20261016
runuser -u app -- .venv/bin/python manage.py restore_site --archive /var/data/backups/backup-EXAMPLE.tar --database /var/data/recovery-20261016/db.sqlite3 --media-root /var/data/recovery-20261016/media --confirm-offline
```

Replace the example archive with the path printed by `backup_site`. The explicit
`--database`, `--media-root` and `--confirm-offline` arguments are mandatory. The
acknowledgement does not stop processes or prove they are offline. Both targets must
be absent, separate from each other, the archive, and the currently configured
DB/media paths. Existing directories (even empty), files, SQLite sidecars and
symlink paths are refused. There is deliberately no overwrite/force option.

Before creating either target, restore stages and validates every member, manifest
version/file set, size/checksum and SQLite integrity. It never uses tar extraction
paths or accepts links, special files, traversal, absolute paths or duplicates.
Restored directories are 0700 and files 0600. Run as the intended owner (UID 10001
in the production container). Caught publication failures remove only targets this
run created. A process kill/power failure can leave incomplete targets: inspect and
choose new fresh paths for retry. Publication of two targets is not an atomic
transaction. Checksums detect damage, not authenticity: someone able to rewrite
both manifest and payload can forge a backup. Only restore trusted archives; there
is no archive resource quota, so reserve isolated disk space for validation.

### Manual cutover and remaining operator setup

No live replacement, configuration switch, scheduling, retention, transfer or
encryption is implemented by these commands. Required owner/operator work:

- Set up and monitor scheduling on the disk-owning service and a tested write-pause
  procedure. Agree retention/recovery objectives (proposal: nightly, 7 daily and
  4 weekly copies, <=24h data loss and <=4h recovery). Implement pruning only after
  verified transfer; monitor disk headroom, backup age, failures and transfer success.
- Encrypt and transfer archives off-host using an operator-chosen tool/service and
  separately protected keys. Restrict access and verify recovery of encrypted copies.
  Disk-local backups are staging, not disaster recovery. No cloud credentials or
  encryption dependencies are supplied by this implementation.
- Rehearse restore with the matching code revision, inspect manifest, test migration
  compatibility on the restored copy, then check readiness, admin, catalogue,
  previews and audio ranges. Record elapsed recovery time before launch.
- For real cutover, stop all application processes/writers first. Keep original
  DB/media untouched as rollback material. Arrange a reviewed offline storage switch
  to the verified restored pair, with correct ownership and serving permissions.
  Current production startup expects exact `/var/data/db.sqlite3` and `/var/data/media`
  paths; merely changing environment variables is not a supported cutover. The
  operator must arrange offline relocation of the original pair to private rollback
  storage and the restored pair to those paths, including handling old SQLite
  sidecars only after clean shutdown. Never replace files from a running Gunicorn
  shell. Restart only after verifying both paths, code/schema compatibility and
  permissions. Rollback also requires stopping all processes and restoring the
  original pair; code rollback alone does not undo migrations. This deployment-
  specific stop/switch/rollback procedure still needs rehearsal and approval.
