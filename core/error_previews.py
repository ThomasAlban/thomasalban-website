"""Development-only previews of the production error templates."""

from django.conf import settings
from django.http import Http404
from django.shortcuts import render


def error_preview(request, status_code):
    if not settings.DEBUG:
        raise Http404
    return render(request, f'{status_code}.html', status=status_code)
