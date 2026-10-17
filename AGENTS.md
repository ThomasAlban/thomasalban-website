# Goal & stack
- Fast, elegant, SEO-first composer website for Thomas Alban. Simple, maintainable, mobile-friendly, accessible.
- - Top priority: website high in search results for "Thomas Alban", "Thomas Alban <Composition>" (e.g. "Thomas Alban Nunc Dimittis"), etc.
- Uses uv, Python, latest stable Django, server-rendered templates, lightweight responsive CSS, minimal JS (No heavy frontend framework).
- `config`: settings/routes; `core`: homepage, About, Contact, enquiries; `compositions`: catalogue and work pages. SQLite locally; persistent database/uploads with backups in production. Manage compositions via Django admin.

# Features
- Pages: `/`, `/compositions/`, `/compositions/<slug>/`, `/about/`, `/contact/`. Homepage has feature area which will be set to *Nunc dimittis* by user, recent works; catalogue lists newest first with various filters.
- Composition fields include title, slug, description, year_composed, premiered_date, category, instrumentation, duration_seconds, optional audio_file/audio_credit and seo_description, is_published, is_featured. Ordered listening links with per-recording credits, score previews and composition images are related models. Hide unpublished compositions and missing metadata; order by premiere date, then year and ID with missing values last.
- Work pages show metadata, recording links, previews, and score enquiries with the composition preselected. Enquiry fields: name, email, optional copy count/message. General contact shares the email infrastructure.
- Explicit owner preference: allowlisted primary YouTube/Spotify players load eagerly as server-rendered iframes on page load, without autoplay, a Load button or site JavaScript. Providers are intentionally contacted on load; do not restore click-to-load behavior. Keep titles, provider classes, external fallback links and credits. Use iframe `referrerpolicy="strict-origin-when-cross-origin"`, not `no-referrer`, because YouTube needs Referer (missing it can cause Error 153). This preference does not establish a consent policy.
- Validate with Django forms; use CSRF, basic anti-spam, authenticated sender, visitor Reply-To, and success confirmation only after successful delivery.

# SEO & design
- Use unique titles/descriptions, canonical URLs, Open Graph, XML sitemap, robots.txt, Person/MusicComposition JSON-LD, semantic HTML, descriptive alt text, internal links. Allow Google/Bing and AI search crawlers including OAI-SearchBot; avoid indexing admin and unnecessary filtered URLs.
- Always use the ASCII hyphen "-", never an em dash, in copy, documentation, and responses.
- Forest green/cream aesthetic, clear typography, excellent mobile navigation, compressed responsive images/previews. Avoid excessive/slow animations (should always feel instant/snappy), heavy embeds, unnecessary dependencies; aim for excellent Lighthouse scores.

# Delivery & checks
- Keep secrets/config in env vars. Prod requires HTTPS, DEBUG=False, secure cookies, explicit allowed hosts, secure admin, persistent storage/backups, and reliable email delivery.
- Public pages, SEO, media and enquiries are implemented; current deployment is a paid single Render Docker service with nginx/Gunicorn and `/var/data` SQLite/media. Migrate only at runtime on the mounted disk. See `docs/deployment.md`; backup tooling remains a separate task and privacy approval is a launch blocker.
- Always use the repository-local `./.venv/bin/uv`, never plain `uv`. Add automated tests as features land. Run `./.venv/bin/uv run --env-file .env python manage.py check`, `./.venv/bin/uv run --env-file .env python manage.py test` and `./.venv/bin/uv run --env-file .env python manage.py makemigrations --check --dry-run` after changes. When instructed not to access `.env` or local data, use isolated environment variables and `--no-env-file`. Document deployment and Search Console sitemap submission.
- Done means visitors can discover *Nunc dimittis* (setup by user via Django admin), explore works, follow recordings, preview scores, submit working enquiries; public content indexable and admin-manageable.
