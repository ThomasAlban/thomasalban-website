"""Delivery shared by contact and score enquiries; no public views here."""

import logging
from time import time

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail.backends.console import EmailBackend as ConsoleEmailBackend
from django.core.mail.backends.dummy import EmailBackend as DummyEmailBackend
from django.core.mail.backends.locmem import EmailBackend as LocmemEmailBackend
from django.db.models import Case, F, Q, Value, When
from django.utils.html import format_html
from django.utils.module_loading import import_string

from .models import EnquiryBudget
from .turnstile import verify_turnstile

logger = logging.getLogger(__name__)

CONTACT_EMAIL = 'thomasalbanmusic@gmail.com'
ERROR_MESSAGE = format_html(
    'We are sorry, there was an error and your enquiry could not be sent. '
    'Please instead contact <a href="mailto:{}">{}</a> directly.',
    CONTACT_EMAIL, CONTACT_EMAIL,
)
SESSION_KEY = 'enquiry_last_sent_at'
RATE_LIMIT_SECONDS = 60
SHARED_LIMIT_MESSAGE = format_html(
    'We are sorry, enquiries are temporarily busy and your message has not been sent. '
    'Please try again later or instead contact <a href="mailto:{}">{}</a> directly.',
    CONTACT_EMAIL, CONTACT_EMAIL,
)
SHORT_WINDOW_SECONDS = 10 * 60
SHORT_WINDOW_LIMIT = 5
DAILY_WINDOW_SECONDS = 24 * 60 * 60
DAILY_WINDOW_LIMIT = 30


def reserve_enquiry_attempt(now):
    """Atomically reserve both budgets, committing before any SMTP network I/O.

    The migration seeds the singleton row. A missing row fails closed. One UPDATE
    with conditional increments works across threads/processes, including SQLite;
    do not replace it with read-then-save or SQLite select_for_update(). Failed
    sends consume capacity too, protecting against repeated SMTP failures.
    """
    now = float(now)
    short_expired = Q(short_started_at__lte=now - SHORT_WINDOW_SECONDS)
    # Match Resend's daily reset at midnight UTC, not local time or a rolling day.
    day_start = now - now % DAILY_WINDOW_SECONDS
    daily_expired = Q(daily_started_at__lt=day_start)
    return EnquiryBudget.objects.filter(pk=1).filter(
        short_expired | Q(short_count__lt=SHORT_WINDOW_LIMIT),
        daily_expired | Q(daily_count__lt=DAILY_WINDOW_LIMIT),
    ).update(
        short_started_at=Case(When(short_expired, then=Value(now)), default=F('short_started_at')),
        short_count=Case(When(short_expired, then=Value(1)), default=F('short_count') + 1),
        daily_started_at=Case(When(daily_expired, then=Value(now)), default=F('daily_started_at')),
        daily_count=Case(When(daily_expired, then=Value(1)), default=F('daily_count') + 1),
    ) == 1


def deliver_enquiry(request, form, composition=None):
    """Return True only for one accepted message; otherwise add a form error.

    Requires SessionMiddleware. The optional composition must be resolved by the
    caller, not taken from submitted form data. Only successful sends start the
    session cooldown. All send attempts also reserve a persistent shared budget.
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

        if not verify_turnstile(request):
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

        if not reserve_enquiry_attempt(now):
            form.add_error(None, SHARED_LIMIT_MESSAGE)
            return False

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
