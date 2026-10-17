"""Exercise the real settings module without inheriting environment secrets."""

from unittest.mock import patch

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from .test_settings import PRODUCTION_ENVIRONMENT, load_settings


class EmailConfigurationTests(SimpleTestCase):
    def load_mailers(self, **environment):
        return load_settings(**environment)['MAILERS']

    def test_default_console_configuration_constructs_without_smtp_options(self):
        mailers = self.load_mailers()
        self.assertEqual(mailers['default'], {
            'BACKEND': 'django.core.mail.backends.console.EmailBackend',
            'OPTIONS': {},
        })
        with override_settings(MAILERS=mailers):
            backend = mail.mailers['default']
            self.assertEqual(backend.__class__.__module__, 'django.core.mail.backends.console')

    def test_non_smtp_backends_ignore_smtp_environment(self):
        for name in ['console', 'dummy', 'locmem', 'filebased']:
            with self.subTest(backend=name):
                mailers = self.load_mailers(
                    DJANGO_EMAIL_BACKEND=f'django.core.mail.backends.{name}.EmailBackend',
                    DJANGO_EMAIL_HOST='smtp.example.com',
                    DJANGO_EMAIL_PORT='not-a-port',
                    DJANGO_EMAIL_HOST_USER='test-user',
                    DJANGO_EMAIL_HOST_PASSWORD='test-password',
                    DJANGO_EMAIL_USE_TLS='invalid',
                    DJANGO_EMAIL_USE_SSL='invalid',
                )
                self.assertEqual(mailers['default']['OPTIONS'], {})

    def test_smtp_configuration_constructs_with_environment_options(self):
        mailers = self.load_mailers(
            DJANGO_EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
            DJANGO_EMAIL_HOST='smtp.example.com',
            DJANGO_EMAIL_PORT='465',
            DJANGO_EMAIL_HOST_USER='test-user',
            DJANGO_EMAIL_HOST_PASSWORD='test-password',
            DJANGO_EMAIL_USE_TLS='false',
            DJANGO_EMAIL_USE_SSL='true',
        )
        expected = {
            'host': 'smtp.example.com', 'port': 465,
            'username': 'test-user', 'password': 'test-password',
            'use_tls': False, 'use_ssl': True, 'timeout': 15,
        }
        self.assertEqual(mailers['default']['OPTIONS'], expected)
        # Constructing the backend must not open a network connection.
        with override_settings(MAILERS=mailers), patch(
            'django.core.mail.backends.smtp.EmailBackend.open',
            side_effect=AssertionError('Tests must not connect to SMTP'),
        ) as open_connection:
            backend = mail.mailers['default']
            for name, value in expected.items():
                self.assertEqual(getattr(backend, name), value)
            open_connection.assert_not_called()

    def test_smtp_invalid_options_fail_at_configuration(self):
        for environment in (
            {'DJANGO_EMAIL_USE_SSL': 'true'},
            {'DJANGO_EMAIL_PORT': 'not-a-port'},
            {'DJANGO_EMAIL_PORT': '0'},
            {'DJANGO_EMAIL_PORT': '65536'},
            {'DJANGO_EMAIL_USE_TLS': 'yes'},
        ):
            with self.subTest(environment=environment), self.assertRaises(ImproperlyConfigured):
                self.load_mailers(
                    DJANGO_EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
                    **environment,
                )

    def test_production_smtp_import_needs_no_credentials(self):
        mailers = self.load_mailers(
            **PRODUCTION_ENVIRONMENT,
            DJANGO_EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
        )
        self.assertEqual(mailers['default']['OPTIONS']['password'], '')
        self.assertEqual(mailers['default']['OPTIONS']['username'], '')

    def test_smtp_defaults(self):
        mailers = self.load_mailers(
            DJANGO_EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
        )
        self.assertEqual(mailers['default']['OPTIONS'], {
            'host': '', 'port': 587, 'username': '', 'password': '',
            'use_tls': True, 'use_ssl': False, 'timeout': 15,
        })
