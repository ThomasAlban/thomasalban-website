# Thomas Alban website

Server-rendered Django composer website with a published-only catalogue, ordered
score previews, admin editing, SEO metadata and shared contact/score enquiries.
Requirements and implementation priorities are in `AGENTS.md`.

## Analytics

Umami Cloud page-view analytics loads on public pages only when `DEBUG=False`
and the request hostname is `thomasalban.com` or `www.thomasalban.com`. Local
development, the Render hostname and Django admin do not load the script.
The public website ID is in `templates/base.html`; no API key or Render setting
is needed. No custom events or enquiry form contents are sent by this integration.
Umami still receives standard page metadata; avoid personal details in URLs.
Document the provider in privacy information and review applicable consent/opt-out
requirements. After deployment, verify a visit in Umami with an unblocked browser.

## Local setup

Bootstrap the repository-local uv binary with Python 3.14, then:

```sh
python3.14 -m venv .venv
.venv/bin/pip install uv==0.13.0
./.venv/bin/uv sync --locked --inexact
test -x ./.venv/bin/uv
cp .env.example .env
./.venv/bin/uv run --env-file .env python manage.py migrate
./.venv/bin/uv run --env-file .env python manage.py createsuperuser
./.venv/bin/uv run --env-file .env python manage.py runserver
```

`--inexact` retains the bootstrap uv executable. Start with a fresh virtual
environment for a clean dependency baseline; it does not remove unrelated packages
from an existing local environment. Docker and CI always bootstrap fresh environments.

Python 3.14 is used in Docker and CI. Django 6.1.2 is currently locked.
Commit `uv.lock` for reproducible installations; use
`./.venv/bin/uv lock --upgrade-package django` to update.

Public pages: `/`, `/compositions/`, `/compositions/<slug>/`, `/about/`,
`/contact/`. The admin is available at `/admin/`.

Set `DJANGO_SITE_URL` to the final HTTPS origin before launch: canonicals,
structured data, sitemap locations and the robots sitemap link use this value.
`/sitemap.xml` contains public pages and published works only. `/robots.txt`
allows search crawlers (including Google, Bing and OAI-SearchBot), excluding admin.
Filtered catalogue pages remain crawlable so their noindex directive and clean canonical can be read.

## Search and social metadata

The homepage retains "Thomas Alban - Composer", its WebSite/Person graph and site
name "Thomas Alban". Composition titles use "<title> - Thomas Alban", without
promising recordings that may not exist. Default descriptions include title,
composer and instrumentation when present; **SEO description** in admin overrides
that default. Visible composition breadcrumbs match BreadcrumbList structured data.

Optionally set `DJANGO_PERSON_SAME_AS` to a comma-separated list of owner-confirmed
public official profile URLs. Leave it empty until verified: no profiles are seeded
or inferred from recording links or contact copy. Only HTTP(S) URLs without credentials
are accepted. This adds Person sameAs on Home and About; syntax validation cannot
establish ownership. Restart the service after changing configuration.

Home and About use the first nonempty biography photo in position/ID order for
Open Graph and Twitter image cards. Composition pages use their first nonempty
composition image, never a score preview or another composition's image. Image URLs
are absolute (relative storage URLs use DJANGO_SITE_URL; absolute CDN URLs are
preserved), with the existing alt text. No image means no image/card tags. No new
assets, cropping or resizing are generated; verify image rights, public availability,
size and provider-compatible format (JPEG/PNG are safest) in social preview tools.

Composition sitemap lastmod uses nullable updated_at, maintained when a composition
or its images, previews or listening links actually change through ordinary model
saves/deletes, including admin inlines. No-op saves do not advance it. Existing rows
remain NULL after migration and omit lastmod until a subsequent content change;
do not mass-save or backfill dates just for SEO. Static pages deliberately omit
lastmod because their full content is not tracked by one model. Bulk create/update,
QuerySet.update, raw SQL/fixtures and replacing a file in storage bypass tracking:
importers must maintain accurate timestamps explicitly (or clear to NULL if unknown).
These dates describe content edits, not composition years or premiere dates.

## Error-page previews

Keep `DJANGO_DEBUG=true` in `.env` and start the local development server using
the command in Local setup above. Open these URLs (adjust the port if needed):

- [400 - Bad request](http://localhost:8000/__preview__/errors/400/)
- [403 - Access denied](http://localhost:8000/__preview__/errors/403/)
- [404 - Page not found](http://localhost:8000/__preview__/errors/404/)
- [500 - Something went wrong](http://localhost:8000/__preview__/errors/500/)

The previews render the actual error templates directly, without raising an
exception, so you can check mobile layouts and both colour themes while keeping
Django's debug diagnostics enabled. They return the corresponding HTTP error
status; error entries in the development-server log are expected.

These routes are registered only when `DEBUG=True` and are unavailable in
production. Actual errors use Django's normal handlers: with `DEBUG=False`,
the custom templates are used; with debug enabled, Django retains its diagnostic
pages for 400/404/500 errors. CSRF failures use the branded 403 page in either mode.

Templates live in `templates/{400,403,404,500}.html`, share
`templates/errors/base.html`, and inherit the main site layout. Preview routing
is in `config/urls.py`, with the view in `core/error_previews.py`.
Regression coverage, including production error handling and debug-only preview
access, is in `core/test_error_pages.py`:

```sh
./.venv/bin/uv run --env-file .env python manage.py test core.test_error_pages
```

## Structure

- `config/`: environment-based settings, URL routing, ASGI and WSGI entry points.
- `core/`: general pages, enquiry validation/delivery, shared SEO and sitemaps.
- `compositions/`: composition models, admin, catalogue filters and work pages.
- `templates/`, `static/css/site.css`: accessible shared templates and responsive styling.

## Catalogue data

Compositions default to unpublished. Use `Composition.objects.published()` for public
queries (admin retains access to drafts). Slugs are unique and editable; the admin
suggests them from titles. Categories are free text until a taxonomy is agreed.
Optional metadata can be left blank. Public durations are approximate, rounded to
the nearest 30 seconds (ties upward, minimum c. 0:30), e.g. c. 1:00, c. 1:30,
c. 2:00. Admin duration inputs step by 30 seconds; existing stored seconds and
catalogue filter boundaries are unchanged. Ordering is premiered date descending,
then composition year descending, then newest ID, with missing dates/years last.
The premiered-date migration preserves values previously stored as release dates;
review those values in admin if they do not represent the actual premiere.
Score previews and composition images are edited inline, sorted by position then
ID, and require descriptive alt text. Composition images allow optional captions
or photographer credits. Images appear on the individual composition page,
below its description without a visible gallery heading; portrait images are
height-limited and retain their aspect ratio. The first nonempty image in position/ID
order also appears on homepage and catalogue cards and in composition social metadata. Pillow validates image uploads in
Django forms. Deleting a composition deletes its related image/preview records;
uploaded files are not automatically removed by Django.

## Biography and photos

In Django admin, open **Core → Biography**, add the biography, and save. There is
one biography record; reopen it to update the About page without code changes.
Use Markdown for formatting, with blank lines between paragraphs:

```markdown
Thomas Alban composes *choral music*, including **Nunc dimittis**.

Explore [his compositions](/compositions/) or [listen](https://example.com).

- First list item
- Second list item
```

Numbered lists (`1. Item`) are also supported. The admin field includes a short
formatting guide. Plain-text paragraphs still work; raw HTML is displayed as text
and unsafe link URLs are blocked. Images and other Markdown features are not
supported in biography text. Until text is saved, the existing placeholder is shown.

Add one or more **Biography photos** in Django admin for the About page. Each
requires an image and descriptive alt text, with optional caption/credit and an
editable position. Photos appear in position/ID order in a responsive gallery.
Upload compressed, appropriately sized images; there is no automatic resizing.


## Recordings

Upload an optional audio file on the composition admin form (MP3, WAV, OGG or
M4A, up to 50 MiB; MP3 is recommended for browser compatibility and file size).
Extension/size validation is not content verification or malware scanning; only
trusted administrators should upload files, and only recordings you have rights
to publish. Native browser controls provide play/pause, seeking and volume
without JavaScript. No waveform generation or transcoding is used.

Add any number of labelled **Listening links** in the composition admin inline,
ordered by position then ID. Select at most one **Is primary** link. Recognised
YouTube video links (watch, short, embed or youtu.be) and Spotify track, album,
playlist, episode and show links display an embedded player for that primary link.
By explicit owner preference, supported primary players are server-rendered iframes
that load eagerly when the page loads, without autoplay or a Load player button.
No site JavaScript is required to create the player; providers may require their own
JavaScript for playback. YouTube/Spotify are intentionally contacted on page load
and may receive information about the visit. Iframes use
`referrerpolicy="strict-origin-when-cross-origin"` so cross-origin HTTPS requests
send the site origin as Referer, which YouTube needs (suppressing it can cause
Error 153). Keep the provider allowlist and ordinary external fallback links.
Add verified
per-recording credits using each Listening link's `credit` or the uploaded file's
`audio_credit`; credits are not automatically inferred from a title or URL.
Other links remain external; all links are listed even when embedded. Existing single
recording URLs are migrated into primary links labelled `Recording`; apply
migrations before serving the updated code.

Audio and previews use the configured media storage. Replacing/clearing files or
deleting records does not delete the files: keep backups, and periodically audit
unreferenced media before removing it (including references needed by backups).
Render nginx serves only JPG/JPEG, PNG, GIF, WebP, AVIF and the listed audio
extensions, with explicit safe MIME types, nosniff, no directory listings or
symlink traversal, and native byte-range support. All three image fields (composition
images, score previews and biography photos) validate these filename extensions,
case-insensitively, in model validation and admin forms; Pillow still validates
image content in forms. Direct model saves do not run validation automatically.
Existing uploads are preserved, not converted or deleted. Existing unsupported
uploads (such as BMP or TIFF) remain unserved by nginx: re-export them as a supported
format and replace the upload in admin, rather than just renaming the extension.
Editing a record with an unsupported image may require replacing that image first.
Images are not resized or converted and no responsive image variants are generated. The total request limit
is 60 MiB, including all admin inline uploads, not 60 MiB per file.
Media URLs are public, including draft uploads. Unpublishing does not revoke
files or copies already downloaded/cached. Only trusted administrators may upload;
this same-origin arrangement is not appropriate for untrusted user uploads.

## Checks

```sh
./.venv/bin/uv run --env-file .env python manage.py check
./.venv/bin/uv run --env-file .env python manage.py test
./.venv/bin/uv run --env-file .env python manage.py makemigrations --check --dry-run
```

CI uses isolated environment variables, not `.env` or deployment secrets, and also
builds the production image and runs `bash deploy/smoke-test.sh` against a disposable
tmpfs disk. It checks migrations, readiness, static files, audio ranges, denied
active media/symlinks, and spoofed forwarding headers. Requires Docker for the
integration test; run `docker build -t website-ci .` first.

Django reads environment variables; `.env` is loaded explicitly by uv. Secrets,
local databases, generated assets and uploads are ignored by Git.

## Content and enquiries

Publish real works through the admin; no compositions or factual biography are
seeded. Publish *Nunc dimittis* with slug `nunc-dimittis` to prioritize it on the
homepage. All composition SEO titles include the composition name and Thomas Alban. Add the confirmed Clare College
recording URL and its verified credit in the Listening link inline (Choir of Clare
College, Cambridge, only for that recording). Add separate verified credits for
any other recordings. The homepage otherwise selects a featured published composition.
Replace the About biography placeholder before launch and have the owner verify
the existing homepage introduction; no new biography is fabricated by deployment.

Category filters use published categories. Duration groups are under 5 minutes,
5–10 minutes inclusive, and over 10 minutes; works without duration are omitted
only when a duration filter is selected. Invalid filters display errors and leave
the catalogue unfiltered. Missing work metadata is not displayed.

Score enquiries include an optional **Approx. Copy Count**; general contact forms
omit it and ignore any submitted copy count. The Contact page also links directly
to thomasalbanmusic@gmail.com and Thomas Alban's LinkedIn profile. These public
links do not change the environment-configured enquiry delivery addresses.

Set `DJANGO_DEFAULT_FROM_EMAIL` to a provider-authorized sender and
`DJANGO_ENQUIRY_EMAIL` to the recipient. For production set
`DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` and configure
host, port, credentials and TLS using `.env.example`. Use TLS or SSL, not both.
Forms use CSRF, a hidden honeypot and a 60-second session cooldown after sending.
Score enquiries resolve the published composition server-side. The visitor is
Reply-To, never the sender. Only backend acceptance produces a one-use success
confirmation; failed delivery leaves the form with an error. Console output in
DEBUG is for testing only, not real email delivery; console/file/dummy backends
are rejected outside DEBUG. With either address unset, enquiries stay disabled.
Production acceptance is not proof of inbox delivery: verify end-to-end delivery
and configure SPF/DKIM/DMARC with the provider. No enquiry database records are
stored, but messages reach the configured mailbox and sessions retain cooldowns.

## Production deployment

See [Render deployment and operations](docs/deployment.md) for the GitHub-connected
paid single-service setup, exact build/start commands, SMTP/domain/TLS setup,
launch blockers, monitoring, security boundary, and proposed backup/restore
interface. `render.yaml` is a proposal, not a purchase or an already-live service.
No deployment, paid resource creation, mail delivery or production data changes
are performed by this repository change.
