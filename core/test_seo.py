import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree

from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings

from compositions.models import Composition, CompositionImage, ListeningLink, ScorePreview
from core.models import BiographyPhoto
from core.seo import page_context
from core.test_public_pages import PageParser
from core.test_settings import load_settings


@override_settings(SITE_URL='https://composer.example', ALLOWED_HOSTS=['testserver'],
                   SECURE_SSL_REDIRECT=False, PERSON_SAME_AS=[])
class SEOTests(TestCase):
    def setUp(self):
        self.work = Composition.objects.create(
            title='Nunc & dimittis', slug='nunc-dimittis', is_published=True,
            instrumentation='SATB choir',
        )

    def schema(self, path):
        return json.loads(PageParser(self.client.get(path).content.decode()).schemas[0])

    def test_title_description_and_matching_breadcrumbs(self):
        response = self.client.get(self.work.get_absolute_url())
        self.assertEqual(response.context['page_title'], 'Nunc & dimittis - Thomas Alban')
        self.assertIn('Nunc & dimittis by Thomas Alban.', response.context['meta_description'])
        self.assertIn('for SATB choir', response.context['meta_description'])
        self.assertNotIn('recording', response.context['meta_description'].lower())
        music, crumbs = self.schema(self.work.get_absolute_url())['@graph']
        self.assertEqual(music['@type'], 'MusicComposition')
        self.assertEqual(crumbs['@type'], 'BreadcrumbList')
        for position, (item, crumb) in enumerate(zip(crumbs['itemListElement'], response.context['breadcrumbs']), 1):
            self.assertEqual(item, {'@type': 'ListItem', 'position': position,
                                   'name': crumb['name'], 'item': 'https://composer.example' + crumb['url']})
        self.assertContains(response, 'aria-label="Breadcrumb"')
        self.assertContains(response, '<span aria-current="page">Nunc &amp; dimittis</span>', html=True)
        self.work.seo_description = 'Owner-written description & details.'
        self.work.save()
        self.assertEqual(self.client.get(self.work.get_absolute_url()).context['meta_description'], self.work.seo_description)
        self.assertEqual(self.client.get('/').context['page_title'], 'Thomas Alban - Composer')

    def test_same_as_is_opt_in_and_shared_by_home_and_about(self):
        self.assertNotIn('sameAs', self.schema('/')['@graph'][1])
        self.assertNotIn('sameAs', self.schema('/about/'))
        urls = ['https://profiles.example/official-owner']
        with override_settings(PERSON_SAME_AS=urls + urls):
            self.assertEqual(self.schema('/')['@graph'][1]['sameAs'], urls)
            self.assertEqual(self.schema('/about/')['sameAs'], urls)
        self.assertEqual(load_settings()['PERSON_SAME_AS'], [])
        self.assertEqual(load_settings(DJANGO_PERSON_SAME_AS=' https://profiles.example/owner, ')['PERSON_SAME_AS'], ['https://profiles.example/owner'])
        for url in ('javascript:alert(1)', '/profile', 'https://user:password@example.com', 'not a URL'):
            with self.subTest(url=url), self.assertRaises(ImproperlyConfigured):
                load_settings(DJANGO_PERSON_SAME_AS=url)

    def test_social_images_are_ordered_absolute_escaped_and_optional(self):
        paths = ['/', '/about/', self.work.get_absolute_url()]
        for path in paths:
            self.assertNotContains(self.client.get(path), 'og:image')
            self.assertNotContains(self.client.get(path), 'twitter:card')
        BiographyPhoto.objects.create(image='bio/second.jpg', alt_text='Second', position=2)
        BiographyPhoto.objects.create(image='', alt_text='Empty', position=0)
        BiographyPhoto.objects.create(image='bio/first.jpg', alt_text='Thomas & piano', position=1)
        for path in ('/', '/about/'):
            response = self.client.get(path)
            self.assertContains(response, 'content="https://composer.example/media/bio/first.jpg"', count=2)
            self.assertContains(response, 'content="Thomas &amp; piano"', count=2)
        self.assertNotContains(self.client.get(self.work.get_absolute_url()), 'og:image')
        CompositionImage.objects.create(composition=self.work, image='', alt_text='Empty')
        CompositionImage.objects.create(composition=self.work, image='photos/first.png', alt_text='Choir "singing"', position=1)
        CompositionImage.objects.create(composition=self.work, image='photos/second.png', alt_text='Second', position=2)
        response = self.client.get(self.work.get_absolute_url())
        self.assertEqual(response.context['social_image_url'], 'https://composer.example/media/photos/first.png')
        self.assertContains(response, 'content="Choir &quot;singing&quot;"', count=2)
        self.assertNotContains(self.client.get('/contact/'), 'og:image')
        external = SimpleNamespace(image=SimpleNamespace(url='https://cdn.example/photo.jpg'), alt_text='Photo')
        self.assertEqual(page_context('Title', 'Description', '/', image=external)['social_image_url'], external.image.url)

    def test_timestamps_track_changes_not_reads_or_noop_saves(self):
        original = self.work.updated_at
        self.assertIsNotNone(original)
        self.client.get(self.work.get_absolute_url())
        self.work.save()
        self.work.refresh_from_db()
        self.assertEqual(self.work.updated_at, original)
        later = datetime(2030, 1, 2, tzinfo=timezone.utc)
        with patch('compositions.signals.timezone.now', return_value=later):
            self.work.description = 'Changed description'
            self.work.save(update_fields=['description'])
        self.work.refresh_from_db()
        self.assertEqual(self.work.updated_at, later)

    def test_related_changes_deletions_and_reparenting_touch_composition(self):
        other = Composition.objects.create(title='Other', slug='other')
        for model, data in (
            (CompositionImage, {'image': 'photo.jpg', 'alt_text': 'Photo'}),
            (ScorePreview, {'image': 'preview.jpg', 'alt_text': 'Preview'}),
            (ListeningLink, {'label': 'Listen', 'url': 'https://example.com/recording'}),
        ):
            with self.subTest(model=model):
                Composition.objects.filter(pk__in=[self.work.pk, other.pk]).update(updated_at=None)
                item = model.objects.create(composition=self.work, **data)
                self.work.refresh_from_db()
                saved = self.work.updated_at
                self.assertIsNotNone(saved)
                item.save()
                self.work.refresh_from_db()
                self.assertEqual(self.work.updated_at, saved)
                item.position = 3
                item.save(update_fields=['position'])
                # A stale parent's no-op save must not roll back a related edit.
                self.work.save()
                self.work.refresh_from_db()
                self.assertGreater(self.work.updated_at, saved)
                item.composition = other
                item.save(update_fields=['composition'])
                other.refresh_from_db()
                self.assertIsNotNone(other.updated_at)
                before_delete = other.updated_at
                model.objects.filter(pk=item.pk).delete()
                other.refresh_from_db()
                self.assertGreater(other.updated_at, before_delete)

    def test_sitemap_omits_unknown_and_static_dates(self):
        Composition.objects.filter(pk=self.work.pk).update(updated_at=None)
        ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        def entries():
            root = ElementTree.fromstring(self.client.get('/sitemap.xml').content)
            return {node.find('s:loc', ns).text: node.find('s:lastmod', ns) for node in root}
        self.assertTrue(all(value is None for value in entries().values()))
        when = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        self.work.title = 'Edited title'
        with patch('compositions.signals.timezone.now', return_value=when):
            self.work.save()
        dated = entries()
        self.assertEqual(dated.pop('https://composer.example' + self.work.get_absolute_url()).text, when.date().isoformat())
        self.assertTrue(all(value is None for value in dated.values()))


class TimestampMigrationTests(TransactionTestCase):
    def test_existing_rows_remain_undated(self):
        before = [('compositions', '0008_alter_composition_text')]
        after = [('compositions', '0009_composition_updated_at')]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            old_model = executor.loader.project_state(before).apps.get_model('compositions', 'Composition')
            old = old_model.objects.create(title='Historic composition', slug='historic', is_published=True)
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            new_model = executor.loader.project_state(after).apps.get_model('compositions', 'Composition')
            self.assertIsNone(new_model.objects.get(pk=old.pk).updated_at)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
