from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.test import RequestFactory, SimpleTestCase, override_settings

from compositions.models import Composition
from core.enquiries import ERROR_MESSAGE, SESSION_KEY, deliver_enquiry
from core.forms import EnquiryForm
from core.test_mail_backend import ACCEPTED_MAILERS


class EnquiryFormTests(SimpleTestCase):
    def test_required_fields_and_hidden_honeypot(self):
        form = EnquiryForm({})
        self.assertFalse(form.is_valid())
        self.assertEqual(set(form.errors), {'name', 'email'})
        self.assertTrue(form.fields['website'].widget.is_hidden)

    def test_optional_fields(self):
        form = EnquiryForm({'name': 'Visitor', 'email': 'visitor@example.com'})
        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data['copy_count'])
        self.assertEqual(form.cleaned_data['message'], '')

    def test_copy_count_must_be_a_positive_integer(self):
        for count in ['0', '-1', '1.5', 'many']:
            with self.subTest(count=count):
                form = EnquiryForm({
                    'name': 'Visitor', 'email': 'visitor@example.com',
                    'copy_count': count,
                })
                self.assertFalse(form.is_valid())
                self.assertIn('copy_count', form.errors)

    def test_invalid_email_and_oversized_content(self):
        form = EnquiryForm({
            'name': 'x' * 201, 'email': 'not an email', 'message': 'x' * 10001,
        })
        self.assertFalse(form.is_valid())
        self.assertEqual(set(form.errors), {'name', 'email', 'message'})


@override_settings(
    DEBUG=False,
    MAILERS=ACCEPTED_MAILERS,
    DEFAULT_FROM_EMAIL='composer@example.com',
    ENQUIRY_EMAIL='enquiries@example.com',
)
class EnquiryDeliveryTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().post('/contact/')
        self.request.session = {}
        # Initialising locmem creates the outbox on the first test.
        mail.mailers['default']
        mail.outbox.clear()

    def form(self, **overrides):
        data = {'name': 'Visitor', 'email': 'visitor@example.com'}
        data.update(overrides)
        return EnquiryForm(data)

    def assert_rejected(self, form):
        self.assertFalse(deliver_enquiry(self.request, form))
        self.assertEqual(list(form.non_field_errors()), [ERROR_MESSAGE])
        self.assertNotIn(SESSION_KEY, self.request.session)
        self.assertEqual(mail.outbox, [])

    def test_contact_delivery_uses_configured_sender_and_visitor_reply_to(self):
        with patch('core.enquiries.time', return_value=1000):
            self.assertTrue(deliver_enquiry(self.request, self.form(message='Hello')))
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.subject, 'Contact enquiry')
        self.assertEqual(email.from_email, 'composer@example.com')
        self.assertEqual(email.to, ['enquiries@example.com'])
        self.assertEqual(email.reply_to, ['visitor@example.com'])
        self.assertIn('Name: Visitor', email.body)
        self.assertIn('Email: visitor@example.com', email.body)
        self.assertIn('Message:\nHello', email.body)
        self.assertNotIn('Copies:', email.body)
        self.assertEqual(self.request.session[SESSION_KEY], 1000)

    def test_score_enquiry_uses_server_composition_not_submitted_title(self):
        composition = Composition(title='Nunc dimittis', slug='nunc-dimittis')
        form = self.form(copy_count='12', composition='Forged title')
        self.assertTrue(deliver_enquiry(self.request, form, composition))
        email = mail.outbox[0]
        self.assertEqual(email.subject, 'Score enquiry')
        self.assertIn('Composition: Nunc dimittis', email.body)
        self.assertIn('Copies: 12', email.body)
        self.assertNotIn('Forged title', email.body)
        self.assertNotIn('Message:', email.body)

    def test_invalid_form_does_not_send(self):
        form = self.form(email='invalid')
        self.assertFalse(deliver_enquiry(self.request, form))
        self.assertIn('email', form.errors)
        self.assertEqual(mail.outbox, [])
        self.assertNotIn(SESSION_KEY, self.request.session)

    def test_honeypot_never_reports_success_or_starts_cooldown(self):
        for value in ['https://spam.example', ' ']:
            with self.subTest(value=value):
                self.assert_rejected(self.form(website=value))
        self.assertTrue(deliver_enquiry(self.request, self.form()))

    def test_rate_limit_blocks_until_exactly_sixty_seconds(self):
        with patch('core.enquiries.time', return_value=1000):
            self.assertTrue(deliver_enquiry(self.request, self.form()))
        form = self.form()
        with patch('core.enquiries.time', return_value=1059.99):
            self.assertFalse(deliver_enquiry(self.request, form))
        self.assertEqual(list(form.non_field_errors()), [ERROR_MESSAGE])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.request.session[SESSION_KEY], 1000)
        with patch('core.enquiries.time', return_value=1060):
            self.assertTrue(deliver_enquiry(self.request, self.form()))
        self.assertEqual(len(mail.outbox), 2)

    def test_rate_limit_is_per_session(self):
        self.assertTrue(deliver_enquiry(self.request, self.form()))
        other_request = RequestFactory().post('/contact/')
        other_request.session = {}
        self.assertTrue(deliver_enquiry(other_request, self.form()))
        self.assertEqual(len(mail.outbox), 2)

    def test_cooldown_starts_after_delivery_completes(self):
        with patch('core.enquiries.time', side_effect=[1000, 1010]):
            self.assertTrue(deliver_enquiry(self.request, self.form()))
        self.assertEqual(self.request.session[SESSION_KEY], 1010)

    def test_delivery_exception_logs_no_personal_data_and_allows_retry(self):
        with (
            patch('core.enquiries.EmailMessage.send', side_effect=RuntimeError(
                'visitor@example.com secret message password',
            )),
            self.assertLogs('core.enquiries', level='ERROR') as logs,
        ):
            self.assert_rejected(self.form())
        self.assertEqual(logs.output, ['ERROR:core.enquiries:Enquiry delivery failed.'])
        self.assertTrue(deliver_enquiry(self.request, self.form()))

    def test_only_one_accepted_message_is_success(self):
        for result in [0, None, 2]:
            with (
                self.subTest(result=result),
                patch('core.enquiries.EmailMessage.send', return_value=result),
                self.assertLogs('core.enquiries', level='WARNING'),
            ):
                self.assert_rejected(self.form())
        self.assertTrue(deliver_enquiry(self.request, self.form()))

    def test_blank_recipient_disables_delivery_even_in_debug(self):
        for recipient in ['', '   ']:
            with self.subTest(recipient=recipient), override_settings(
                ENQUIRY_EMAIL=recipient, DEBUG=True,
            ), patch('core.enquiries.EmailMessage.send') as send:
                self.assert_rejected(self.form())
                send.assert_not_called()

    def test_missing_recipient_disables_delivery(self):
        with override_settings():
            del settings.ENQUIRY_EMAIL
            self.assert_rejected(self.form())

    def test_non_delivery_backends_are_rejected_in_production(self):
        backends = [
            f'django.core.mail.backends.{name}.EmailBackend'
            for name in ['console', 'dummy', 'filebased', 'locmem']
        ]
        backends.append('core.test_mail_backend.WrappedLocmemEmailBackend')
        for backend in backends:
            with self.subTest(backend=backend), override_settings(MAILERS={
                'default': {'BACKEND': backend},
            }), patch('core.enquiries.EmailMessage.send') as send:
                self.assert_rejected(self.form())
                send.assert_not_called()

    def test_explicit_debug_console_is_allowed(self):
        output = StringIO()
        with override_settings(DEBUG=True, MAILERS={
            'default': {
                'BACKEND': 'django.core.mail.backends.console.EmailBackend',
                'OPTIONS': {'stream': output},
            },
        }):
            self.assertTrue(deliver_enquiry(self.request, self.form()))
        self.assertIn('Reply-To: visitor@example.com', output.getvalue())
        self.assertIn(SESSION_KEY, self.request.session)

    def test_bad_mailer_configuration_fails_safely(self):
        for mailers in [{}, {'default': {'BACKEND': 'nonexistent.Backend'}}]:
            with (
                self.subTest(mailers=mailers),
                override_settings(MAILERS=mailers),
                self.assertLogs('core.enquiries', level='ERROR'),
            ):
                self.assert_rejected(self.form())
