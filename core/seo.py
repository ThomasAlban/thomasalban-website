"""Shared, safely serialized public-page metadata."""

import json
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.urls import reverse


def absolute_url(path):
    return f'{settings.SITE_URL.rstrip("/")}{path}'


def page_context(title, description, path, active_page='', noindex=False, schema=None, image=None):
    context = {
        'page_title': title,
        'meta_description': description,
        'canonical_url': absolute_url(path),
        'active_page': active_page,
        'noindex': noindex,
    }
    if image and image.image:
        url = urljoin(settings.SITE_URL.rstrip('/') + '/', image.image.url)
        if urlsplit(url).scheme in {'http', 'https'}:
            context.update(social_image_url=url, social_image_alt=image.alt_text)
    if schema:
        context['json_ld'] = json.dumps(schema).replace('<', '\\u003c')
    return context


def homepage_schema():
    person = person_schema()
    person.pop('@context')
    home_url = absolute_url(reverse('core:home'))
    return {
        '@context': 'https://schema.org',
        '@graph': [
            {
                '@type': 'WebSite',
                '@id': home_url + '#website',
                'name': 'Thomas Alban',
                'url': home_url,
            },
            person,
        ],
    }


def person_schema():
    schema = {
        '@context': 'https://schema.org',
        '@type': 'Person',
        '@id': absolute_url(reverse('core:home')) + '#composer',
        'name': 'Thomas Alban',
        'jobTitle': 'Composer',
        'url': absolute_url(reverse('core:home')),
    }
    if settings.PERSON_SAME_AS:
        schema['sameAs'] = list(dict.fromkeys(settings.PERSON_SAME_AS))
    return schema
