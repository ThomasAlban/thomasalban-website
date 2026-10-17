"""Network-free transport double for production enquiry tests only."""

from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.locmem import EmailBackend as LocmemEmailBackend


class AcceptedEmailBackend(BaseEmailBackend):
    """Simulate transport acceptance without weakening the production guard."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.capture = LocmemEmailBackend()

    def send_messages(self, email_messages):
        return self.capture.send_messages(email_messages)


class WrappedLocmemEmailBackend(LocmemEmailBackend):
    """A wrapper must still be rejected as non-delivery in production."""


ACCEPTED_MAILERS = {
    'default': {'BACKEND': 'core.test_mail_backend.AcceptedEmailBackend'},
}
