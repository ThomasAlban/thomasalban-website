from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TestCase, TransactionTestCase

from .models import Category, Composition, CompositionCategory


class CategoryMigrationTests(TransactionTestCase):
    def test_existing_categories_and_timestamps_are_preserved(self):
        before = [('compositions', '0009_composition_updated_at')]
        after = [('compositions', '0010_composition_categories')]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate(before)
            old_model = executor.loader.project_state(before).apps.get_model(
                'compositions', 'Composition',
            )
            dated = datetime(2026, 10, 20, 12, 30, tzinfo=timezone.utc)
            fixtures = [
                ('published', 'Choral', True, dated),
                ('draft', 'Choral', False, None),
                ('blank', '', True, dated),
                ('blank-draft', '', False, None),
                ('comma', 'Choral, orchestral', True, dated),
                ('spaces', '  Chamber  ', False, dated),
                ('case', 'choral', True, None),
            ]
            rows = []
            for slug, name, published, updated_at in fixtures:
                row = old_model.objects.create(
                    title=slug, slug=slug, category=name,
                    is_published=published, updated_at=updated_at,
                )
                rows.append((row.pk, name, published, updated_at))

            executor = MigrationExecutor(connection)
            executor.migrate(after)
            apps = executor.loader.project_state(after).apps
            composition_model = apps.get_model('compositions', 'Composition')
            category_model = apps.get_model('compositions', 'Category')
            self.assertEqual(composition_model.objects.count(), len(rows))
            self.assertCountEqual(
                category_model.objects.values_list('name', flat=True),
                ['Choral', 'Choral, orchestral', '  Chamber  ', 'choral'],
            )
            for pk, name, published, updated_at in rows:
                with self.subTest(category=name, published=published):
                    composition = composition_model.objects.get(pk=pk)
                    self.assertEqual(
                        list(composition.categories.values_list('name', flat=True)),
                        [name] if name else [],
                    )
                    self.assertEqual(composition.updated_at, updated_at)
                    self.assertEqual(composition.is_published, published)
            shared = category_model.objects.get(name='Choral')
            self.assertCountEqual(
                shared.compositions.values_list('slug', flat=True),
                ['published', 'draft'],
            )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())


class CategoryTimestampTests(TestCase):
    def setUp(self):
        self.composition = Composition.objects.create(
            title='Published composition', slug='published', is_published=True,
        )
        self.draft = Composition.objects.create(title='Draft', slug='draft')
        self.unrelated = Composition.objects.create(title='Unrelated', slug='unrelated')
        self.choral = Category.objects.create(name='Choral')
        self.chamber = Category.objects.create(name='Chamber')
        self.original = datetime(2026, 10, 20, tzinfo=timezone.utc)
        self.later = datetime(2030, 1, 2, tzinfo=timezone.utc)
        self.reset_timestamps()

    def reset_timestamps(self):
        Composition.objects.all().update(updated_at=self.original)

    def assert_timestamps(self, *changed):
        changed_ids = {composition.pk for composition in changed}
        for composition in (self.composition, self.draft, self.unrelated):
            with self.subTest(composition=composition.slug):
                composition.refresh_from_db()
                self.assertEqual(
                    composition.updated_at,
                    self.later if composition.pk in changed_ids else self.original,
                )

    def test_forward_add_touches_only_composition(self):
        with patch('compositions.signals.timezone.now', return_value=self.later):
            self.composition.categories.add(self.choral, self.chamber)
        self.assert_timestamps(self.composition)
        self.assertCountEqual(
            self.composition.categories.all(), [self.choral, self.chamber],
        )

    def test_forward_remove_touches_only_composition(self):
        self.composition.categories.add(self.choral, self.chamber)
        self.draft.categories.add(self.choral)
        self.reset_timestamps()
        with patch('compositions.signals.timezone.now', return_value=self.later):
            self.composition.categories.remove(self.choral)
        self.assert_timestamps(self.composition)
        self.assertEqual(list(self.composition.categories.all()), [self.chamber])
        self.assertEqual(list(self.draft.categories.all()), [self.choral])

    def test_forward_clear_touches_only_composition(self):
        self.composition.categories.add(self.choral, self.chamber)
        self.draft.categories.add(self.choral)
        self.reset_timestamps()
        with patch('compositions.signals.timezone.now', return_value=self.later):
            self.composition.categories.clear()
        self.assert_timestamps(self.composition)
        self.assertFalse(self.composition.categories.exists())
        self.assertEqual(list(self.draft.categories.all()), [self.choral])

    def test_reverse_add_touches_all_added_compositions_including_drafts(self):
        with patch('compositions.signals.timezone.now', return_value=self.later):
            self.choral.compositions.add(self.composition, self.draft)
        self.assert_timestamps(self.composition, self.draft)
        self.assertCountEqual(
            self.choral.compositions.all(), [self.composition, self.draft],
        )

    def test_reverse_remove_touches_only_removed_compositions(self):
        self.choral.compositions.add(self.composition, self.draft, self.unrelated)
        self.reset_timestamps()
        with patch('compositions.signals.timezone.now', return_value=self.later):
            self.choral.compositions.remove(self.composition, self.draft)
        self.assert_timestamps(self.composition, self.draft)
        self.assertEqual(list(self.choral.compositions.all()), [self.unrelated])

    def test_reverse_clear_touches_previously_related_compositions(self):
        self.choral.compositions.add(self.composition, self.draft)
        self.unrelated.categories.add(self.chamber)
        self.reset_timestamps()
        with patch('compositions.signals.timezone.now', return_value=self.later):
            self.choral.compositions.clear()
        self.assert_timestamps(self.composition, self.draft)
        self.assertFalse(self.choral.compositions.exists())
        self.assertEqual(list(self.unrelated.categories.all()), [self.chamber])

    def test_category_rename_touches_only_related_compositions(self):
        self.choral.compositions.add(self.composition, self.draft)
        self.reset_timestamps()
        with patch('compositions.signals.timezone.now', return_value=self.later):
            self.choral.name = 'Choir'
            self.choral.save(update_fields=['name'])
        self.assert_timestamps(self.composition, self.draft)
        self.assertEqual(self.composition.categories.get().name, 'Choir')
        self.assertEqual(self.draft.categories.get().name, 'Choir')

    def test_category_deletion_touches_only_previously_related_compositions(self):
        self.choral.compositions.add(self.composition, self.draft)
        self.composition.categories.add(self.chamber)
        self.reset_timestamps()
        with patch('compositions.signals.timezone.now', return_value=self.later):
            self.choral.delete()
        self.assert_timestamps(self.composition, self.draft)
        self.assertEqual(list(self.composition.categories.all()), [self.chamber])
        self.assertFalse(self.draft.categories.exists())

    def test_unchanged_category_save_does_not_touch_compositions(self):
        self.choral.compositions.add(self.composition, self.draft)
        self.reset_timestamps()
        for update_fields in (None, ['name']):
            with self.subTest(update_fields=update_fields):
                with patch('compositions.signals.timezone.now', return_value=self.later):
                    self.choral.save(update_fields=update_fields)
                self.assert_timestamps()

    def test_unchanged_composition_save_preserves_membership_timestamp(self):
        self.composition.refresh_from_db()
        with patch('compositions.signals.timezone.now', return_value=self.later):
            self.composition.categories.add(self.choral)
        with patch(
            'compositions.signals.timezone.now',
            return_value=datetime(2031, 1, 2, tzinfo=timezone.utc),
        ):
            self.composition.save()
        self.assert_timestamps(self.composition)

    def test_duplicate_add_and_empty_clear_do_not_touch_compositions(self):
        self.composition.categories.add(self.choral)
        self.reset_timestamps()
        with patch('compositions.signals.timezone.now', return_value=self.later):
            self.composition.categories.add(self.choral)
            self.choral.compositions.add(self.composition)
            self.draft.categories.clear()
            self.chamber.compositions.clear()
        self.assert_timestamps()


    def test_direct_membership_creation_touches_only_owner_including_draft(self):
        for composition in (self.composition, self.draft):
            with self.subTest(composition=composition.slug):
                self.reset_timestamps()
                with patch('compositions.signals.timezone.now', return_value=self.later):
                    CompositionCategory.objects.create(
                        composition=composition, category=self.choral,
                    )
                self.assert_timestamps(composition)

    def test_reordering_membership_touches_only_owner(self):
        membership = CompositionCategory.objects.create(
            composition=self.composition, category=self.choral, position=0,
        )
        CompositionCategory.objects.create(composition=self.draft, category=self.choral)
        self.reset_timestamps()
        with patch('compositions.signals.timezone.now', return_value=self.later):
            membership.position = 5
            membership.save(update_fields=['position'])
        self.assert_timestamps(self.composition)
        membership.refresh_from_db()
        self.assertEqual(membership.position, 5)

    def test_direct_membership_delete_touches_only_owner(self):
        membership = CompositionCategory.objects.create(
            composition=self.composition, category=self.choral,
        )
        CompositionCategory.objects.create(composition=self.draft, category=self.choral)
        self.reset_timestamps()
        with patch('compositions.signals.timezone.now', return_value=self.later):
            membership.delete()
        self.assert_timestamps(self.composition)
        self.assertFalse(self.composition.category_memberships.exists())
        self.assertTrue(self.draft.category_memberships.exists())
        self.assertTrue(Category.objects.filter(pk=self.choral.pk).exists())

    def test_queryset_membership_delete_touches_only_owners(self):
        for composition in (self.composition, self.draft):
            CompositionCategory.objects.create(composition=composition, category=self.choral)
        self.reset_timestamps()
        with patch('compositions.signals.timezone.now', return_value=self.later):
            CompositionCategory.objects.filter(category=self.choral).delete()
        self.assert_timestamps(self.composition, self.draft)

    def test_unchanged_membership_save_does_not_touch_owner(self):
        membership = CompositionCategory.objects.create(
            composition=self.composition, category=self.choral, position=3,
        )
        self.reset_timestamps()
        for update_fields in (None, ['position'], ['category']):
            with self.subTest(update_fields=update_fields):
                with patch('compositions.signals.timezone.now', return_value=self.later):
                    membership.save(update_fields=update_fields)
                self.assert_timestamps()

    def test_unsaved_position_change_does_not_touch_owner(self):
        membership = CompositionCategory.objects.create(
            composition=self.composition, category=self.choral, position=3,
        )
        self.reset_timestamps()
        with patch('compositions.signals.timezone.now', return_value=self.later):
            membership.position = 9
            membership.save(update_fields=['category'])
        self.assert_timestamps()
        membership.refresh_from_db()
        self.assertEqual(membership.position, 3)


class CategoryAdminFormTests(TestCase):
    def setUp(self):
        self.choral = Category.objects.create(name='Choral')
        self.chamber = Category.objects.create(name='Chamber')
        self.composition = Composition.objects.create(title='Mixed categories', slug='mixed')
        self.request = RequestFactory().get('/admin/compositions/composition/add/')
        self.request.user = get_user_model()(
            is_active=True, is_staff=True, is_superuser=True,
        )
        self.model_admin = admin.site._registry[Composition]

    def get_inline(self):
        from .admin import CompositionCategoryInline

        inlines = self.model_admin.get_inline_instances(self.request, self.composition)
        matches = [inline for inline in inlines if isinstance(inline, CompositionCategoryInline)]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def formset(self, rows, initial=0):
        formset_class = self.get_inline().get_formset(self.request, self.composition)
        prefix = formset_class.get_default_prefix()
        data = {
            f'{prefix}-TOTAL_FORMS': str(len(rows)),
            f'{prefix}-INITIAL_FORMS': str(initial),
            f'{prefix}-MIN_NUM_FORMS': '0',
            f'{prefix}-MAX_NUM_FORMS': '1000',
        }
        for index, row in enumerate(rows):
            for field, value in row.items():
                data[f'{prefix}-{index}-{field}'] = str(value)
        return formset_class(data=data, instance=self.composition)

    def test_categories_use_inline_instead_of_main_form_widget(self):
        inline = self.get_inline()
        self.assertIs(inline.model, CompositionCategory)
        self.assertEqual(list(inline.fields), ['category', 'position'])
        self.assertEqual(inline.extra, 0)
        self.assertNotIn('categories', self.model_admin.filter_horizontal)
        self.assertNotIn('categories', self.model_admin.get_form(self.request).base_fields)

    def test_inline_saves_multiple_categories_in_position_order(self):
        formset = self.formset([
            {'category': self.chamber.pk, 'position': 8},
            {'category': self.choral.pk, 'position': 2},
        ])
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()
        self.assertEqual(self.composition.categories_display, 'Choral, Chamber')
        memberships = list(self.composition.category_memberships.all())
        self.assertEqual([row.position for row in memberships], [2, 8])
        self.assertCountEqual(self.composition.categories.all(), [self.choral, self.chamber])
        unbound = self.get_inline().get_formset(self.request, self.composition)(
            instance=self.composition,
        )
        self.assertEqual(
            [form.initial['category'] for form in unbound.initial_forms],
            [self.choral.pk, self.chamber.pk],
        )

    def test_inline_edits_order_and_deletes_memberships(self):
        choral = CompositionCategory.objects.create(
            composition=self.composition, category=self.choral, position=0,
        )
        chamber = CompositionCategory.objects.create(
            composition=self.composition, category=self.chamber, position=1,
        )
        formset = self.formset([
            {'id': choral.pk, 'category': self.choral.pk, 'position': 9},
            {'id': chamber.pk, 'category': self.chamber.pk, 'position': 0},
        ], initial=2)
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()
        self.assertEqual(self.composition.categories_display, 'Chamber, Choral')
        choral.refresh_from_db()
        chamber.refresh_from_db()
        self.assertEqual((choral.position, chamber.position), (9, 0))
        formset = self.formset([
            {'id': chamber.pk, 'category': self.chamber.pk, 'position': 0, 'DELETE': 'on'},
            {'id': choral.pk, 'category': self.choral.pk, 'position': 9},
        ], initial=2)
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()
        self.assertEqual(self.composition.categories_display, 'Choral')
        self.assertFalse(CompositionCategory.objects.filter(pk=chamber.pk).exists())
        self.assertTrue(Category.objects.filter(pk=self.chamber.pk).exists())

    def test_inline_rejects_duplicate_categories(self):
        formset = self.formset([
            {'category': self.choral.pk, 'position': 0},
            {'category': self.choral.pk, 'position': 1},
        ])
        self.assertFalse(formset.is_valid())
        self.assertTrue(formset.non_form_errors() or any(formset.errors))
        self.assertFalse(self.composition.category_memberships.exists())

    def test_inline_rejects_duplicate_of_existing_category(self):
        membership = CompositionCategory.objects.create(
            composition=self.composition, category=self.choral,
        )
        formset = self.formset([
            {'id': membership.pk, 'category': self.choral.pk, 'position': 0},
            {'category': self.choral.pk, 'position': 1},
        ], initial=1)
        self.assertFalse(formset.is_valid())
        self.assertEqual(self.composition.category_memberships.count(), 1)

    def test_empty_inline_and_blank_extra_row_are_optional(self):
        for rows in ([], [{'category': '', 'position': '0'}]):
            with self.subTest(rows=rows):
                formset = self.formset(rows)
                self.assertTrue(formset.is_valid(), formset.errors)
                self.assertEqual(formset.save(), [])
                self.assertFalse(self.composition.category_memberships.exists())


class OrderedCategoryTests(TestCase):
    def setUp(self):
        self.composition = Composition.objects.create(title='First', slug='first')
        self.other = Composition.objects.create(title='Second', slug='second')
        self.chamber = Category.objects.create(name='Chamber')
        self.choral = Category.objects.create(name='Choral')

    def test_explicit_through_model_and_position_contract(self):
        field = Composition._meta.get_field('categories')
        self.assertIs(field.remote_field.through, CompositionCategory)
        self.assertFalse(CompositionCategory._meta.auto_created)
        composition_field = CompositionCategory._meta.get_field('composition')
        self.assertEqual(composition_field.remote_field.related_name, 'category_memberships')
        self.assertIs(composition_field.remote_field.model, Composition)
        self.assertIs(CompositionCategory._meta.get_field('category').remote_field.model, Category)
        position = CompositionCategory._meta.get_field('position')
        self.assertIsInstance(position, models.PositiveIntegerField)
        self.assertEqual(position.default, 0)
        self.assertTrue(position.help_text)
        self.assertEqual(list(CompositionCategory._meta.ordering), ['position', 'pk'])
        membership = CompositionCategory(composition=self.composition, category=self.choral)
        self.assertEqual(membership.position, 0)
        membership.full_clean()
        membership.position = -1
        with self.assertRaises(ValidationError):
            membership.full_clean()

    def test_order_is_independent_for_each_composition(self):
        for composition, categories in (
            (self.composition, [self.choral, self.chamber]),
            (self.other, [self.chamber, self.choral]),
        ):
            for position, category in enumerate(categories):
                CompositionCategory.objects.create(
                    composition=composition, category=category, position=position,
                )
        self.assertEqual(self.composition.categories_display, 'Choral, Chamber')
        self.assertEqual(self.other.categories_display, 'Chamber, Choral')
        self.assertEqual(
            list(self.composition.category_memberships.values_list('category_id', flat=True)),
            [self.choral.pk, self.chamber.pk],
        )
        self.assertEqual(
            list(self.other.category_memberships.values_list('category_id', flat=True)),
            [self.chamber.pk, self.choral.pk],
        )

    def test_equal_positions_use_membership_pk_not_category_name(self):
        first = CompositionCategory.objects.create(
            composition=self.composition, category=self.choral, position=0,
        )
        second = CompositionCategory.objects.create(
            composition=self.composition, category=self.chamber, position=0,
        )
        self.assertEqual(list(self.composition.category_memberships.all()), [first, second])
        self.assertEqual(self.composition.categories_display, 'Choral, Chamber')

    def test_display_uses_membership_order_with_related_categories(self):
        CompositionCategory.objects.create(
            composition=self.composition, category=self.choral, position=1,
        )
        CompositionCategory.objects.create(
            composition=self.composition, category=self.chamber, position=2,
        )
        with self.assertNumQueries(1):
            self.assertEqual(self.composition.categories_display, 'Choral, Chamber')

    def test_empty_display(self):
        self.assertEqual(self.composition.categories_display, '')

    def test_duplicate_pair_is_rejected_by_database(self):
        CompositionCategory.objects.create(composition=self.composition, category=self.choral)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CompositionCategory.objects.create(
                composition=self.composition, category=self.choral, position=5,
            )
        self.assertEqual(self.composition.category_memberships.count(), 1)


class OrderedCategoryMigrationTests(TransactionTestCase):
    def test_assignments_order_and_timestamps_are_preserved(self):
        before = [('compositions', '0010_composition_categories')]
        after = [('compositions', '0011_ordered_composition_categories')]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            old_composition = apps.get_model('compositions', 'Composition')
            old_category = apps.get_model('compositions', 'Category')
            categories = {
                name: old_category.objects.create(name=name)
                for name in ['Orchestral', 'Choral', 'Chamber', 'Unused']
            }
            dated = datetime(2026, 10, 20, 12, 30, tzinfo=timezone.utc)
            fixtures = [
                ('published', True, dated, ['Orchestral', 'Choral', 'Chamber']),
                ('draft', False, None, ['Choral', 'Chamber']),
                ('single', False, dated, ['Orchestral']),
                ('empty', True, None, []),
            ]
            rows = []
            for slug, published, timestamp, names in fixtures:
                composition = old_composition.objects.create(
                    title=slug, slug=slug, is_published=published, updated_at=timestamp,
                )
                for name in names:
                    composition.categories.add(categories[name])
                rows.append((composition.pk, slug, published, timestamp, sorted(names)))
            old_through = old_composition._meta.get_field('categories').remote_field.through
            old_table = old_through._meta.db_table
            expected_category_ids = {name: category.pk for name, category in categories.items()}

            executor = MigrationExecutor(connection)
            executor.migrate(after)
            apps = executor.loader.project_state(after).apps
            composition_model = apps.get_model('compositions', 'Composition')
            category_model = apps.get_model('compositions', 'Category')
            membership_model = apps.get_model('compositions', 'CompositionCategory')
            self.assertIs(
                composition_model._meta.get_field('categories').remote_field.through,
                membership_model,
            )
            self.assertNotEqual(membership_model._meta.db_table, old_table)
            self.assertIn(membership_model._meta.db_table, connection.introspection.table_names())
            self.assertNotIn(old_table, connection.introspection.table_names())
            self.assertEqual(composition_model.objects.count(), len(rows))
            self.assertEqual(
                dict(category_model.objects.values_list('name', 'pk')), expected_category_ids,
            )
            self.assertEqual(membership_model.objects.count(), sum(len(row[4]) for row in rows))
            for pk, slug, published, timestamp, names in rows:
                with self.subTest(slug=slug):
                    composition = composition_model.objects.get(pk=pk)
                    self.assertEqual(composition.slug, slug)
                    self.assertEqual(composition.title, slug)
                    self.assertEqual(composition.is_published, published)
                    self.assertEqual(composition.updated_at, timestamp)
                    memberships = membership_model.objects.filter(composition_id=pk)
                    self.assertEqual(
                        list(memberships.values_list('category__name', 'position')),
                        list(zip(names, range(len(names)))),
                    )
                    self.assertCountEqual(
                        composition.categories.values_list('name', flat=True), names,
                    )
            self.assertFalse(membership_model.objects.filter(category_id=categories['Unused'].pk).exists())
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
