from django.contrib import admin
from django.test import RequestFactory, TestCase, override_settings

from .models import Composition, CompositionImage, ListeningLink


@override_settings(ALLOWED_HOSTS=['testserver'], SECURE_SSL_REDIRECT=False)
class CompositionTextTests(TestCase):
    def setUp(self):
        self.composition = Composition.objects.create(
            title='Vocal composition', slug='vocal-composition', is_published=True,
        )

    def render_text(self, text, has_translation=False):
        self.composition.text = text
        self.composition.has_translation = has_translation
        self.composition.save()
        return self.client.get(self.composition.get_absolute_url())

    def test_markdown_unicode_and_source_link_preserve_stored_text(self):
        text = (
            'Щедрик, щедрик, щедрівочка.  \nПрилетіла ластівочка.\n\n'
            '*A little swallow flew in.*\n\n'
            '**Traditional text** - [Source](https://example.com/text)'
        )
        response = self.render_text(text, has_translation=True)
        self.assertContains(response, 'Щедрик, щедрик, щедрівочка.<br>')
        self.assertContains(response, 'Прилетіла ластівочка.')
        self.assertContains(response, '<em>A little swallow flew in.</em>', html=True)
        self.assertContains(response, '<strong>Traditional text</strong>', html=True)
        self.assertContains(
            response,
            '<a href="https://example.com/text" rel="noopener noreferrer">Source</a>',
            html=True,
        )
        self.composition.refresh_from_db()
        self.assertEqual(self.composition.text, text)
        self.assertTrue(self.composition.has_translation)

    def test_single_line_breaks_and_blank_lines_are_preserved(self):
        for line_ending in ('\n', '\r\n'):
            for trailing_spaces in ('', '  '):
                with self.subTest(line_ending=line_ending, trailing_spaces=trailing_spaces):
                    response = self.render_text(
                        f'First line{trailing_spaces}{line_ending}Second line'
                        f'{line_ending}{line_ending}*Translated line{line_ending}Another line*'
                    )
                    self.assertContains(response, '<p>First line<br>Second line</p>', html=True)
                    self.assertContains(
                        response, '<p><em>Translated line<br>Another line</em></p>', html=True,
                    )

    def test_description_keeps_normal_markdown_line_break_behavior(self):
        self.composition.description = 'First description line\nSecond description line'
        response = self.render_text('First verse line\nSecond verse line')
        self.assertContains(response, '<p>First description line\nSecond description line</p>', html=True)
        self.assertContains(response, '<p>First verse line<br>Second verse line</p>', html=True)

    def test_heading_without_translation(self):
        response = self.render_text('Nunc dimittis.')
        self.assertContains(response, '<h2 id="text-title">Text</h2>', html=True)
        self.assertNotContains(response, 'Text and translation')

    def test_translation_checkbox_only_changes_heading_not_formatting(self):
        response = self.render_text('Now let your servant depart.', has_translation=True)
        self.assertContains(
            response, '<h2 id="text-title">Text and translation</h2>', html=True,
        )
        self.assertContains(response, '<p>Now let your servant depart.</p>', html=True)
        self.assertNotContains(response, '<em>Now let your servant depart.</em>')

    def test_blank_text_hides_section_even_with_translation_checked(self):
        for has_translation in (False, True):
            with self.subTest(has_translation=has_translation):
                response = self.render_text('', has_translation=has_translation)
                self.assertNotContains(response, 'id="text-title"')

    def test_text_is_below_images_and_above_listen(self):
        self.composition.description = 'Description before sung text.'
        image = CompositionImage.objects.create(
            composition=self.composition, image='composition_images/choir.jpg',
            alt_text='Choir at the premiere',
        )
        ListeningLink.objects.create(
            composition=self.composition, label='Recording', url='https://example.com',
        )
        response = self.render_text('Sung text goes here.')
        content = response.content.decode().split('<main', 1)[1]
        self.assertLess(content.index('Description before sung text.'), content.index(image.image.url))
        self.assertLess(content.index(image.image.url), content.index('id="text-title"'))
        self.assertLess(content.index('Sung text goes here.'), content.index('id="recording-title"'))

    def test_unsafe_html_links_and_images_are_not_rendered(self):
        response = self.render_text(
            '<script>alert(1)</script>\n\n'
            '<img src=x onerror=alert(1)>\n\n'
            '[Bad](javascript:alert%281%29)\n\n'
            '[Encoded](jav&#x61;script:alert%281%29)\n\n'
            '[Data](data:text/html,unsafe)\n\n'
            '![Image](https://example.com/image.png)'
        )
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertNotContains(response, '<img')
        self.assertNotContains(response, '<a href="javascript:')
        self.assertNotContains(response, '<a href="data:')
        self.assertContains(response, '&lt;img src=x onerror=alert(1)&gt;')

    def test_existing_compositions_have_empty_text_and_no_translation(self):
        self.composition.refresh_from_db()
        self.assertEqual(self.composition.text, '')
        self.assertFalse(self.composition.has_translation)

    def test_admin_exposes_optional_fields_and_markdown_guidance(self):
        request = RequestFactory().get('/admin/compositions/composition/add/')
        form = admin.site._registry[Composition].get_form(request)()
        self.assertFalse(form.fields['text'].required)
        self.assertIn('Markdown supported', form.fields['text'].help_text)
        self.assertIn('Single line breaks are preserved', form.fields['text'].help_text)
        self.assertIn('any language', form.fields['text'].help_text)
        self.assertFalse(form.fields['has_translation'].required)
        self.assertEqual(form.fields['has_translation'].label, 'Has translation')
