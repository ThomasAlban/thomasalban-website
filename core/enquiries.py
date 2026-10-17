"""Delivery shared by contact and score enquiries; no public views here."""

import logging
from time import time

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail.backends.console import EmailBackend as ConsoleEmailBackend
from django.core.mail.backends.dummy import EmailBackend as DummyEmailBackend
from django.core.mail.backends.locmem import EmailBackend as LocmemEmailBackend
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)

ERROR_MESSAGE = 'Your enquiry could not be sent. Please try again later.'
SESSION_KEY = 'enquiry_last_sent_at'
RATE_LIMIT_SECONDS = 60


def deliver_enquiry(request, form, composition=None):
    """Return True only for one accepted message; otherwise add a form error.

    Requires SessionMiddleware. The optional composition must be resolved by the
    caller, not taken from submitted form data. Only successful sends start the
    session cooldown. This is basic anti-spam, not a cross-session rate limiter.
    """
    if not form.is_valid():
        return False

    def reject():
        form.add_error(None, ERROR_MESSAGE)
        return False

    if form.cleaned_data['website']:
        return reject()

    now = time()
    last_sent = request.session.get(SESSION_KEY)
    if isinstance(last_sent, (int, float)) and now - last_sent < RATE_LIMIT_SECONDS:
        return reject()

    recipient = getattr(settings, 'ENQUIRY_EMAIL', '').strip()
    if not recipient or not settings.DEFAULT_FROM_EMAIL.strip():
        return reject()

    try:
        config = settings.MAILERS['default']
        backend = import_string(config.get(
            'BACKEND', 'django.core.mail.backends.smtp.EmailBackend',
        ))
        # File-based email inherits the console backend. Also reject subclasses
        # so a custom wrapper cannot accidentally bypass this production guard.
        if not settings.DEBUG and issubclass(
            backend, (ConsoleEmailBackend, DummyEmailBackend, LocmemEmailBackend),
        ):
            return reject()

        data = form.cleaned_data
        subject = 'Contact enquiry'
        lines = []
        if composition is not None:
            subject = 'Score enquiry'
            lines.append(f'Composition: {composition.title}')
        lines.extend([
            f'Name: {data["name"]}',
            f'Email: {data["email"]}',
        ])
        if data.get('copy_count') is not None:
            lines.append(f'Copies: {data["copy_count"]}')
        if data['message']:
            lines.extend(['', 'Message:', data['message']])

        email = EmailMessage(
            subject=subject,
            body='\n'.join(lines),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
            reply_to=[data['email']],
        )
        if email.send(using='default') != 1:
            logger.warning('Enquiry delivery did not accept one message.')
            return reject()
    except Exception:
        # Backend exceptions can contain addresses, credentials or message text.
        # Deliberately omit exception details and traceback from the log.
        logger.error('Enquiry delivery failed.')
        return reject()

    request.session[SESSION_KEY] = time()
    return True
