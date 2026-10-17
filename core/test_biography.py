from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Biography


@override_settings(ALLOWED_HOSTS=['testserver'], SECURE_SSL_REDIRECT=False)
class BiographyTests(TestCase):
    def test_about_without_biography_keeps_placeholder(self):
        response = self.client.get(reverse('core:about'))
        self.assertContains(response, 'Biography placeholder')

    def test_about_renders_paragraphs_and_escapes_html(self):
        Biography.objects.create(body='First paragraph.\n\nSecond <script>alert(1)</script>.')
        response = self.client.get(reverse('core:about'))
        self.assertContains(response, '<p>First paragraph.</p>', html=True)
        self.assertContains(response, '<p>Second &lt;script&gt;alert(1)&lt;/script&gt;.</p>', html=True)
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertNotContains(response, 'Biography placeholder')
        self.assertContains(response, 'Explore Thomas Alban’s compositions')

    def test_about_renders_markdown_formatting_and_links(self):
        body = (
            'Music for *choirs* and **instruments**.\n\n'
            '[Compositions](/compositions/) and [Listen](https://example.com).\n\n'
            '- Choral\n- Instrumental\n\n1. First\n2. Second'
        )
        biography = Biography.objects.create(body=body)
        response = self.client.get(reverse('core:about'))
        self.assertContains(response, '<em>choirs</em>', html=True)
        self.assertContains(response, '<strong>instruments</strong>', html=True)
        self.assertContains(
            response, '<a href="/compositions/" rel="noopener noreferrer">Compositions</a>',
            html=True,
        )
        self.assertContains(
            response, '<a href="https://example.com" rel="noopener noreferrer">Listen</a>',
            html=True,
        )
        self.assertContains(response, '<ul><li>Choral</li><li>Instrumental</li></ul>', html=True)
        self.assertContains(response, '<ol><li>First</li><li>Second</li></ol>', html=True)
        biography.refresh_from_db()
        self.assertEqual(biography.body, body)

    def test_markdown_blocks_unsafe_links_and_raw_html(self):
        Biography.objects.create(body=(
            '[Bad](javascript:alert%281%29)\n\n'
            '[Encoded](jav&#x61;script:alert%281%29)\n\n'
            '[Data](data:text/html,unsafe)\n\n'
            '<a href="javascript:alert(1)" onclick="alert(1)">Raw</a>\n\n'
            '<img src=x onerror=alert(1)>\n\n'
            '![Image](https://example.com/image.png)'
        ))
        response = self.client.get(reverse('core:about'))
        self.assertNotContains(response, '<a href="javascript:')
        self.assertNotContains(response, '<a href="data:')
        self.assertNotContains(response, '<img')
        self.assertNotContains(response, '<a href="javascript:alert(1)"')
        self.assertContains(response, '&lt;img src=x onerror=alert(1)&gt;')
        self.assertContains(response, '&lt;a href=')

    def test_empty_biography_keeps_placeholder(self):
        Biography.objects.create(body='')
        response = self.client.get(reverse('core:about'))
        self.assertContains(response, 'Biography placeholder')

    def test_database_rejects_second_biography(self):
        Biography.objects.create(body='Original biography.')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Biography.objects.create(pk=2, body='Another biography.')
        self.assertEqual(Biography.objects.count(), 1)

    def test_admin_can_add_and_update_but_not_add_second_biography(self):
        user = get_user_model().objects.create_superuser(
            username='editor', email='editor@example.com', password='test-password',
        )
        self.client.force_login(user)
        add_url = reverse('admin:core_biography_add')
        self.assertEqual(self.client.get(add_url).status_code, 200)
        response = self.client.post(add_url, {'body': 'Initial biography.', '_save': 'Save'})
        self.assertEqual(response.status_code, 302)
        biography = Biography.objects.get()
        self.assertEqual(str(biography), 'Biography')
        self.assertEqual(biography.body, 'Initial biography.')
        self.assertEqual(self.client.get(add_url).status_code, 403)
        change_url = reverse('admin:core_biography_change', args=[biography.pk])
        response = self.client.post(change_url, {'body': 'Updated biography.', '_save': 'Save'})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(reverse('core:about')), 'Updated biography.')

    def test_admin_requires_biography_text(self):
        user = get_user_model().objects.create_superuser(
            username='editor', email='editor@example.com', password='test-password',
        )
        self.client.force_login(user)
        response = self.client.post(reverse('admin:core_biography_add'), {'body': '   '})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Biography.objects.exists())
        self.assertIn('body', response.context['adminform'].form.errors)
