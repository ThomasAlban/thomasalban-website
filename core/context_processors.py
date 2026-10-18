"""Public template flags, evaluated from runtime settings rather than template DEBUG."""

from django.conf import settings
from django.core.exceptions import DisallowedHost


def analytics(request):
    # Error templates also invoke context processors. Never re-raise the invalid
    # host exception while Django is rendering its intended HTTP 400 response.
    if settings.DEBUG:
        return {'umami_enabled': False}
    try:
        hostname = request.get_host().split(':')[0].lower()
    except DisallowedHost:
        return {'umami_enabled': False}
    return {
        'umami_enabled': hostname in {'thomasalban.com', 'www.thomasalban.com'},
    }
