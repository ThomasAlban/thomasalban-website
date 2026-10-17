FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends nginx util-linux openssl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home app \
    && python -m venv /app/.venv \
    && /app/.venv/bin/pip install --no-cache-dir uv==0.13.0
COPY pyproject.toml uv.lock ./
# Fresh environment: retain bootstrap uv without introducing stray app dependencies.
RUN ./.venv/bin/uv sync --locked --no-dev --inexact \
    && test -x ./.venv/bin/uv && ./.venv/bin/uv --version
COPY . .
# Build settings are deliberately isolated from deployment secrets and storage.
RUN DJANGO_DEBUG=true DJANGO_SECRET_KEY=build-only DJANGO_DATABASE_PATH=/unmounted/db.sqlite3 \
    DJANGO_MEDIA_ROOT=/unmounted/media .venv/bin/python manage.py collectstatic --noinput
COPY deploy/nginx.conf /etc/nginx/nginx.conf
EXPOSE 10000
CMD ["bash", "deploy/start.sh"]
