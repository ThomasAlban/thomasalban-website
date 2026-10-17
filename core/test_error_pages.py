"""Branded error responses through Django's production exception handling."""

from importlib import reload

from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import Http404
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.urls import Resolver404, clear_url_caches, include, path, resolve

from core.error_previews import error_preview


PRIVATE_DETAIL = 'private-error-detail-not-for-visitors'


def bad_request(request):
    raise SuspiciousOperation(PRIVATE_DETAIL)


def forbidden(request):
    raise PermissionDenied(PRIVATE_DETAIL)


def missing(request):
    raise Http404(PRIVATE_DETAIL)


def broken(request):
    raise RuntimeError(PRIVATE_DETAIL)


urlpatterns = [
    path('errors/400/', bad_request),
    path('errors/403/', forbidden),
    path('errors/404/', missing),
    path('errors/500/', broken),
    path('', include('config.urls')),
]


@override_settings(
    DEBUG=False,
    ALLOWED_HOSTS=['testserver'],
    SECURE_SSL_REDIRECT=False,
    ROOT_URLCONF=__name__,
)
class ErrorPageTests(SimpleTestCase):
    def test_error_responses_use_shared_layout_without_database_access(self):
        client = Client(raise_request_exception=False)
        for status, title, heading in [
            (400, 'Bad request', 'We couldn’t open that page'),
            (403, 'Access denied', 'Access denied'),
            (404, 'Page not found', 'Page not found'),
            (500, 'Something went wrong', 'Something went wrong'),
        ]:
            with self.subTest(status=status):
                response = client.get(f'/errors/{status}/')
                self.assertEqual(response.status_code, status)
                self.assertTemplateUsed(response, f'{status}.html')
                for text in [
                    f'<title>{title} - Thomas Alban</title>',
                    f'<h1 id="error-heading">{heading}</h1>',
                    f'Error {status}',
                    'name="robots" content="noindex, follow"',
                    'aria-label="Main navigation"',
                    'href="/">Back to home</a>',
                    'href="/compositions/">Explore compositions</a>',
                    'css/site.css',
                ]:
                    self.assertContains(response, text, status_code=status)
                for text in [PRIVATE_DETAIL, 'rel="canonical"', 'application/ld+json']:
                    self.assertNotContains(response, text, status_code=status)

    def test_unknown_url_uses_custom_404(self):
        response = self.client.get('/this-page-does-not-exist/')
        self.assertContains(response, 'Page not found', status_code=404)
        self.assertTemplateUsed(response, '404.html')

    def test_server_error_template_renders_without_request_context(self):
        content = render_to_string('500.html')
        self.assertIn('<title>Something went wrong - Thomas Alban</title>', content)
        self.assertIn('href="/">Back to home</a>', content)

    def test_csrf_failure_explains_how_to_retry_without_exposing_details(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post('/contact/', {'message': PRIVATE_DETAIL})
        self.assertTemplateUsed(response, '403.html')
        self.assertContains(response, 'Your message has not been sent.', status_code=403)
        self.assertContains(response, 'reload the page and try again', status_code=403)
        self.assertNotContains(response, PRIVATE_DETAIL, status_code=403)
        self.assertNotContains(response, 'CSRF cookie not set', status_code=403)


@override_settings(
    ALLOWED_HOSTS=['testserver'],
    SECURE_SSL_REDIRECT=False,
    ROOT_URLCONF='config.urls',
)
class ErrorPreviewTests(SimpleTestCase):
    def test_preview_routes_are_only_registered_in_debug_mode(self):
        from config import urls

        try:
            for debug in (True, False):
                with self.subTest(debug=debug), override_settings(DEBUG=debug):
                    reload(urls)
                    clear_url_caches()
                    for status in (400, 403, 404, 500):
                        url = f'/__preview__/errors/{status}/'
                        if debug:
                            response = self.client.get(url)
                            self.assertEqual(response.status_code, status)
                            self.assertTemplateUsed(response, f'{status}.html')
                            self.assertContains(response, f'Error {status}', status_code=status)
                        else:
                            with self.assertRaises(Resolver404):
                                resolve(url)
        finally:
            reload(urls)
            clear_url_caches()

    @override_settings(DEBUG=False)
    def test_preview_view_also_refuses_access_outside_debug_mode(self):
        with self.assertRaises(Http404):
            error_preview(RequestFactory().get('/__preview__/errors/500/'), 500)
