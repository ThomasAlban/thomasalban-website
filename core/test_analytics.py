"""Analytics is public-site only and never enabled by template debug flags."""

from django.test import TestCase, override_settings


@override_settings(
    ALLOWED_HOSTS=['thomasalban.com', 'www.thomasalban.com', 'thomasalban.onrender.com', 'localhost'],
    SECURE_SSL_REDIRECT=False,
)
class AnalyticsTests(TestCase):
    script = 'https://cloud.umami.is/script.js'

    @override_settings(DEBUG=False)
    def test_production_public_pages_include_tracker_once(self):
        for host in ('thomasalban.com', 'www.thomasalban.com'):
            for url in ('/', '/about/', '/contact/', '/compositions/'):
                with self.subTest(host=host, url=url):
                    response = self.client.get(url, HTTP_HOST=host, secure=True)
                    self.assertContains(response, self.script, count=1)
                    self.assertContains(response, 'data-website-id="6d94f97d-a9d8-4352-8a59-155757c5cb0b"')
                    self.assertContains(response, 'data-domains="thomasalban.com,www.thomasalban.com"')

    @override_settings(DEBUG=True)
    def test_debug_never_loads_tracker_even_on_public_hostname(self):
        response = self.client.get('/', HTTP_HOST='thomasalban.com')
        self.assertNotContains(response, self.script)

    @override_settings(DEBUG=False)
    def test_test_hosts_never_load_tracker(self):
        for host in ('thomasalban.onrender.com', 'localhost'):
            response = self.client.get('/', HTTP_HOST=host, secure=True)
            self.assertNotContains(response, self.script)

    @override_settings(DEBUG=False)
    def test_invalid_host_returns_400_without_analytics(self):
        for url in ('/', '/healthz/'):
            with self.subTest(url=url):
                response = self.client.get(url, HTTP_HOST='evil.example', secure=True)
                self.assertEqual(response.status_code, 400)
                self.assertNotContains(response, self.script, status_code=400)

    @override_settings(DEBUG=False)
    def test_admin_login_never_loads_tracker(self):
        response = self.client.get('/admin/login/', HTTP_HOST='thomasalban.com', secure=True)
        self.assertNotContains(response, self.script)
