from django.apps import apps
from django.test import SimpleTestCase
from django.urls import reverse


class ScaffoldTests(SimpleTestCase):
    def test_project_apps_are_registered(self):
        self.assertTrue(apps.is_installed('core'))
        self.assertTrue(apps.is_installed('compositions'))

    def test_admin_route_is_available(self):
        self.assertEqual(reverse('admin:index'), '/admin/')

