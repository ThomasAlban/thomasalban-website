"""Project routes, including development-only upload serving."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from config.health import readiness
from core.sitemaps import CompositionSitemap, PublicPageSitemap

urlpatterns = [
    path('healthz/', readiness, name='readiness'),
    path('admin/', admin.site.urls),
    path('sitemap.xml', sitemap, {'sitemaps': {
        'pages': PublicPageSitemap, 'compositions': CompositionSitemap,
    }}, name='sitemap'),
    path('', include('core.urls')),
    path('compositions/', include('compositions.urls')),
]

if settings.DEBUG:
    from core.error_previews import error_preview

    urlpatterns += [
        path(f'__preview__/errors/{status_code}/', error_preview,
             {'status_code': status_code}, name=f'error-preview-{status_code}')
        for status_code in (400, 403, 404, 500)
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
