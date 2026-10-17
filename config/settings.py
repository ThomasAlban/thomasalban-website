"""Shared settings; configuration is read from environment variables."""

import ipaddress
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

def env_bool(name, default=False):
    value = os.environ.get(name, str(default)).lower()
    if value not in {'true', 'false'}:
        raise ImproperlyConfigured(f'{name} must be true or false.')
    return value == 'true'


def env_int(name, default, minimum, maximum=None):
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        raise ImproperlyConfigured(f'{name} must be an integer.') from None
    if value < minimum or (maximum is not None and value > maximum):
        raise ImproperlyConfigured(f'{name} is outside the allowed range.')
    return value


def valid_host(host):
    # Exact DNS names or IP literals only, never wildcard/suffix host patterns.
    try:
        ipaddress.ip_address(host[1:-1] if host.startswith('[') and host.endswith(']') else host)
        return ':' not in host or (host.startswith('[') and host.endswith(']'))
    except ValueError:
        return len(host) <= 253 and all(
            re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label)
            for label in host.split('.')
        )


def validated_origin(value, name):
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = parsed.hostname
        valid = (
            value and not any(character.isspace() or ord(character) < 32 for character in value)
            and parsed.scheme in {'http', 'https'} and host
            and valid_host(f'[{host}]' if ':' in host else host)
            and parsed.username is None and parsed.password is None
            and parsed.path in {'', '/'} and '?' not in value and '#' not in value
            and not parsed.netloc.endswith(':') and (port is None or port > 0)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ImproperlyConfigured(f'{name} must be an HTTP(S) origin without credentials, path, query or fragment.')
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == 'localhost'
    if not DEBUG and not local and parsed.scheme != 'https':
        raise ImproperlyConfigured(f'{name} must use HTTPS in production.')
    return value.rstrip('/')


DEBUG = env_bool('DJANGO_DEBUG')
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY and DEBUG:
    SECRET_KEY = 'django-insecure-local-development-only'
if not DEBUG and (
    len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5
    or SECRET_KEY.startswith('django-insecure-')
    or SECRET_KEY != SECRET_KEY.strip()
    or any(marker in SECRET_KEY.lower() for marker in ('replace', 'changeme', 'change-me'))
):
    raise ImproperlyConfigured('DJANGO_SECRET_KEY must be a strong, non-placeholder production key (at least 50 characters and 5 distinct characters).')

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1' if DEBUG else '').split(',')
    if host.strip()
]
if not DEBUG and (not ALLOWED_HOSTS or not all(valid_host(host) for host in ALLOWED_HOSTS)):
    raise ImproperlyConfigured('DJANGO_ALLOWED_HOSTS must contain explicit hostnames or IP literals, without wildcards, schemes or ports.')
CSRF_FAILURE_VIEW = 'core.views.csrf_failure'
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
    'core.apps.CoreConfig',
    'compositions.apps.CompositionsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Production must point this at a persistent volume and arrange backups.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.environ.get('DJANGO_DATABASE_PATH', str(BASE_DIR / 'db.sqlite3')),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-gb'
TIME_ZONE = 'Europe/London'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_URL = '/media/'
MEDIA_ROOT = Path(os.environ.get('DJANGO_MEDIA_ROOT', str(BASE_DIR / 'media')))
if not DEBUG:
    for name in ('DJANGO_DATABASE_PATH', 'DJANGO_MEDIA_ROOT'):
        value = os.environ.get(name, '')
        if not value or not Path(value).is_absolute():
            raise ImproperlyConfigured(f'{name} must be an explicit absolute persistent-storage path in production.')
# Do not stat or create storage paths here: Render's disk is absent during builds.

SITE_URL = validated_origin(
    os.environ.get('DJANGO_SITE_URL', 'http://localhost:8000' if DEBUG else ''),
    'DJANGO_SITE_URL',
)
CSRF_TRUSTED_ORIGINS = [
    validated_origin(origin, 'DJANGO_CSRF_TRUSTED_ORIGINS')
    for origin in CSRF_TRUSTED_ORIGINS
]

# Local console output is not delivery. Configure SMTP before launch.
MAILERS = {
    'default': {
        'BACKEND': os.environ.get('DJANGO_EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend'),
        'OPTIONS': {},
    },
}
if MAILERS['default']['BACKEND'] == 'django.core.mail.backends.smtp.EmailBackend':
    MAILERS['default']['OPTIONS'] = {
        'host': os.environ.get('DJANGO_EMAIL_HOST', ''),
        'port': env_int('DJANGO_EMAIL_PORT', 587, 1, 65535),
        'username': os.environ.get('DJANGO_EMAIL_HOST_USER', ''),
        'password': os.environ.get('DJANGO_EMAIL_HOST_PASSWORD', ''),
        'use_tls': env_bool('DJANGO_EMAIL_USE_TLS', True),
        'use_ssl': env_bool('DJANGO_EMAIL_USE_SSL'),
        'timeout': 15,
    }
    if MAILERS['default']['OPTIONS']['use_tls'] and MAILERS['default']['OPTIONS']['use_ssl']:
        raise ImproperlyConfigured('Enable only one of DJANGO_EMAIL_USE_TLS and DJANGO_EMAIL_USE_SSL.')
# Do not require live email credentials during builds. Enquiry delivery separately
# rejects missing addresses and non-delivery backends in production.
DEFAULT_FROM_EMAIL = os.environ.get('DJANGO_DEFAULT_FROM_EMAIL', '')
ENQUIRY_EMAIL = os.environ.get('DJANGO_ENQUIRY_EMAIL', '')

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
# Enable only behind a trusted proxy. Our Render nginx config overwrites this
# with HTTPS, ignoring incoming headers; Render's edge redirects HTTP to HTTPS.
SECURE_PROXY_SSL_HEADER = (
    ('HTTP_X_FORWARDED_PROTO', 'https')
    if env_bool('DJANGO_TRUST_PROXY_HEADERS') else None
)
# Start disabled; enable a short duration after verifying HTTPS in production.
SECURE_HSTS_SECONDS = env_int('DJANGO_SECURE_HSTS_SECONDS', 0, 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS')
SECURE_HSTS_PRELOAD = env_bool('DJANGO_SECURE_HSTS_PRELOAD')
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
