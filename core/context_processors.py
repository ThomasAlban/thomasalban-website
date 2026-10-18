"""Public template flags, evaluated from runtime settings rather than template DEBUG."""

from django.conf import settings


def analytics(request):
    return {
        'umami_enabled': not settings.DEBUG and request.get_host().split(':')[0].lower()
        in {'thomasalban.com', 'www.thomasalban.com'},
    }
