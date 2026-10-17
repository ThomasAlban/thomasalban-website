from datetime import date

from django.test import TestCase
from django.urls import reverse

from .models import Composition


class CatalogueTests(TestCase):
    def setUp(self):
        self.url = reverse('compositions:list')
        self.alpha = Composition.objects.create(
            title='alpha', slug='alpha', category='Choral', instrumentation='SATB choir',
            year_composed=2020, premiered_date=date(2024, 1, 1),
            duration_seconds=240, is_published=True,
        )
        self.beta = Composition.objects.create(
            title='Beta', slug='beta', category='Chamber', instrumentation='Piano and violin',
            year_composed=2025, premiered_date=date(2023, 1, 1),
            duration_seconds=420, is_published=True,
        )
        self.undated = Composition.objects.create(
            title='Undated', slug='undated', year_composed=2020, is_published=True,
        )
        self.unknown = Composition.objects.create(
            title='Unknown', slug='unknown', is_published=True,
        )
        self.draft = Composition.objects.create(
            title='Draft choir', slug='draft', category='Hidden', year_composed=2030,
        )

    def test_search_matches_title_category_and_instrumentation(self):
        for query, expected in [
            (' ALPHA ', [self.alpha]), ('CHORAL', [self.alpha]),
            ('choir', [self.alpha]), ('violin', [self.beta]),
        ]:
            with self.subTest(query=query):
                response = self.client.get(self.url, {'q': query})
                self.assertEqual(list(response.context['works']), expected)
                self.assertContains(response, 'Matching compositions')
                self.assertContains(response, 'Clear filters')

    def test_search_empty_state_and_selected_value(self):
        response = self.client.get(self.url, {'q': 'missing'})
        self.assertContains(response, 'No compositions match these filters.')
        self.assertContains(response, 'value="missing"')

    def test_sorting_with_unknown_dates_last(self):
        for sort, expected in [
            ('premiered_date', [self.alpha, self.beta, self.undated, self.unknown]),
            ('alphabetical', [self.alpha, self.beta, self.undated, self.unknown]),
            ('year_composed', [self.beta, self.alpha, self.undated, self.unknown]),
        ]:
            with self.subTest(sort=sort):
                response = self.client.get(self.url, {'sort': sort})
                self.assertEqual(list(response.context['works']), expected)
                self.assertContains(response, f'value="{sort}" selected')
        response = self.client.get(self.url)
        self.assertEqual(list(response.context['works']),
                         [self.alpha, self.beta, self.undated, self.unknown])

    def test_multiple_years_and_published_year_choices(self):
        response = self.client.get(self.url, {'years': ['2020', '2025']})
        self.assertEqual(list(response.context['works']),
                         [self.alpha, self.beta, self.undated])
        self.assertEqual(response.context['filter_form'].fields['years'].choices,
                         [('2025', '2025'), ('2020', '2020')])
        self.assertNotContains(response, 'Hidden')
        self.assertContains(response, 'value="2020"')
        self.assertContains(response, 'checked')

    def test_filters_and_sort_combine(self):
        response = self.client.get(self.url, {
            'q': 'choir', 'category': 'Choral', 'duration': 'short',
            'years': ['2020'], 'sort': 'alphabetical',
        })
        self.assertEqual(list(response.context['works']), [self.alpha])
        response = self.client.get(self.url, {'q': 'choir', 'years': ['2025']})
        self.assertEqual(list(response.context['works']), [])

    def test_invalid_choices_and_overlong_search_show_errors(self):
        for data, field in [
            ({'sort': 'title; DROP TABLE'}, 'sort'),
            ({'years': ['2030']}, 'years'),
            ({'years': ['invalid']}, 'years'),
            ({'q': 'x' * 201}, 'q'),
        ]:
            with self.subTest(data=data):
                response = self.client.get(self.url, data)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context['filter_form'].errors)
                self.assertNotIn(self.draft, response.context['works'])

    def test_filtered_pages_remain_noindex_with_catalogue_canonical(self):
        response = self.client.get(self.url, {'q': 'alpha'})
        self.assertContains(response, 'noindex, follow')
        self.assertContains(response, '/compositions/"')

    def test_year_dropdown_is_compact_and_shows_selection_count(self):
        response = self.client.get(self.url)
        self.assertContains(response, '<details class="year-dropdown">')
        self.assertContains(response, '<span id="year-filter-summary">Any year</span>')
        response = self.client.get(self.url, {'years': ['2020', '2025']})
        self.assertContains(response, '<span id="year-filter-summary">2 selected</span>')
        self.assertContains(response, '<details class="year-dropdown">')

    def test_invalid_year_opens_dropdown_to_show_error(self):
        response = self.client.get(self.url, {'years': ['invalid']})
        self.assertContains(response, '<details class="year-dropdown" open>')
        self.assertContains(response, 'Select a valid choice.')

    def test_catalogue_loads_scroll_enhancement_and_select_wrappers(self):
        response = self.client.get(self.url)
        self.assertContains(response, '/static/js/catalogue.js')
        self.assertContains(response, 'class="select-control"', count=3)

    def test_search_and_submit_have_a_dedicated_bottom_row(self):
        response = self.client.get(self.url, {'q': 'alpha'})
        html = response.content.decode()
        row_start = html.index('<div class="filter-search-row">')
        form_end = html.index('</form>', row_start)
        bottom_row = html[row_start:form_end]
        self.assertIn('name="q"', bottom_row)
        self.assertIn('<button type="submit">Filter compositions</button>', bottom_row)
        self.assertNotIn('<select', bottom_row)
        self.assertNotIn('<details', bottom_row)
        self.assertNotIn('Clear filters', bottom_row)
        self.assertLess(html.index('Clear filters'), row_start)

    def test_controls_render_without_javascript(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'type="search"')
        self.assertContains(response, 'Sort by')
        self.assertContains(response, 'Year composed')
        self.assertContains(response, 'Alphabetical (A–Z)')
