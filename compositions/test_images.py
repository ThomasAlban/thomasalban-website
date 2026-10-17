from datetime import date
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.forms import modelform_factory
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils.html import escape
from PIL import Image

from .models import Composition, CompositionImage


@override_settings(ALLOWED_HOSTS=['testserver'], SECURE_SSL_REDIRECT=False)
class CompositionImageTests(TestCase):
    def setUp(self):
        self.work = Composition.objects.create(
            title='Test work', slug='test-work', is_published=True,
        )

    def make_image(self, position=0, **kwargs):
        data = {
            'image': f'composition_images/photo-{position}.jpg',
            'alt_text': 'Musicians taking a bow at the premiere',
            'position': position,
        }
        data.update(kwargs)
        return CompositionImage.objects.create(composition=self.work, **data)

    def test_images_are_ordered_with_stable_ties(self):
        later = self.make_image(2)
        first = self.make_image(0)
        second = self.make_image(0)
        self.assertEqual(list(self.work.images.all()), [first, second, later])
        self.assertEqual(str(first), 'Test work - image 0')

    def test_image_and_descriptive_alt_text_are_required(self):
        image = CompositionImage(composition=self.work)
        with self.assertRaises(ValidationError) as error:
            image.full_clean()
        self.assertIn('image', error.exception.message_dict)
        self.assertIn('alt_text', error.exception.message_dict)
        form_class = modelform_factory(CompositionImage, fields=['image', 'alt_text'])
        form = form_class(data={'alt_text': '   '})
        self.assertFalse(form.is_valid())
        self.assertIn('alt_text', form.errors)

    def test_caption_is_optional_and_position_nonnegative(self):
        image = self.make_image()
        image.full_clean()
        self.assertEqual(image.caption, '')
        image.position = -1
        with self.assertRaises(ValidationError) as error:
            image.full_clean()
        self.assertIn('position', error.exception.message_dict)

    def test_upload_uses_dated_composition_images_directory(self):
        data = BytesIO()
        Image.new('RGB', (8, 6), color='white').save(data, format='PNG')
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = CompositionImage(
                composition=self.work,
                image=SimpleUploadedFile('premiere.png', data.getvalue(), content_type='image/png'),
                alt_text='Musicians at the premiere',
            )
            image.full_clean()
            image.save()
            self.assertRegex(image.image.name, r'^composition_images/\d{4}/\d{2}/premiere\.png$')
            self.assertTrue(image.image.storage.exists(image.image.name))

    def test_deleting_composition_cascades_to_images(self):
        self.make_image()
        self.work.delete()
        self.assertFalse(CompositionImage.objects.exists())

    def test_admin_has_image_inline_and_premiered_date(self):
        model_admin = admin.site._registry[Composition]
        inline = next(inline for inline in model_admin.inlines if inline.model == CompositionImage)
        self.assertEqual(inline.fields, ['image', 'alt_text', 'caption', 'position'])
        self.assertIn('premiered_date', model_admin.list_display)
        self.assertNotIn('release_date', model_admin.list_display)

    def test_gallery_order_alt_text_caption_and_lazy_loading(self):
        later = self.make_image(2)
        first = self.make_image(
            0, alt_text='Choir & conductor taking a bow',
            caption='<script>not markup</script> & premiere',
        )
        response = self.client.get(self.work.get_absolute_url())
        self.assertContains(response, 'id="composition-images"')
        self.assertNotContains(response, '>Gallery</h2>')
        self.assertContains(response, 'alt="Choir &amp; conductor taking a bow"')
        self.assertContains(response, f'<figcaption>{escape(first.caption)}</figcaption>', html=True)
        self.assertNotContains(response, first.caption)
        self.assertContains(response, 'loading="lazy" decoding="async"', count=2)
        content = response.content.decode()
        self.assertLess(content.index(first.image.url), content.index(later.image.url))
        self.assertContains(response, '<figcaption>', count=1)

    def test_gallery_is_below_description_before_enquiry_in_left_column(self):
        self.work.description = 'Description before the premiere photos.'
        self.work.audio_file = 'audio/recording.mp3'
        self.work.save()
        image = self.make_image()
        response = self.client.get(self.work.get_absolute_url())
        content = response.content.decode()
        self.assertLess(content.index(self.work.description), content.index('id="composition-images"'))
        self.assertLess(content.index(image.image.url), content.index('id="recording-title"'))
        self.assertLess(content.index('id="composition-images"'), content.index('<aside class="enquiry-panel"'))

    def test_catalogue_uses_first_ordered_photo_as_thumbnail_only(self):
        later = self.make_image(3)
        first = self.make_image(0, image='composition_images/first.jpg', alt_text='Choir & conductor')
        for params in ({}, {'q': 'Test'}):
            response = self.client.get('/compositions/', params)
            self.assertContains(response, first.image.url, count=1)
            self.assertContains(response, 'class="work-card-image"')
            self.assertContains(response, 'alt="Choir &amp; conductor"')
            self.assertNotContains(response, later.image.url)
            self.assertNotContains(response, 'id="composition-images"')
        response = self.client.get('/')
        self.assertContains(response, first.image.url, count=1)
        self.assertNotContains(response, later.image.url)
        response = self.client.get(self.work.get_absolute_url())
        self.assertContains(response, first.image.url, count=1)
        self.assertContains(response, later.image.url, count=1)

    def test_home_featured_and_recent_use_first_ordered_photo(self):
        self.work.is_featured = True
        self.work.save()
        self.make_image(0, image='')
        first = self.make_image(1, alt_text='Choir & conductor')
        later = self.make_image(2)
        response = self.client.get('/')
        self.assertContains(response, first.image.url, count=2)
        self.assertContains(response, 'alt="Choir &amp; conductor"', count=2)
        self.assertContains(response, 'loading="lazy" decoding="async"', count=2)
        self.assertNotContains(response, later.image.url)
        content = response.content.decode()
        featured, recent = content.split('aria-labelledby="recent-title"')
        self.assertIn(first.image.url, featured)
        self.assertIn(first.image.url, recent)

    def test_home_thumbnail_queries_do_not_grow_with_recent_compositions(self):
        self.work.is_featured = True
        self.work.save()
        self.make_image()
        with self.assertNumQueries(5):
            self.client.get('/')
        for number in range(5):
            work = Composition.objects.create(
                title=f'Other {number}', slug=f'other-{number}', is_published=True,
            )
            CompositionImage.objects.create(
                composition=work, image=f'composition_images/other-{number}.jpg',
                alt_text='Other premiere',
            )
        with self.assertNumQueries(5):
            response = self.client.get('/')
        for work in response.context['recent_works']:
            self.assertEqual(len(work.thumbnail_images), 1)

    def test_no_gallery_or_card_image_without_images(self):
        self.assertNotContains(self.client.get(self.work.get_absolute_url()), 'id="composition-images"')
        self.assertNotContains(self.client.get('/compositions/'), 'work-card-image')
        self.work.is_featured = True
        self.work.save()
        self.assertNotContains(self.client.get('/'), 'class="work-card-image"')

    def test_draft_images_are_not_exposed(self):
        image = self.make_image()
        self.work.is_published = False
        self.work.save()
        self.assertEqual(self.client.get(self.work.get_absolute_url()).status_code, 404)
        for path in ('/compositions/', '/'):
            self.assertNotContains(self.client.get(path), image.image.url)

    def test_catalogue_fetches_one_thumbnail_per_composition_in_one_query(self):
        self.make_image()
        other = Composition.objects.create(title='Other', slug='other', is_published=True)
        CompositionImage.objects.create(
            composition=other, image='composition_images/other.jpg', alt_text='Other premiere',
        )
        self.make_image(2)
        with self.assertNumQueries(3):
            response = self.client.get('/compositions/')
        for work in response.context['works']:
            self.assertEqual(len(work.thumbnail_images), 1)

    def test_premiered_date_is_displayed_and_absent_date_is_omitted(self):
        self.assertNotContains(self.client.get(self.work.get_absolute_url()), '<dt>Premiered</dt>')
        self.work.premiered_date = date(2026, 1, 2)
        self.work.save()
        response = self.client.get(self.work.get_absolute_url())
        self.assertContains(response, '<dt>Premiered</dt>')
        self.assertContains(response, '<time datetime="2026-01-02">2 January 2026</time>', html=True)
        self.assertNotContains(response, '<dt>Released</dt>')


class PremiereDateMigrationTests(TransactionTestCase):
    migrate_from = [('compositions', '0002_remove_composition_recording_url_and_more')]
    migrate_to = [('compositions', '0003_premiered_date_and_composition_images')]

    def test_rename_preserves_existing_dates_and_nulls_in_both_directions(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        try:
            old_apps = executor.loader.project_state(self.migrate_from).apps
            Work = old_apps.get_model('compositions', 'Composition')
            dated = Work.objects.create(title='Dated', slug='dated', release_date=date(2025, 6, 7))
            undated = Work.objects.create(title='Undated', slug='undated')
            executor = MigrationExecutor(connection)
            executor.migrate(self.migrate_to)
            new_apps = executor.loader.project_state(self.migrate_to).apps
            Work = new_apps.get_model('compositions', 'Composition')
            self.assertEqual(Work.objects.get(pk=dated.pk).premiered_date, date(2025, 6, 7))
            self.assertIsNone(Work.objects.get(pk=undated.pk).premiered_date)
            executor = MigrationExecutor(connection)
            executor.migrate(self.migrate_from)
            restored_apps = executor.loader.project_state(self.migrate_from).apps
            Work = restored_apps.get_model('compositions', 'Composition')
            self.assertEqual(Work.objects.get(pk=dated.pk).release_date, date(2025, 6, 7))
            self.assertIsNone(Work.objects.get(pk=undated.pk).release_date)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
