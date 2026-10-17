from django.forms import modelform_factory
from django.test import TestCase, override_settings

from .models import Composition


@override_settings(ALLOWED_HOSTS=['testserver'], SECURE_SSL_REDIRECT=False)
class CompositionDescriptionTests(TestCase):
    def setUp(self):
        self.composition = Composition.objects.create(
            title='Test composition', slug='test-composition', is_published=True,
        )

    def render_description(self, description):
        self.composition.description = description
        self.composition.save()
        return self.client.get(self.composition.get_absolute_url())

    def test_markdown_formatting_links_and_lists(self):
        description = (
            'Music for *choirs* and **instruments**.\n\n'
            '[About](/about/) and [Listen](https://example.com).\n\n'
            '- Choral\n- Instrumental\n\n1. First\n2. Second'
        )
        response = self.render_description(description)
        self.assertContains(response, '<em>choirs</em>', html=True)
        self.assertContains(response, '<strong>instruments</strong>', html=True)
        self.assertContains(
            response, '<a href="/about/" rel="noopener noreferrer">About</a>', html=True,
        )
        self.assertContains(
            response, '<a href="https://example.com" rel="noopener noreferrer">Listen</a>',
            html=True,
        )
        self.assertContains(response, '<ul><li>Choral</li><li>Instrumental</li></ul>', html=True)
        self.assertContains(response, '<ol><li>First</li><li>Second</li></ol>', html=True)
        self.composition.refresh_from_db()
        self.assertEqual(self.composition.description, description)

    def test_plain_text_paragraphs_still_render(self):
        response = self.render_description('First paragraph.\n\nSecond paragraph.')
        self.assertContains(response, '<p>First paragraph.</p>', html=True)
        self.assertContains(response, '<p>Second paragraph.</p>', html=True)

    def test_unsafe_links_html_and_images_are_not_rendered(self):
        response = self.render_description(
            '[Bad](javascript:alert%281%29)\n\n'
            '[Encoded](jav&#x61;script:alert%281%29)\n\n'
            '[Data](data:text/html,unsafe)\n\n'
            '<script>alert(1)</script>\n\n'
            '<img src=x onerror=alert(1)>\n\n'
            '![Image](https://example.com/image.png)'
        )
        self.assertNotContains(response, '<a href="javascript:')
        self.assertNotContains(response, '<a href="data:')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertNotContains(response, '<img')
        self.assertContains(response, '&lt;img src=x onerror=alert(1)&gt;')

    def test_blank_description_is_omitted(self):
        response = self.render_description('')
        self.assertNotContains(response, 'class="prose work-description"')

    def test_structured_description_is_plain_text(self):
        response = self.render_description(
            'For *choir* & **organ**.\n\n[Listen](https://example.com).'
        )
        self.assertContains(response, '"description": "For choir & organ. Listen."')

    def test_admin_form_has_markdown_guidance_and_allows_blank_description(self):
        form = modelform_factory(Composition, fields=['description'])()
        self.assertIn('Markdown supported', form.fields['description'].help_text)
        self.assertFalse(form.fields['description'].required)
