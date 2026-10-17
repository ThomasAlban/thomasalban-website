"""Settings regressions use isolated environments, never developer credentials."""

import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


PRODUCTION_ENVIRONMENT = {
    'DJANGO_DEBUG': 'false',
    'DJANGO_SECRET_KEY': 'test-only-key-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ-abcdef',
    'DJANGO_ALLOWED_HOSTS': 'example.com,www.example.com,app.onrender.com',
    'DJANGO_SITE_URL': 'https://example.com',
    'DJANGO_DATABASE_PATH': '/unmounted-test-disk/db.sqlite3',
    'DJANGO_MEDIA_ROOT': '/unmounted-test-disk/media',
}


def load_settings(**environment):
    settings_path = Path(__file__).resolve().parent.parent / 'config' / 'settings.py'
    with patch.dict(os.environ, {'DJANGO_DEBUG': 'true', **environment}, clear=True):
        return runpy.run_path(str(settings_path))


class ProductionConfigurationTests(SimpleTestCase):
    def production(self, **environment):
        return load_settings(**{**PRODUCTION_ENVIRONMENT, **environment})

    def test_local_defaults(self):
        settings = load_settings()
        self.assertTrue(settings['DEBUG'])
        self.assertEqual(settings['SITE_URL'], 'http://localhost:8000')
        self.assertEqual(settings['ALLOWED_HOSTS'], ['localhost', '127.0.0.1'])
        self.assertFalse(settings['SECURE_SSL_REDIRECT'])
        self.assertFalse(settings['SESSION_COOKIE_SECURE'])
        self.assertFalse(settings['CSRF_COOKIE_SECURE'])

    def test_production_defaults_and_storage(self):
        settings = self.production()
        for name in ('SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE', 'SECURE_SSL_REDIRECT'):
            self.assertTrue(settings[name])
        self.assertIsNone(settings['SECURE_PROXY_SSL_HEADER'])
        self.assertEqual(settings['SECURE_HSTS_SECONDS'], 0)
        self.assertFalse(settings['SECURE_HSTS_INCLUDE_SUBDOMAINS'])
        self.assertFalse(settings['SECURE_HSTS_PRELOAD'])
        self.assertEqual(settings['DATABASES']['default']['NAME'], '/unmounted-test-disk/db.sqlite3')
        self.assertEqual(settings['MEDIA_ROOT'], Path('/unmounted-test-disk/media'))
        self.assertEqual(settings['STATIC_ROOT'], settings['BASE_DIR'] / 'staticfiles')
        self.assertEqual(settings['MAILERS']['default']['OPTIONS'], {})

    def test_production_essentials_must_be_explicit(self):
        for name in PRODUCTION_ENVIRONMENT.keys() - {'DJANGO_DEBUG'}:
            environment = PRODUCTION_ENVIRONMENT.copy()
            del environment[name]
            with self.subTest(name=name), self.assertRaises(ImproperlyConfigured):
                load_settings(**environment)

    def test_weak_and_placeholder_secrets(self):
        for key in ('', 'short', 'x' * 70, 'abcd' * 20,
                    'django-insecure-' + 'abcdef' * 10, 'replace-me-' + 'abcdef' * 10,
                    ' ' + PRODUCTION_ENVIRONMENT['DJANGO_SECRET_KEY']):
            with self.subTest(key=key), self.assertRaisesMessage(ImproperlyConfigured, 'DJANGO_SECRET_KEY'):
                self.production(DJANGO_SECRET_KEY=key)

    def test_production_hosts_are_exact(self):
        for hosts in ('', ',', '*', '.example.com', 'https://example.com',
                      'example.com:443', 'example.com/path', 'bad host', '-bad.com',
                      'example.com,*', 'example..com'):
            with self.subTest(hosts=hosts), self.assertRaisesMessage(ImproperlyConfigured, 'DJANGO_ALLOWED_HOSTS'):
                self.production(DJANGO_ALLOWED_HOSTS=hosts)
        settings = self.production(DJANGO_ALLOWED_HOSTS=' example.com, 127.0.0.1, [::1], ')
        self.assertEqual(settings['ALLOWED_HOSTS'], ['example.com', '127.0.0.1', '[::1]'])

    def test_invalid_origins_including_parser_edge_cases(self):
        for origin in ('', 'example.com', '//example.com', 'ftp://example.com',
                       'https://user:pass@example.com', 'https://@example.com',
                       'https://example.com/path', 'https://example.com//',
                       'https://example.com?query', 'https://example.com?',
                       'https://example.com#fragment', 'https://example.com#',
                       'https://example.com:bad', 'https://example.com:65536',
                       'https://example.com:0', 'https://example.com:',
                       'https://[invalid', 'https://example.com\n',
                       'https://example.com\\evil', 'https://*.example.com'):
            with self.subTest(origin=origin), self.assertRaisesMessage(ImproperlyConfigured, 'DJANGO_SITE_URL'):
                load_settings(DJANGO_SITE_URL=origin)

    def test_production_https_and_local_exceptions(self):
        for origin in ('http://example.com', 'http://localhost.evil.com', 'http://192.168.1.1'):
            with self.subTest(origin=origin), self.assertRaisesMessage(ImproperlyConfigured, 'HTTPS'):
                self.production(DJANGO_SITE_URL=origin)
        for origin in ('http://localhost:8000', 'http://127.0.0.1', 'http://[::1]:8000',
                       'https://example.com:8443'):
            with self.subTest(origin=origin):
                self.assertEqual(self.production(DJANGO_SITE_URL=origin + '/')['SITE_URL'], origin)

    def test_csrf_origins_are_validated(self):
        settings = self.production(DJANGO_CSRF_TRUSTED_ORIGINS=' https://www.example.com/, ')
        self.assertEqual(settings['CSRF_TRUSTED_ORIGINS'], ['https://www.example.com'])
        with self.assertRaisesMessage(ImproperlyConfigured, 'DJANGO_CSRF_TRUSTED_ORIGINS'):
            self.production(DJANGO_CSRF_TRUSTED_ORIGINS='https://example.com/path')

    def test_proxy_and_hsts_are_explicit_opt_ins(self):
        settings = self.production(
            DJANGO_TRUST_PROXY_HEADERS='true', DJANGO_SECURE_HSTS_SECONDS='300',
            DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS='true', DJANGO_SECURE_HSTS_PRELOAD='true',
        )
        self.assertEqual(settings['SECURE_PROXY_SSL_HEADER'], ('HTTP_X_FORWARDED_PROTO', 'https'))
        self.assertEqual(settings['SECURE_HSTS_SECONDS'], 300)
        self.assertTrue(settings['SECURE_HSTS_INCLUDE_SUBDOMAINS'])
        self.assertTrue(settings['SECURE_HSTS_PRELOAD'])

    def test_invalid_security_values_fail_clearly(self):
        for name, value in (
            ('DJANGO_DEBUG', 'typo'), ('DJANGO_TRUST_PROXY_HEADERS', '1'),
            ('DJANGO_SECURE_HSTS_SECONDS', '-1'), ('DJANGO_SECURE_HSTS_SECONDS', 'abc'),
            ('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', 'yes'),
            ('DJANGO_SECURE_HSTS_PRELOAD', 'yes'),
            ('DJANGO_DATABASE_PATH', ''), ('DJANGO_DATABASE_PATH', 'db.sqlite3'),
            ('DJANGO_MEDIA_ROOT', 'media'),
        ):
            with self.subTest(name=name, value=value), self.assertRaisesMessage(ImproperlyConfigured, name):
                self.production(**{name: value})

    def test_collectstatic_without_mounted_disk_or_email_credentials(self):
        settings = self.production()
        overrides = {name: value for name, value in settings.items() if name.isupper()}
        with TemporaryDirectory() as static_root:
            overrides['STATIC_ROOT'] = static_root
            with override_settings(**overrides):
                call_command('collectstatic', interactive=False, verbosity=0)
            self.assertTrue(any(Path(static_root).iterdir()))
