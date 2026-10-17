"""Fail-closed Turnstile verification shared by both enquiry forms."""

import json
import logging
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)

VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
MAX_RESPONSE_BYTES = 16 * 1024


def verify_turnstile(request):
    """Verify an enquiry token; only development may bypass verification."""
    if not settings.TURNSTILE_ENABLED:
        return bool(settings.DEBUG)

    if not settings.TURNSTILE_SITE_KEY or not settings.TURNSTILE_SECRET_KEY:
        return False
    token = request.POST.get('cf-turnstile-response', '')
    if not token or len(token) > 2048:
        return False

    try:
        hostnames = settings.TURNSTILE_HOSTNAMES or (urlsplit(settings.SITE_URL).hostname,)
        if not all(hostnames):
            return False
        verification = Request(
            VERIFY_URL,
            data=urlencode({
                'secret': settings.TURNSTILE_SECRET_KEY,
                'response': token,
            }).encode('utf-8'),
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            method='POST',
        )
        with urlopen(verification, timeout=5) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            return False
        result = json.loads(body)
        return (
            isinstance(result, dict)
            and result.get('success') is True
            and result.get('hostname') in hostnames
            and result.get('action') == 'enquiry'
        )
    except Exception:
        # Network errors may contain credentials or tokens. Never log details.
        logger.warning('Turnstile verification failed.')
        return False
