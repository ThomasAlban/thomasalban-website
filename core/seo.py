"""Shared, safely serialized public-page metadata."""

import json

from django.conf import settings
from django.urls import reverse


def absolute_url(path):
    return f'{settings.SITE_URL.rstrip("/")}{path}'


def page_context(title, description, path, active_page='', noindex=False, schema=None):
    context = {
        'page_title': title,
        'meta_description': description,
        'canonical_url': absolute_url(path),
        'active_page': active_page,
        'noindex': noindex,
    }
    if schema:
        context['json_ld'] = json.dumps(schema).replace('<', '\\u003c')
    return context


def person_schema():
    return {
        '@context': 'https://schema.org',
        '@type': 'Person',
        '@id': absolute_url(reverse('core:home')) + '#composer',
        'name': 'Thomas Alban',
        'jobTitle': 'Composer',
        'url': absolute_url(reverse('core:home')),
    }
