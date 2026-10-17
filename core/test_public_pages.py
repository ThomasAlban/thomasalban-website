"""Request-level coverage for public pages, discovery and enquiry delivery."""

from datetime import date
from html.parser import HTMLParser
import json
from unittest.mock import patch
from urllib.parse import urlsplit
from xml.etree import ElementTree

from django.core import mail
from django.test import Client, TestCase, override_settings
from django.utils.html import escape

from compositions.models import Composition, ListeningLink, ScorePreview
from core.enquiries import ERROR_MESSAGE, SESSION_KEY, SHARED_LIMIT_MESSAGE, SHORT_WINDOW_LIMIT
from core.models import EnquiryBudget
from core.test_mail_backend import ACCEPTED_MAILERS
from core.turnstile import verify_turnstile


class PageParser(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.tags = []
        self.schemas = []
        self.in_schema = False
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.tags.append((tag, attributes))
        if tag == 'script' and attributes.get('type') == 'application/ld+json':
            self.in_schema = True
            self.schemas.append('')

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_schema = False

    def handle_data(self, data):
        if self.in_schema:
            self.schemas[-1] += data


@override_settings(
    SITE_URL='https://composer.example',
    ALLOWED_HOSTS=['testserver', 'composer.example'],
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
    MAILERS=ACCEPTED_MAILERS,
    DEFAULT_FROM_EMAIL='composer@example.com',
    ENQUIRY_EMAIL='enquiries@example.com',
)
class PublicPageTests(TestCase):
    def make_work(self, slug='test-work', **kwargs):
        data = {'title': slug.replace('-', ' ').title(), 'is_published': True}
        data.update(kwargs)
        return Composition.objects.create(slug=slug, **data)

    def parse(self, response):
        return PageParser(response.content.decode())

    def assert_works(self, response, expected, key='works'):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context[key]), expected)
        content = response.content.decode()
        # Verify template rendering order too, not just the view's queryset.
        positions = [content.index(f'<h3><a href="{work.get_absolute_url()}"')
                     for work in expected]
        self.assertEqual(positions, sorted(positions))

    def test_required_pages_return_200_with_empty_database(self):
        for path, template in [
            ('/', 'core/home.html'),
            ('/compositions/', 'compositions/list.html'),
            ('/about/', 'core/about.html'),
            ('/contact/', 'core/contact.html'),
        ]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template)
                if path in ('/', '/compositions/'):
                    self.assertContains(response, 'Compositions will be added here')
        self.assertIsNone(self.client.get('/').context['featured'])
        for path in ('/robots.txt', '/sitemap.xml'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_shared_theme_toggle_and_early_script(self):
        work = self.make_work()
        for path in ('/', '/compositions/', '/about/', '/contact/',
                     work.get_absolute_url()):
            with self.subTest(path=path):
                response = self.client.get(path)
                tags = self.parse(response).tags
                toggles = [attrs for tag, attrs in tags
                           if tag == 'button' and attrs.get('class') == 'theme-toggle']
                self.assertEqual(len(toggles), 1)
                self.assertEqual(toggles[0]['type'], 'button')
                self.assertEqual(toggles[0]['aria-pressed'], 'false')
                self.assertIn('hidden', toggles[0])
                self.assertEqual(toggles[0]['aria-label'], 'Light mode')
                icons = [attrs for tag, attrs in tags if tag == 'svg'
                         and attrs.get('class', '').startswith('theme-icon-')]
                self.assertEqual([icon['class'] for icon in icons],
                                 ['theme-icon-sun', 'theme-icon-moon'])
                toggle_position = next(i for i, (tag, attrs) in enumerate(tags)
                                       if tag == 'button' and
                                       attrs.get('class') == 'theme-toggle')
                home_position = next(i for i, (tag, attrs) in enumerate(tags)
                                     if tag == 'a' and attrs.get('href') == '/'
                                     and attrs.get('class') != 'site-name')
                self.assertLess(toggle_position, home_position)
                script = next(i for i, (tag, attrs) in enumerate(tags)
                              if tag == 'script' and
                              attrs.get('src') == '/static/js/theme.js')
                stylesheet = next(i for i, (tag, attrs) in enumerate(tags)
                                  if tag == 'link' and
                                  attrs.get('rel') == 'stylesheet')
                self.assertLess(script, stylesheet)

    def test_shared_header_has_full_width_decorative_divider(self):
        work = self.make_work()
        for path in ('/', '/compositions/', '/about/', '/contact/',
                     work.get_absolute_url()):
            with self.subTest(path=path):
                tags = self.parse(self.client.get(path)).tags
                dividers = [i for i, (tag, attrs) in enumerate(tags)
                            if tag == 'div' and
                            attrs.get('class') == 'header-divider']
                self.assertIn(('footer', {'class': 'site-band footer-band'}), tags)
                self.assertEqual(len(dividers), 1)
                position = dividers[0]
                self.assertEqual(tags[position][1]['aria-hidden'], 'true')
                self.assertEqual(tags[position + 1][0], 'svg')
                self.assertEqual(tags[position + 1][1]['focusable'], 'false')
                navigation_position = next(i for i, (tag, _) in enumerate(tags)
                                           if tag == 'nav')
                main_position = next(i for i, (tag, _) in enumerate(tags)
                                     if tag == 'main')
                self.assertLess(navigation_position, position)
                self.assertLess(position, main_position)

    def test_shared_navigation_has_progressively_enhanced_menu(self):
        work = self.make_work()
        for path in ('/', '/compositions/', '/about/', '/contact/',
                     work.get_absolute_url()):
            with self.subTest(path=path):
                tags = self.parse(self.client.get(path)).tags
                menus = [attrs for tag, attrs in tags
                         if tag == 'button' and attrs.get('class') == 'menu-toggle']
                self.assertEqual(len(menus), 1)
                self.assertEqual(menus[0]['type'], 'button')
                self.assertEqual(menus[0]['aria-label'], 'Menu')
                self.assertEqual(menus[0]['aria-expanded'], 'false')
                self.assertIn('hidden', menus[0])
                navigation = next(attrs for tag, attrs in tags if tag == 'nav')
                self.assertEqual(navigation['id'], menus[0]['aria-controls'])
                self.assertNotIn('hidden', navigation)
                self.assertIn(('script', {'src': '/static/js/navigation.js',
                                          'defer': None}), tags)

    def test_drawn_page_headings_keep_accessible_text(self):
        for path, name, label in [
            ('/', 'name', 'Thomas Alban'),
            ('/compositions/', 'compositions', 'Compositions'),
            ('/about/', 'about', 'About'),
            ('/contact/', 'contact', 'Contact'),
        ]:
            with self.subTest(path=path):
                response = self.client.get(path)
                headings = [attrs for tag, attrs in self.parse(response).tags
                            if tag == 'h1']
                self.assertEqual(len(headings), 1)
                self.assertEqual(headings[0]['class'],
                                 f'drawn-heading drawn-heading-{name}')
                self.assertNotIn('aria-hidden', headings[0])
                self.assertContains(
                    response,
                    f'<span class="drawn-heading-text">{label}</span>',
                    html=True,
                )

    def test_drawn_headings_embed_only_the_current_mask_without_image_requests(self):
        from core.templatetags.headings import heading_mask

        for path, name in [
            ('/', 'thomas-alban'),
            ('/compositions/', 'compositions'),
            ('/about/', 'about'),
            ('/contact/', 'contact'),
        ]:
            with self.subTest(path=path):
                response = self.client.get(path)
                tags = self.parse(response).tags
                heading = next(attrs for tag, attrs in tags if tag == 'h1')
                self.assertEqual(heading['style'],
                                 f"--heading-mask: url('{heading_mask(name)}')")
                self.assertEqual(response.content.count(b'data:image/png;base64,'), 1)
                self.assertNotContains(response, '/images/headings/')
                self.assertFalse(any(tag == 'link' and attrs.get('rel') == 'preload'
                                     for tag, attrs in tags))

    def test_composition_detail_does_not_preload_a_heading_mask(self):
        response = self.client.get(self.make_work().get_absolute_url())
        self.assertNotContains(response, 'data:image/png;base64,')
        self.assertFalse(any(tag == 'link' and attrs.get('rel') == 'preload'
                             for tag, attrs in self.parse(response).tags))

    def test_score_enquiry_keeps_text_heading(self):
        from django.template.loader import render_to_string

        content = render_to_string('core/contact.html', {
            'composition': self.make_work(),
        })
        self.assertIn('<h1>Score enquiry</h1>', content)
        self.assertNotIn('drawn-heading-contact', content)
        self.assertNotIn('data:image/png;base64,', content)
        self.assertFalse(any(tag == 'link' and attrs.get('rel') == 'preload'
                             for tag, attrs in PageParser(content).tags))

    def test_privacy_page_and_links_are_removed(self):
        self.assertEqual(self.client.get('/privacy/').status_code, 404)
        work = self.make_work()
        for path in ('/', '/compositions/', '/about/', '/contact/',
                     work.get_absolute_url()):
            with self.subTest(path=path):
                self.assertNotContains(self.client.get(path), '/privacy/')

    def test_contact_has_bullet_links_to_email_and_linkedin(self):
        response = self.client.get('/contact/')
        self.assertContains(response,
                            '<li>Email: <a href="mailto:thomasalbanmusic@gmail.com">thomasalbanmusic@gmail.com</a></li>',
                            html=True)
        self.assertContains(response,
                            '<li><a href="https://www.linkedin.com/in/thomas-alban-b7b285278/" rel="external noopener">LinkedIn</a></li>',
                            html=True)

    def test_public_copy_uses_compositions_not_works(self):
        work = self.make_work('test-composition', category='Choral')
        for path in ('/', '/about/', '/contact/', '/compositions/',
                     '/compositions/?category=Choral', work.get_absolute_url()):
            response = self.client.get(path)
            parser = PageParser(response.content.decode())
            # Ignore internal CSS names, template identifiers and attributes.
            text = []
            parser.handle_data = text.append
            parser.feed(response.content.decode())
            self.assertNotRegex(' '.join(text), r'\b[Ww]orks?\b')

    def test_published_detail_and_unknown_detail(self):
        work = self.make_work()
        response = self.client.get(work.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'compositions/detail.html')
        self.assertEqual(response.context['composition'], work)
        self.assertContains(response, f'<h1>{work.title}</h1>', html=True)
        schema = json.loads(self.parse(response).schemas[0])
        self.assertEqual(schema['composer']['name'], 'Thomas Alban')
        self.assertEqual(self.client.get('/compositions/missing/').status_code, 404)

    def test_drafts_are_absent_from_home_catalogue_and_detail(self):
        draft = self.make_work('nunc-dimittis', title='Secret unpublished work',
                               is_published=False, is_featured=True,
                               category='Secret category', premiered_date=date(2030, 1, 1))
        published = self.make_work('public-work', is_featured=True)
        home = self.client.get('/')
        self.assertEqual(home.context['featured'], published)
        self.assert_works(home, [published], 'recent_works')
        catalogue = self.client.get('/compositions/')
        self.assert_works(catalogue, [published])
        self.assertNotIn('Secret category', catalogue.context['categories'])
        for response in (home, catalogue):
            self.assertNotContains(response, draft.title)
            self.assertNotContains(response, draft.get_absolute_url())
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(draft.get_absolute_url()).status_code, 404)

    def test_nunc_is_featured_with_required_title_but_no_automatic_credit(self):
        nunc = self.make_work('nunc-dimittis', title='Nunc dimittis')
        recording = ListeningLink.objects.create(
            composition=nunc, label='Recording', url='https://recordings.example/nunc',
        )
        self.make_work('other-featured', is_featured=True,
                       premiered_date=date(2026, 1, 1))
        self.assertEqual(self.client.get('/').context['featured'], nunc)
        response = self.client.get(nunc.get_absolute_url())
        self.assertContains(response,
                            '<title>Nunc dimittis - Thomas Alban | Score &amp; Recording</title>',
                            html=True)
        self.assertNotContains(response, 'Choir of Clare College')
        self.assertContains(response, recording.url)
        schema = json.loads(self.parse(response).schemas[0])
        self.assertEqual(schema['@type'], 'MusicComposition')
        self.assertEqual(schema['composer']['name'], 'Thomas Alban')

    def test_explicit_recording_credits_are_per_recording_and_escaped(self):
        # Editorially verified credit simulated in test data only.
        credit = 'Performed by the Choir of Clare College, Cambridge.'
        for slug in ('nunc-dimittis', 'another-composition'):
            work = self.make_work(slug, audio_file='audio/test.mp3',
                                  audio_credit='Uploaded recording <credit>')
            ListeningLink.objects.create(
                composition=work, label='Credited recording',
                url='https://recordings.example/verified', credit=credit,
            )
            ListeningLink.objects.create(
                composition=work, label='Another recording',
                url='https://recordings.example/other',
            )
            response = self.client.get(work.get_absolute_url())
            self.assertContains(response, credit, count=1)
            self.assertContains(response, 'Uploaded recording &lt;credit&gt;')
            work.audio_file = ''
            work.save()
            self.assertNotContains(self.client.get(work.get_absolute_url()),
                                   'Uploaded recording')

    def test_unchecked_unsafe_listening_urls_are_not_rendered_or_in_schema(self):
        work = self.make_work('nunc-dimittis')
        unsafe_urls = [
            'javascript:alert(1)', 'data:text/html,unsafe', '//example.com/audio',
            'ftp://example.com/audio', 'https://user:secret@example.com/audio',
            'https://@example.com/audio', 'https://example.com:99999/audio',
            'https://[invalid', 'https://exa\nmple.com/audio',
            'https://example.com\\@evil.example/audio',
        ]
        for url in unsafe_urls:
            with self.subTest(url=url):
                work.listening_links.all().delete()
                # Deliberately bypass full_clean(), as an unchecked import does.
                ListeningLink.objects.create(
                    composition=work, label='Unsafe recording', url=url,
                    is_primary=True, credit='Unsafe recording credit',
                )
                response = self.client.get(work.get_absolute_url())
                self.assertNotContains(response, 'id="recording-title"')
                self.assertNotContains(response, 'Unsafe recording')
                parser = self.parse(response)
                self.assertFalse(any(tag == 'iframe' for tag, _ in parser.tags))
                for schema in parser.schemas:
                    self.assertNotIn(url, json.dumps(json.loads(schema)))
                safe = ListeningLink.objects.create(
                    composition=work, label='Safe recording',
                    url='https://recordings.example/audio?x=1&y=2',
                )
                response = self.client.get(work.get_absolute_url())
                self.assertContains(response, escape(safe.url))
                self.assertNotContains(response, 'Unsafe recording')

    def test_premiere_order_fallback_ties_and_home_limit(self):
        unknown_first = self.make_work('unknown-first')
        unknown_second = self.make_work('unknown-second')
        old_year = self.make_work('old-year', year_composed=2020)
        new_year = self.make_work('new-year', year_composed=2026)
        old_premiere = self.make_work('old-premiere', premiered_date=date(2024, 1, 1))
        tie_first = self.make_work('tie-first', premiered_date=date(2025, 1, 1),
                                   year_composed=2025)
        tie_second = self.make_work('tie-second', premiered_date=date(2025, 1, 1),
                                    year_composed=2025)
        expected = [tie_second, tie_first, old_premiere, new_year, old_year,
                    unknown_second, unknown_first]
        self.assert_works(self.client.get('/compositions/'), expected)
        self.assert_works(self.client.get('/'), expected[:6], 'recent_works')
        self.assertNotContains(self.client.get('/'), unknown_first.get_absolute_url())

    def test_category_choices_and_combined_filters(self):
        choral = self.make_work('choral', category='Choral', duration_seconds=300)
        self.make_work('instrumental', category='Instrumental', duration_seconds=300)
        self.make_work('short-choral', category='Choral', duration_seconds=299)
        self.make_work('uncategorised', duration_seconds=300)
        self.make_work('draft-category', category='Draft only', is_published=False)
        response = self.client.get('/compositions/', {'category': 'Choral', 'duration': 'medium'})
        self.assert_works(response, [choral])
        self.assertEqual(response.context['categories'], ['Choral', 'Instrumental'])
        self.assertContains(response, 'Clear filters')

    def test_duration_filter_exact_bounds_and_unknown_duration(self):
        works = {seconds: self.make_work(f'duration-{seconds}', duration_seconds=seconds)
                 for seconds in (1, 299, 300, 600, 601)}
        unknown = self.make_work('unknown-duration')
        for choice, seconds in [('short', [299, 1]), ('medium', [600, 300]),
                                ('long', [601])]:
            with self.subTest(duration=choice):
                response = self.client.get('/compositions/', {'duration': choice})
                self.assert_works(response, [works[value] for value in seconds])
                self.assertNotContains(response, unknown.get_absolute_url())
        self.assert_works(self.client.get('/compositions/'),
                          [unknown] + [works[value] for value in (601, 600, 300, 299, 1)])

    def test_invalid_filter_choices_show_errors_without_partial_filtering(self):
        first = self.make_work('first', category='Choral', duration_seconds=300)
        second = self.make_work('second', category='Instrumental', duration_seconds=601)
        for data, error_field in [
            ({'category': 'Not a category', 'duration': 'medium'}, 'category'),
            ({'category': 'Choral', 'duration': 'invalid'}, 'duration'),
            ({'category': 'Draft only'}, 'category'),
        ]:
            with self.subTest(data=data):
                response = self.client.get('/compositions/', data)
                self.assert_works(response, [second, first])
                self.assertIn(error_field, response.context['filter_form'].errors)
                self.assertContains(response, 'Select a valid choice.')

    def test_valid_filters_with_no_matches_show_empty_state(self):
        self.make_work(category='Choral', duration_seconds=299)
        response = self.client.get('/compositions/', {'category': 'Choral', 'duration': 'long'})
        self.assert_works(response, [])
        self.assertContains(response, 'No compositions match these filters.')
        self.assertContains(response, 'View all compositions')

    def test_uploaded_audio_has_only_native_controls(self):
        work = self.make_work('nunc-dimittis', audio_file='audio/test.mp3')
        response = self.client.get(work.get_absolute_url())
        audio = [attrs for tag, attrs in self.parse(response).tags if tag == 'audio']
        self.assertEqual(len(audio), 1)
        self.assertEqual(audio[0]['src'], work.audio_file.url)
        self.assertIn('controls', audio[0])
        self.assertEqual(audio[0]['preload'], 'none')
        self.assertNotIn('autoplay', audio[0])
        self.assertNotContains(response, 'waveform')
        self.assertNotContains(response, 'type="range"')
        self.assertNotContains(response, '/static/js/listening.js')
        self.assertNotContains(response, 'Choir of Clare College')

    def test_ordered_links_and_only_primary_embed_loads_without_site_javascript(self):
        work = self.make_work(title='Music & "title"')
        secondary = ListeningLink.objects.create(
            composition=work, label='Secondary recording', position=2,
            url='https://youtu.be/abcdefghijk',
        )
        primary = ListeningLink.objects.create(
            composition=work, label='Primary & "recording"', position=0, is_primary=True,
            url='https://open.spotify.com/track/123abc', credit='Verified test credit',
        )
        for provider, url, embed_url, player_class in [
            ('Spotify', 'https://open.spotify.com/track/123abc',
             'https://open.spotify.com/embed/track/123abc', 'spotify-player'),
            ('YouTube', 'https://youtu.be/dQw4w9WgXcQ?autoplay=1',
             'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ', 'video-player'),
        ]:
            with self.subTest(provider=provider):
                primary.url = url
                primary.save()
                # The Django client executes no JavaScript: the iframe must be in HTML.
                response = self.client.get(work.get_absolute_url())
                content = response.content.decode()
                self.assertLess(content.index(f'href="{primary.url}"'),
                                content.index(f'href="{secondary.url}"'))
                self.assertNotContains(response, secondary.embed_url)
                page = self.parse(response)
                frames = [attrs for tag, attrs in page.tags if tag == 'iframe']
                self.assertEqual(len(frames), 1)
                self.assertEqual(frames[0], {
                    'src': embed_url,
                    'title': f'{work.title} - {primary.label}',
                    'class': player_class,
                    'loading': 'eager',
                    'referrerpolicy': 'strict-origin-when-cross-origin',
                    'allow': 'encrypted-media; fullscreen; picture-in-picture',
                    'allowfullscreen': None,
                })
                self.assertNotContains(response, 'data-recording-embed')
                self.assertNotContains(response, 'Load Primary')
                self.assertNotContains(response, '/static/js/listening.js')
                self.assertNotContains(response, 'This player connects to')
                self.assertNotContains(response, 'recording-notice')
                self.assertContains(response, 'Verified test credit', count=1)
                for link in (primary, secondary):
                    self.assertIn(('a', {'href': link.url, 'rel': 'external noopener'}), page.tags)
                self.assertNotContains(response, '<audio')

    def test_unsupported_primary_remains_external_and_labels_are_escaped(self):
        work = self.make_work()
        link = ListeningLink.objects.create(
            composition=work, label='<img src=x onerror=alert(1)>', is_primary=True,
            url='https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ',
        )
        response = self.client.get(work.get_absolute_url())
        self.assertContains(response, escape(link.label))
        self.assertContains(response, link.url)
        self.assertNotContains(response, 'data-recording-embed')
        self.assertNotContains(response, '<iframe')
        self.assertNotContains(response, link.label)

    def test_missing_metadata_recording_and_previews_are_omitted(self):
        work = self.make_work()
        response = self.client.get(work.get_absolute_url())
        for text in ('About the composition', '<dt>Category</dt>', '<dt>Instrumentation</dt>',
                     '<dt>Duration</dt>', '<dt>Composed</dt>', '<dt>Premiered</dt>',
                     'id="recording-title"', 'Choir of Clare College',
                     'id="previews-title"', 'id="score-viewer"', '/static/js/score-previews.js', 'None'):
            with self.subTest(text=text):
                self.assertNotContains(response, text)
        schema = json.loads(self.parse(response).schemas[0])
        self.assertNotIn('musicalInstrumentation', schema)
        self.assertNotIn('description', schema)
        for path in ('/', '/compositions/'):
            page = self.client.get(path)
            self.assertNotContains(page, 'card-meta')
            self.assertNotContains(page, '<dt>Duration</dt>')

    def test_present_metadata_and_ordered_preview_alt_text(self):
        work = self.make_work(category='Choral', instrumentation='SATB',
                              duration_seconds=301, year_composed=2025,
                              premiered_date=date(2026, 1, 2), description='A test description.')
        later = ScorePreview.objects.create(composition=work, position=2,
                                             image='score_previews/later.png', alt_text='Second page')
        first = ScorePreview.objects.create(composition=work, position=0,
                                             image='score_previews/first.png', alt_text='First page & notes')
        response = self.client.get(work.get_absolute_url())
        for text in ('Choral', 'SATB', 'c. 5:00', '2025', '2 January 2026', 'A test description.'):
            self.assertContains(response, text)
        content = response.content.decode()
        self.assertLess(content.index(first.image.url), content.index(later.image.url))
        self.assertContains(response, 'alt="First page &amp; notes"')
        self.assertContains(response, 'loading="lazy"')
        self.assertContains(response, f'href="{first.image.url}" data-score-preview')
        self.assertContains(response, 'aria-label="Enlarge score preview: First page &amp; notes"')
        self.assertContains(response, '<dialog class="score-viewer"')
        self.assertContains(response, 'class="score-viewer-header"')
        self.assertContains(response, 'class="score-viewer-navigation" role="group" aria-label="Preview navigation"')
        self.assertContains(response, 'class="score-viewer-zoom" role="group" aria-label="Preview zoom"')
        self.assertContains(response, 'data-preview-previous aria-label="Previous score preview" disabled')
        self.assertContains(response, 'data-preview-next aria-label="Next score preview" disabled')
        self.assertContains(response, 'data-preview-status aria-live="polite"')
        self.assertContains(response, 'aria-label="Zoom in"')
        self.assertContains(response, 'aria-label="Zoom out"')
        self.assertContains(response, 'data-zoom-reset>Fit to view</button>')
        self.assertContains(response, '/static/js/score-previews.js', count=1)
        self.assertNotContains(self.client.get('/compositions/'), '/static/js/score-previews.js')

    def test_hostile_title_is_escaped_and_json_ld_cannot_close_script(self):
        title = '</script><script>alert("owned")</script><img src=x onerror=alert(1)> & Music'
        work = self.make_work(title=title, instrumentation='<b>SATB</b>')
        response = self.client.get(work.get_absolute_url())
        self.assertContains(response, f'<h1>{escape(title)}</h1>', html=True)
        self.assertNotContains(response, title)
        page = self.parse(response)
        self.assertEqual(len(page.schemas), 1)
        self.assertNotIn('<', page.schemas[0])
        self.assertIn('\\u003c/script>', page.schemas[0])
        schema = json.loads(page.schemas[0])
        self.assertEqual(schema['name'], title)
        self.assertEqual(schema['musicalInstrumentation'], '<b>SATB</b>')
        self.assertFalse(any(tag == 'img' and attrs.get('onerror')
                             for tag, attrs in page.tags))
        scripts = [attrs for tag, attrs in page.tags if tag == 'script']
        expected_scripts = [
            {'src': '/static/js/theme.js'},
            {'src': '/static/js/navigation.js', 'defer': None},
            {'type': 'application/ld+json'},
        ]
        if response.context['form'].turnstile_enabled:
            expected_scripts.append({
                'src': 'https://challenges.cloudflare.com/turnstile/v0/api.js',
                'async': None, 'defer': None,
            })
        self.assertEqual(scripts, expected_scripts)
        for path in ('/', '/compositions/'):
            response = self.client.get(path)
            self.assertNotContains(response, title)
            self.assertContains(response, escape(title))

    def test_clean_canonicals_open_graph_and_unique_page_metadata(self):
        work = self.make_work(seo_description='A specific search description.')
        titles = set()
        descriptions = set()
        for path in ('/', '/compositions/', '/about/', '/contact/',
                     work.get_absolute_url()):
            with self.subTest(path=path):
                response = self.client.get(path)
                page = self.parse(response)
                canonical = [attrs['href'] for tag, attrs in page.tags
                             if tag == 'link' and attrs.get('rel') == 'canonical']
                self.assertEqual(canonical, ['https://composer.example' + path])
                self.assertIn(('meta', {'property': 'og:url', 'content': canonical[0]}), page.tags)
                self.assertNotContains(response, 'content="noindex, follow"')
                titles.add(response.context['page_title'])
                descriptions.add(response.context['meta_description'])
        self.assertEqual(len(titles), 5)
        self.assertEqual(len(descriptions), 5)
        self.assertContains(self.client.get(work.get_absolute_url()),
                            'content="A specific search description."')
        for path in ('/', '/about/'):
            schema = json.loads(self.parse(self.client.get(path)).schemas[0])
            self.assertEqual(schema['@type'], 'Person')
            self.assertEqual(schema['name'], 'Thomas Alban')

    def test_all_filtered_catalogue_urls_are_noindex_with_clean_canonical(self):
        self.make_work(category='Choral')
        for query in ({'category': 'Choral'}, {'duration': 'short'},
                      {'category': 'invalid'}, {'category': '', 'duration': ''},
                      {'utm_source': 'search'}):
            with self.subTest(query=query):
                response = self.client.get('/compositions/', query)
                self.assertContains(response, 'content="noindex, follow"')
                self.assertContains(response,
                                    '<link rel="canonical" href="https://composer.example/compositions/">',
                                    html=True)

    def test_sitemap_contains_public_pages_and_published_works_only(self):
        work = self.make_work()
        draft = self.make_work('draft', is_published=False)
        response = self.client.get('/sitemap.xml', HTTP_HOST='composer.example', secure=True)
        self.assertEqual(response.status_code, 200)
        root = ElementTree.fromstring(response.content)
        locations = [node.text for node in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
        expected_paths = {'/', '/compositions/', '/about/', '/contact/',
                          work.get_absolute_url()}
        self.assertEqual(set(locations), {'https://composer.example' + path for path in expected_paths})
        self.assertNotIn(draft.get_absolute_url(), [urlsplit(url).path for url in locations])
        self.assertTrue(all('/admin/' not in url and '?' not in url for url in locations))

    def test_robots_allows_search_crawlers_and_queries_but_disallows_admin(self):
        draft = self.make_work('draft', is_published=False)
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')
        self.assertContains(response, 'User-agent: *\nAllow: /\n')
        self.assertContains(response, 'Disallow: /admin/')
        self.assertNotContains(response, 'Disallow: /*?')
        self.assertContains(response, 'Sitemap: https://composer.example/sitemap.xml')
        self.assertNotContains(response, 'Disallow: /\n')
        self.assertNotContains(response, draft.get_absolute_url())
        self.assertNotContains(response, 'https://composer.example/admin/')


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
    MAILERS=ACCEPTED_MAILERS,
    DEFAULT_FROM_EMAIL='composer@example.com',
    ENQUIRY_EMAIL='enquiries@example.com',
)
class PublicEnquiryTests(TestCase):
    make_work = PublicPageTests.make_work

    def setUp(self):
        verification = patch('core.enquiries.verify_turnstile', return_value=True)
        verification.start()
        self.addCleanup(verification.stop)
        mail.mailers['default']
        mail.outbox.clear()
        self.work = self.make_work('nunc-dimittis', title='Nunc dimittis')
        self.data = {'name': 'Visitor', 'email': 'visitor@example.com',
                     'copy_count': '12', 'message': 'Please send score information.'}

    def test_copy_count_only_appears_on_score_enquiry_and_is_optional(self):
        contact = self.client.get('/contact/')
        self.assertNotContains(contact, 'name="copy_count"')
        self.assertNotIn('copy_count', contact.context['form'].fields)
        score = self.client.get(self.work.get_absolute_url())
        self.assertContains(score, 'Approx. Copy Count')
        self.assertContains(score, 'Optional - an estimate is fine.')
        self.assertFalse(score.context['form'].fields['copy_count'].required)
        response = self.client.post(self.work.get_absolute_url(), {
            'name': 'Visitor', 'email': 'visitor@example.com',
        })
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('Copies:', mail.outbox[-1].body)

    def test_field_notes_follow_inputs_and_copy_help_remains_accessible(self):
        response = self.client.get(self.work.get_absolute_url())
        content = response.content.decode()
        start = content.index('name="copy_count"')
        note = content.index('Optional - an estimate is fine.')
        self.assertLess(start, note)
        self.assertContains(response, 'id="id_copy_count_helptext"', count=1)
        inputs = [attrs for tag, attrs in PageParser(content).tags if tag == 'input']
        copy_input = next(attrs for attrs in inputs if attrs.get('name') == 'copy_count')
        self.assertIn('id_copy_count_helptext', copy_input.get('aria-describedby', '').split())
        for name in ('name', 'email'):
            input_position = content.index(f'name="{name}"')
            self.assertGreater(content.index('Required.', input_position), input_position)

    def test_contact_ignores_submitted_copy_count(self):
        response = self.client.post('/contact/', {**self.data, 'copy_count': 'not a number'})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('Copies:', mail.outbox[-1].body)

    def test_contact_and_score_enquiry_success_prg_and_one_use_receipt(self):
        for path, subject in [('/contact/', 'Contact enquiry'),
                              (self.work.get_absolute_url(), 'Score enquiry')]:
            with self.subTest(path=path):
                client = Client()
                response = client.post(path, {**self.data, 'composition': 'Forged composition'})
                self.assertRedirects(response, path, fetch_redirect_response=False)
                email = mail.outbox[-1]
                self.assertEqual(email.subject, subject)
                self.assertEqual(email.from_email, 'composer@example.com')
                self.assertEqual(email.to, ['enquiries@example.com'])
                self.assertEqual(email.reply_to, ['visitor@example.com'])
                if subject == 'Score enquiry':
                    self.assertIn('Copies: 12', email.body)
                else:
                    self.assertNotIn('Copies:', email.body)
                self.assertIn(self.data['message'], email.body)
                self.assertNotIn('Forged composition', email.body)
                if subject == 'Score enquiry':
                    self.assertIn('Composition: Nunc dimittis', email.body)
                else:
                    self.assertNotIn('Composition:', email.body)
                count = len(mail.outbox)
                receipt = client.get(response['Location'])
                self.assertContains(receipt, 'Your message has been sent.')
                self.assertTrue(receipt.context['sent'])
                refresh = client.get(path)
                self.assertNotContains(refresh, 'Your message has been sent.')
                self.assertFalse(refresh.context['sent'])
                self.assertEqual(len(mail.outbox), count)
        self.assertEqual(len(mail.outbox), 2)

    def test_score_receipt_is_scoped_to_selected_composition(self):
        other = self.make_work('other')
        response = self.client.post(self.work.get_absolute_url(), self.data)
        self.assertRedirects(response, self.work.get_absolute_url(), fetch_redirect_response=False)
        self.assertNotContains(self.client.get(other.get_absolute_url()), 'Your message has been sent.')
        self.assertNotContains(self.client.get('/contact/'), 'Your message has been sent.')
        self.assertContains(self.client.get(self.work.get_absolute_url()), 'Your message has been sent.')

    def test_invalid_form_and_honeypot_never_report_success(self):
        for path in ('/contact/', self.work.get_absolute_url()):
            changes_to_test = [{'email': 'invalid'}, {'website': 'spam'}]
            if path == self.work.get_absolute_url():
                changes_to_test.append({'copy_count': '0'})
            for changes in changes_to_test:
                with self.subTest(path=path, changes=changes):
                    client = Client()
                    response = client.post(path, {**self.data, **changes})
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.context['form'].errors)
                    self.assertNotContains(response, 'Your message has been sent.')
                    self.assertNotContains(client.get(path), 'Your message has been sent.')
                    self.assertNotIn(SESSION_KEY, client.session)
        self.assertEqual(mail.outbox, [])

    def test_delivery_exception_or_zero_accepted_messages_never_reports_success(self):
        for path in ('/contact/', self.work.get_absolute_url()):
            for failure in ({'side_effect': RuntimeError('Delivery failed')}, {'return_value': 0}):
                with self.subTest(path=path, failure=failure):
                    client = Client()
                    # Each failure/retry pair is a separate short budget window.
                    with patch('core.enquiries.time', return_value=100000 + len(mail.outbox) * 600):
                        with patch('core.enquiries.EmailMessage.send', **failure), self.assertLogs('core.enquiries'):
                            response = client.post(path, self.data)
                        self.assertContains(response, ERROR_MESSAGE)
                        self.assertContains(response, 'We are sorry')
                        self.assertContains(response, '<a href="mailto:thomasalbanmusic@gmail.com">thomasalbanmusic@gmail.com</a>', html=True)
                        self.assertNotContains(response, 'Please check the fields below.')
                        self.assertFalse(response.context['sent'])
                        self.assertNotContains(response, 'Your message has been sent.')
                        self.assertNotContains(client.get(path), 'Your message has been sent.')
                        self.assertNotIn(SESSION_KEY, client.session)
                        # Failure must not prevent a later successful retry.
                        retry = client.post(path, self.data)
                        self.assertRedirects(retry, path, fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 4)

    def test_shared_budget_covers_both_routes_despite_fresh_clients_and_headers(self):
        paths = ('/contact/', self.work.get_absolute_url())
        for index in range(SHORT_WINDOW_LIMIT):
            client = Client()
            response = client.post(paths[index % 2], self.data)
            self.assertEqual(response.status_code, 302)
        for path in paths:
            client = Client()
            response = client.post(path, self.data, HTTP_X_FORWARDED_FOR='203.0.113.1')
            self.assertContains(response, SHARED_LIMIT_MESSAGE)
            self.assertContains(response, '<a href="mailto:thomasalbanmusic@gmail.com">thomasalbanmusic@gmail.com</a>', html=True)
            self.assertNotContains(response, 'Your message has been sent.')
            self.assertNotIn(SESSION_KEY, client.session)
            self.assertEqual(client.get(path).status_code, 200)
        self.assertEqual(len(mail.outbox), SHORT_WINDOW_LIMIT)

    @override_settings(
        DEBUG=False, TURNSTILE_ENABLED=True,
        TURNSTILE_SITE_KEY='public-widget-key', TURNSTILE_SECRET_KEY='private-widget-secret',
        TURNSTILE_HOSTNAMES=('composer.example',), SITE_URL='https://composer.example',
    )
    def test_turnstile_widget_and_real_verification_gate_on_both_routes(self):
        with (
            patch('core.enquiries.verify_turnstile', new=verify_turnstile),
            patch('core.turnstile.urlopen') as network,
        ):
            response_body = network.return_value.__enter__.return_value
            for index, path in enumerate(('/contact/', self.work.get_absolute_url())):
                client = Client()
                page = client.get(path)
                self.assertContains(page, 'data-sitekey="public-widget-key"')
                self.assertContains(page, 'data-action="enquiry"')
                self.assertNotContains(page, 'private-widget-secret')
                missing = client.post(path, self.data)
                self.assertContains(missing, ERROR_MESSAGE)
                network.assert_not_called()
                self.assertEqual(EnquiryBudget.objects.get().daily_count, index)
                response_body.read.return_value = b'{"success": false, "error-codes": ["timeout-or-duplicate"]}'
                rejected = client.post(path, {**self.data, 'cf-turnstile-response': 'used-token'})
                self.assertContains(rejected, ERROR_MESSAGE)
                self.assertEqual(EnquiryBudget.objects.get().daily_count, index)
                response_body.read.return_value = b'{"success": true, "hostname": "composer.example", "action": "enquiry"}'
                accepted = client.post(path, {**self.data, 'cf-turnstile-response': 'fresh-token'})
                self.assertEqual(accepted.status_code, 302)
                self.assertEqual(EnquiryBudget.objects.get().daily_count, index + 1)
                network.reset_mock()
        self.assertEqual(len(mail.outbox), 2)

    def test_csrf_enforced_for_both_forms_and_valid_token_delivers(self):
        for path in ('/contact/', self.work.get_absolute_url()):
            with self.subTest(path=path):
                client = Client(enforce_csrf_checks=True)
                self.assertEqual(client.post(path, self.data).status_code, 403)
                self.assertEqual(mail.outbox, [])
                page = client.get(path)
                self.assertContains(page, 'name="csrfmiddlewaretoken"')
                self.assertEqual(client.post(path, {**self.data, 'csrfmiddlewaretoken': 'bad'}).status_code, 403)
                token = client.cookies['csrftoken'].value
                response = client.post(path, {**self.data, 'csrfmiddlewaretoken': token})
                self.assertRedirects(response, path, fetch_redirect_response=False)
                self.assertContains(client.get(path), 'Your message has been sent.')
                self.assertEqual(len(mail.outbox), 1)
                mail.outbox.clear()
