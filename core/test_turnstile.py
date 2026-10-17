import json
import os
import runpy
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs

from django.core.exceptions import ImproperlyConfigured
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings

from core.enquiries import ERROR_MESSAGE, SESSION_KEY, deliver_enquiry
from core.forms import EnquiryForm
from core.turnstile import MAX_RESPONSE_BYTES, VERIFY_URL, verify_turnstile


@override_settings(
    DEBUG=False,
    TURNSTILE_ENABLED=True,
    TURNSTILE_HOSTNAMES=(),
    TURNSTILE_SITE_KEY='public-site-key',
    TURNSTILE_SECRET_KEY='private-secret-key',
    SITE_URL='https://thomasalban.com',
)
class TurnstileTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().post('/contact/', {
            'cf-turnstile-response': 'visitor-token',
        })
        self.network = patch('core.turnstile.urlopen')
        self.urlopen = self.network.start()
        self.addCleanup(self.network.stop)
        self.response = self.urlopen.return_value.__enter__.return_value
        self.set_result({
            'success': True, 'hostname': 'thomasalban.com', 'action': 'enquiry',
        })

    def set_result(self, result):
        self.response.read.return_value = json.dumps(result).encode('utf-8')

    def test_success_and_exact_request_fields(self):
        self.assertTrue(verify_turnstile(self.request))
        self.urlopen.assert_called_once()
        args, kwargs = self.urlopen.call_args
        request = args[0]
        self.assertEqual(request.full_url, VERIFY_URL)
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Content-type'), 'application/x-www-form-urlencoded')
        self.assertEqual(parse_qs(request.data.decode('utf-8')), {
            'secret': ['private-secret-key'], 'response': ['visitor-token'],
        })
        self.assertEqual(kwargs, {'timeout': 5})
        self.response.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)

    def test_success_must_be_boolean_true(self):
        for success in (False, None, 1, 'true', [], {}):
            with self.subTest(success=success):
                self.set_result({
                    'success': success, 'hostname': 'thomasalban.com', 'action': 'enquiry',
                })
                self.assertFalse(verify_turnstile(self.request))

    def test_wrong_or_missing_hostname_and_action(self):
        for field, value in (
            ('hostname', 'attacker.example'), ('hostname', None),
            ('hostname', 'www.thomasalban.com'), ('action', 'contact'), ('action', None),
        ):
            with self.subTest(field=field, value=value):
                result = {'success': True, 'hostname': 'thomasalban.com', 'action': 'enquiry'}
                result[field] = value
                self.set_result(result)
                self.assertFalse(verify_turnstile(self.request))

    @override_settings(TURNSTILE_HOSTNAMES=('thomasalban.com', 'www.thomasalban.com'))
    def test_configured_hostnames_allow_www_and_reject_unknown(self):
        for hostname, expected in (
            ('thomasalban.com', True), ('www.thomasalban.com', True),
            ('attacker.example', False),
        ):
            with self.subTest(hostname=hostname):
                self.set_result({'success': True, 'hostname': hostname, 'action': 'enquiry'})
                self.assertEqual(verify_turnstile(self.request), expected)

    @override_settings(TURNSTILE_HOSTNAMES=('www.thomasalban.com',))
    def test_configured_list_replaces_canonical_and_ignores_request_headers(self):
        self.request.META['HTTP_HOST'] = 'thomasalban.com'
        self.request.META['HTTP_X_FORWARDED_HOST'] = 'thomasalban.com'
        self.assertFalse(verify_turnstile(self.request))
        self.set_result({'success': True, 'hostname': 'www.thomasalban.com', 'action': 'enquiry'})
        self.assertTrue(verify_turnstile(self.request))

    def test_site_url_uses_hostname_not_port_or_scheme(self):
        with self.settings(SITE_URL='https://thomasalban.com:8443/'):
            self.assertTrue(verify_turnstile(self.request))

    def test_non_dictionary_json_fails_closed(self):
        for result in ([], None, True, 'success', 1):
            with self.subTest(result=result):
                self.set_result(result)
                self.assertFalse(verify_turnstile(self.request))

    def test_malformed_json_and_encoding_fail_closed_with_sanitized_logs(self):
        for body in (b'not-json-private-secret-key', b'\xff'):
            with self.subTest(body=body):
                self.response.read.return_value = body
                with self.assertLogs('core.turnstile', level='WARNING') as logs:
                    self.assertFalse(verify_turnstile(self.request))
                self.assertEqual(logs.output, ['WARNING:core.turnstile:Turnstile verification failed.'])

    def test_oversized_response_fails_closed(self):
        self.response.read.return_value = b' ' * (MAX_RESPONSE_BYTES + 1)
        self.assertFalse(verify_turnstile(self.request))

    def test_missing_empty_and_oversized_tokens_do_not_use_network(self):
        for data in ({}, {'cf-turnstile-response': ''}, {'cf-turnstile-response': 'x' * 2049}):
            with self.subTest(length=len(data.get('cf-turnstile-response', ''))):
                self.assertFalse(verify_turnstile(RequestFactory().post('/contact/', data)))
        self.urlopen.assert_not_called()

    def test_maximum_length_token_is_accepted(self):
        request = RequestFactory().post('/contact/', {'cf-turnstile-response': 'x' * 2048})
        self.assertTrue(verify_turnstile(request))

    def test_network_errors_and_timeout_fail_closed_with_sanitized_logs(self):
        for error in (TimeoutError('private-secret-key'), URLError('visitor-token')):
            with self.subTest(error=type(error).__name__):
                self.urlopen.side_effect = error
                with self.assertLogs('core.turnstile', level='WARNING') as logs:
                    self.assertFalse(verify_turnstile(self.request))
                self.assertEqual(logs.output, ['WARNING:core.turnstile:Turnstile verification failed.'])

    def test_missing_keys_fail_closed_without_network(self):
        for setting in ('TURNSTILE_SITE_KEY', 'TURNSTILE_SECRET_KEY'):
            with self.subTest(setting=setting), self.settings(**{setting: ''}):
                self.assertFalse(verify_turnstile(self.request))
        self.urlopen.assert_not_called()

    def test_only_debug_can_disable_verification(self):
        with self.settings(TURNSTILE_ENABLED=False, DEBUG=True):
            self.assertTrue(verify_turnstile(self.request))
        with self.settings(TURNSTILE_ENABLED=False, DEBUG=False):
            self.assertFalse(verify_turnstile(self.request))
        self.urlopen.assert_not_called()

    def test_enabled_debug_still_requires_verification(self):
        with self.settings(DEBUG=True):
            self.assertTrue(verify_turnstile(self.request))
        self.urlopen.assert_called_once()

    def test_shared_widget_and_public_key_only(self):
        html = render_to_string('includes/enquiry_form.html', {'form': EnquiryForm()})
        self.assertIn('https://challenges.cloudflare.com/turnstile/v0/api.js', html)
        self.assertIn('async defer', html)
        self.assertIn('data-sitekey="public-site-key"', html)
        self.assertIn('data-action="enquiry"', html)
        self.assertIn('<noscript>', html)
        self.assertIn('mailto:thomasalbanmusic@gmail.com', html)
        self.assertNotIn('private-secret-key', html)

    def test_widget_visibility_in_debug_and_production(self):
        with self.settings(DEBUG=True, TURNSTILE_ENABLED=False):
            html = render_to_string('includes/enquiry_form.html', {'form': EnquiryForm()})
            self.assertNotIn('cf-turnstile', html)
        with self.settings(DEBUG=False, TURNSTILE_ENABLED=False):
            self.assertTrue(EnquiryForm().turnstile_enabled)


class TurnstileHostnameSettingsTests(SimpleTestCase):
    def load_settings(self, value=None):
        environment = {'DJANGO_DEBUG': 'True', 'DJANGO_DATABASE_PATH': ':memory:'}
        if value is not None:
            environment['DJANGO_TURNSTILE_HOSTNAMES'] = value
        with patch.dict(os.environ, environment, clear=True):
            return runpy.run_path(str(Path(__file__).resolve().parent.parent / 'config/settings.py'))['TURNSTILE_HOSTNAMES']

    def test_default_is_empty_tuple(self):
        self.assertEqual(self.load_settings(), ())
        self.assertEqual(self.load_settings(''), ())

    def test_comma_separated_hosts_are_trimmed(self):
        self.assertEqual(
            self.load_settings(' thomasalban.com, www.thomasalban.com '),
            ('thomasalban.com', 'www.thomasalban.com'),
        )

    def test_invalid_hosts_raise_configuration_error(self):
        for hostname in (
            '*', '*.thomasalban.com', '.thomasalban.com',
            'https://thomasalban.com', 'thomasalban.com:443',
            'thomasalban.com/path', 'bad host',
        ):
            with self.subTest(hostname=hostname):
                with self.assertRaisesMessage(ImproperlyConfigured, 'DJANGO_TURNSTILE_HOSTNAMES'):
                    self.load_settings(f'thomasalban.com,{hostname}')


@override_settings(
    DEBUG=True,
    DEFAULT_FROM_EMAIL='composer@example.com',
    ENQUIRY_EMAIL='enquiries@example.com',
    MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
)
class TurnstileDeliveryGateTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().post('/contact/')
        self.request.session = {}
        self.data = {'name': 'Visitor', 'email': 'visitor@example.com'}

    def test_rejection_precedes_budget_and_smtp_for_both_forms(self):
        for include_copy_count in (True, False):
            with (
                self.subTest(include_copy_count=include_copy_count),
                patch('core.enquiries.verify_turnstile', return_value=False) as verify,
                patch('core.enquiries.reserve_enquiry_attempt') as reserve,
                patch('core.enquiries.EmailMessage') as email,
            ):
                form = EnquiryForm(self.data, include_copy_count=include_copy_count)
                self.assertFalse(deliver_enquiry(self.request, form))
                verify.assert_called_once_with(self.request)
                reserve.assert_not_called()
                email.assert_not_called()
                self.assertEqual(list(form.non_field_errors()), [ERROR_MESSAGE])
                self.assertNotIn(SESSION_KEY, self.request.session)

    def test_early_guards_skip_verification(self):
        cases = (
            ({'email': 'invalid'}, {}, {}),
            ({'website': 'spam'}, {}, {}),
            ({}, {SESSION_KEY: 1000}, {}),
            ({}, {}, {'ENQUIRY_EMAIL': ''}),
            ({}, {}, {'DEFAULT_FROM_EMAIL': ''}),
            ({}, {}, {'DEBUG': False}),
        )
        for overrides, session, settings_overrides in cases:
            with (
                self.subTest(overrides=overrides, settings=settings_overrides),
                self.settings(**settings_overrides),
                patch('core.enquiries.time', return_value=1001),
                patch('core.enquiries.verify_turnstile') as verify,
                patch('core.enquiries.reserve_enquiry_attempt') as reserve,
            ):
                self.request.session = session
                form = EnquiryForm({**self.data, **overrides})
                self.assertFalse(deliver_enquiry(self.request, form))
                verify.assert_not_called()
                reserve.assert_not_called()

    def test_success_continues_to_budget_and_delivery(self):
        with (
            patch('core.enquiries.verify_turnstile', return_value=True) as verify,
            patch('core.enquiries.reserve_enquiry_attempt', return_value=True) as reserve,
            patch('core.enquiries.EmailMessage') as email,
        ):
            email.return_value.send.return_value = 1
            self.assertTrue(deliver_enquiry(self.request, EnquiryForm(self.data)))
            verify.assert_called_once_with(self.request)
            reserve.assert_called_once()
            email.return_value.send.assert_called_once_with(using='default')
            self.assertIn(SESSION_KEY, self.request.session)
