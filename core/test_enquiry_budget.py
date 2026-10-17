from django.test import TestCase

from core.enquiries import (
    DAILY_WINDOW_LIMIT, DAILY_WINDOW_SECONDS,
    SHORT_WINDOW_LIMIT, SHORT_WINDOW_SECONDS, reserve_enquiry_attempt,
)
from core.models import EnquiryBudget


class EnquiryBudgetTests(TestCase):
    def test_short_window_resets_at_exact_boundary(self):
        now = 100000.0
        for _ in range(SHORT_WINDOW_LIMIT):
            self.assertTrue(reserve_enquiry_attempt(now))
        self.assertFalse(reserve_enquiry_attempt(now + SHORT_WINDOW_SECONDS - 0.01))
        self.assertTrue(reserve_enquiry_attempt(now + SHORT_WINDOW_SECONDS))
        budget = EnquiryBudget.objects.get()
        self.assertEqual(budget.short_count, 1)
        self.assertEqual(budget.daily_count, SHORT_WINDOW_LIMIT + 1)

    def test_daily_budget_survives_short_window_resets_until_midnight_utc(self):
        day_start = DAILY_WINDOW_SECONDS * 2
        for index in range(DAILY_WINDOW_LIMIT):
            # Spread attempts across short windows, but stay in one UTC day.
            self.assertTrue(reserve_enquiry_attempt(day_start + index * SHORT_WINDOW_SECONDS))
        before = EnquiryBudget.objects.get()
        self.assertFalse(reserve_enquiry_attempt(day_start + DAILY_WINDOW_SECONDS - 0.01))
        after = EnquiryBudget.objects.get()
        # Rejection must not partially reset or increment either counter.
        self.assertEqual(before.short_count, after.short_count)
        self.assertEqual(before.short_started_at, after.short_started_at)
        self.assertEqual(after.daily_count, DAILY_WINDOW_LIMIT)
        self.assertTrue(reserve_enquiry_attempt(day_start + DAILY_WINDOW_SECONDS))
        self.assertEqual(EnquiryBudget.objects.get().daily_count, 1)

    def test_midnight_does_not_bypass_short_window(self):
        midnight = DAILY_WINDOW_SECONDS * 2
        for _ in range(SHORT_WINDOW_LIMIT):
            self.assertTrue(reserve_enquiry_attempt(midnight - 1))
        self.assertFalse(reserve_enquiry_attempt(midnight))
        self.assertTrue(reserve_enquiry_attempt(midnight - 1 + SHORT_WINDOW_SECONDS))
        self.assertEqual(EnquiryBudget.objects.get().daily_count, 1)

    def test_reservation_is_one_conditional_database_update(self):
        with self.assertNumQueries(1):
            self.assertTrue(reserve_enquiry_attempt(100000.0))
        for _ in range(SHORT_WINDOW_LIMIT - 1):
            self.assertTrue(reserve_enquiry_attempt(100000.0))
        with self.assertNumQueries(1):
            self.assertFalse(reserve_enquiry_attempt(100000.0))

    def test_missing_budget_fails_closed(self):
        EnquiryBudget.objects.all().delete()
        self.assertFalse(reserve_enquiry_attempt(100000.0))
