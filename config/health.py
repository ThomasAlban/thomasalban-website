"""Small, read-only readiness probe. No external mail or provider dependencies."""

import os

from django.conf import settings
from django.db import DatabaseError, connection
from django.http import HttpResponse
from django.views.decorators.http import require_safe


@require_safe
def readiness(request):
    try:
        # Check a real migrated table, not merely that SQLite can open a file.
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1 FROM django_migrations LIMIT 1')
            migrated = cursor.fetchone() is not None
        ready = migrated and settings.MEDIA_ROOT.is_dir() and os.access(
            settings.MEDIA_ROOT, os.R_OK | os.W_OK | os.X_OK,
        )
    except (DatabaseError, OSError):
        ready = False
    response = HttpResponse('ok' if ready else 'unavailable', status=200 if ready else 503,
                            content_type='text/plain')
    response['Cache-Control'] = 'no-store'
    response['X-Robots-Tag'] = 'noindex'
    return response
