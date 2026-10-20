from types import SimpleNamespace
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from compositions.models import Composition


class CanonicalSitemap(Sitemap):
    def get_urls(self, page=1, site=None, protocol=None):
        origin = urlsplit(settings.SITE_URL)
        return super().get_urls(
            page=page, site=SimpleNamespace(domain=origin.netloc), protocol=origin.scheme,
        )


class PublicPageSitemap(CanonicalSitemap):

    def items(self):
        return ['core:home', 'compositions:list', 'core:about', 'core:contact']

    def location(self, item):
        return reverse(item)


class CompositionSitemap(CanonicalSitemap):

    def lastmod(self, item):
        return item.updated_at

    def items(self):
        return Composition.objects.published()
