from datetime import date

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Composition, ScorePreview


class CompositionTests(TestCase):
    def make_work(self, slug='test-work', **kwargs):
        return Composition.objects.create(title='Test work', slug=slug, **kwargs)

    def test_minimal_work_is_unpublished_and_metadata_is_optional(self):
        work = self.make_work()
        work.full_clean()
        self.assertFalse(work.is_published)
        self.assertFalse(work.is_featured)
        self.assertIsNone(work.premiered_date)
        self.assertIsNone(work.duration_seconds)
        self.assertEqual(str(work), 'Test work')

    def test_published_queryset_excludes_drafts(self):
        self.make_work('draft', is_featured=True)
        published = self.make_work('published', is_published=True)
        self.assertEqual(list(Composition.objects.published()), [published])

    def test_premiere_order_and_undated_fallback(self):
        older = self.make_work('older', premiered_date=date(2024, 1, 1))
        newer = self.make_work('newer', premiered_date=date(2025, 1, 1))
        undated_old = self.make_work('undated-old', year_composed=2020)
        undated_new = self.make_work('undated-new', year_composed=2026)
        unknown = self.make_work('unknown')
        self.assertEqual(
            list(Composition.objects.all()),
            [newer, older, undated_new, undated_old, unknown],
        )

    def test_ordering_ties_are_deterministic(self):
        first = self.make_work('first')
        second = self.make_work('second')
        self.assertEqual(list(Composition.objects.all()), [second, first])

    def test_slug_is_unique(self):
        self.make_work()
        duplicate = Composition(title='Another work', slug='test-work')
        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_invalid_metadata_is_rejected(self):
        for metadata in (
            {'duration_seconds': 0},
            {'duration_seconds': -1},
            {'year_composed': 0},
            {'year_composed': 10000},
        ):
            with self.subTest(metadata=metadata):
                work = Composition(title='Test work', slug='test-work', **metadata)
                with self.assertRaises(ValidationError):
                    work.full_clean()

    def test_duration_is_approximate_in_half_minute_steps(self):
        for seconds, expected in [
            (None, ''), (1, 'c. 0:30'), (44, 'c. 0:30'),
            (45, 'c. 1:00'), (60, 'c. 1:00'), (74, 'c. 1:00'),
            (75, 'c. 1:30'), (90, 'c. 1:30'), (105, 'c. 2:00'),
            (120, 'c. 2:00'), (301, 'c. 5:00'), (3599, 'c. 60:00'),
        ]:
            with self.subTest(seconds=seconds):
                self.assertEqual(Composition(duration_seconds=seconds).duration_display, expected)

    def test_admin_duration_accepts_and_preserves_arbitrary_positive_seconds(self):
        model_admin = admin.site._registry[Composition]
        field = model_admin.formfield_for_dbfield(
            Composition._meta.get_field('duration_seconds'), request=None,
        )
        self.assertEqual(field.widget.attrs['step'], 1)
        self.assertEqual(field.widget.attrs['min'], 1)
        self.assertIn('stored value is unchanged', field.help_text)
        form_class = model_admin.get_form(None)
        work = self.make_work(duration_seconds=44)
        for seconds in (1, 44, 301):
            with self.subTest(seconds=seconds):
                form = form_class({'title': work.title, 'slug': work.slug,
                                   'duration_seconds': seconds}, instance=work)
                self.assertTrue(form.is_valid(), form.errors)
                form.save()
                work.refresh_from_db()
                self.assertEqual(work.duration_seconds, seconds)
        for value in (0, -1, 1.5):
            with self.subTest(value=value):
                form = form_class({'title': work.title, 'slug': work.slug,
                                   'duration_seconds': value}, instance=work)
                self.assertFalse(form.is_valid())
                self.assertIn('duration_seconds', form.errors)

    def test_admin_has_score_preview_inline(self):
        model_admin = admin.site._registry[Composition]
        self.assertEqual(model_admin.inlines[0].model, ScorePreview)


class ScorePreviewTests(TestCase):
    def setUp(self):
        self.work = Composition.objects.create(title='Test work', slug='test-work')

    def make_preview(self, position):
        return ScorePreview.objects.create(
            composition=self.work,
            image='score_previews/example.png',
            alt_text='First page of the test score',
            position=position,
        )

    def test_previews_are_ordered_with_stable_ties(self):
        later = self.make_preview(2)
        first = self.make_preview(0)
        second = self.make_preview(0)
        self.assertEqual(list(self.work.score_previews.all()), [first, second, later])

    def test_alt_text_and_image_are_required(self):
        preview = ScorePreview(composition=self.work)
        with self.assertRaises(ValidationError) as error:
            preview.full_clean()
        self.assertIn('alt_text', error.exception.message_dict)
        self.assertIn('image', error.exception.message_dict)

    def test_deleting_work_cascades_to_previews(self):
        self.make_preview(0)
        self.work.delete()
        self.assertFalse(ScorePreview.objects.exists())
