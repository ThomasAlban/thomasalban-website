"""Inline small, trusted heading masks to avoid an extra render-time request."""

from base64 import b64encode
from functools import lru_cache

from django import template
from django.conf import settings


register = template.Library()
HEADING_NAMES = frozenset({'thomas-alban', 'compositions', 'about', 'contact'})


@register.simple_tag
@lru_cache(maxsize=4)
def heading_mask(name):
    # Only repository assets, never uploaded files or arbitrary template paths.
    if name not in HEADING_NAMES:
        raise ValueError(f'Unknown heading mask: {name}')
    asset = settings.BASE_DIR / 'static/images/headings' / f'{name}.png'
    encoded = b64encode(asset.read_bytes()).decode('ascii')
    return f'data:image/png;base64,{encoded}'
