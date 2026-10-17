from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.db import close_old_connections
from django.test import RequestFactory, TransactionTestCase, override_settings

from core.enquiries import DAILY_WINDOW_LIMIT, SHORT_WINDOW_LIMIT, deliver_enquiry
from core.forms import EnquiryForm
from core.models import EnquiryBudget
from core.test_mail_backend import ACCEPTED_MAILERS


@override_settings(
    DEBUG=False, MAILERS=ACCEPTED_MAILERS,
    DEFAULT_FROM_EMAIL='composer@example.com', ENQUIRY_EMAIL='enquiries@example.com',
)
class ConcurrentEnquiryBudgetTests(TransactionTestCase):
    def setUp(self):
        verification = patch('core.enquiries.verify_turnstile', return_value=True)
        verification.start()
        self.addCleanup(verification.stop)
        # TransactionTestCase flushes data between tests, including migration data.
        EnquiryBudget.objects.update_or_create(pk=1, defaults={
            'short_started_at': 100000.0, 'short_count': 0,
            'daily_started_at': 100000.0, 'daily_count': 0,
        })

    def deliver(self):
        request = RequestFactory().post('/contact/')
        request.session = {}
        return deliver_enquiry(request, EnquiryForm({
            'name': 'Visitor', 'email': 'visitor@example.com',
        }))

    def test_concurrent_attempts_cannot_overspend_either_budget(self):
        scenarios = [
            (100000.0, SHORT_WINDOW_LIMIT - 1, 100000.0, 0, 1),
            (100000.0, 0, 100000.0, DAILY_WINDOW_LIMIT - 1, 1),
            (0.0, SHORT_WINDOW_LIMIT, 0.0, DAILY_WINDOW_LIMIT, SHORT_WINDOW_LIMIT),
        ]
        for short_start, short_count, daily_start, daily_count, capacity in scenarios:
            with self.subTest(capacity=capacity, daily_count=daily_count):
                EnquiryBudget.objects.filter(pk=1).update(
                    short_started_at=short_start, short_count=short_count,
                    daily_started_at=daily_start, daily_count=daily_count,
                )
                barrier = Barrier(8)

                def attempt():
                    close_old_connections()
                    try:
                        barrier.wait(timeout=10)
                        return self.deliver()
                    finally:
                        close_old_connections()

                with (
                    patch('core.enquiries.time', return_value=100000.0),
                    patch('core.enquiries.EmailMessage.send', return_value=1) as send,
                    patch('core.enquiries.logger'),
                    ThreadPoolExecutor(max_workers=8) as pool,
                ):
                    results = list(pool.map(lambda _: attempt(), range(8)))
                # SQLite may reject contenders with a lock error; those fail closed.
                self.assertGreaterEqual(sum(results), 1)
                self.assertLessEqual(sum(results), capacity)
                self.assertEqual(send.call_count, sum(results))
                budget = EnquiryBudget.objects.get()
                self.assertLessEqual(budget.short_count, SHORT_WINDOW_LIMIT)
                self.assertLessEqual(budget.daily_count, DAILY_WINDOW_LIMIT)

    def test_reservation_is_committed_before_smtp_and_survives_failure(self):
        def read_from_independent_connection():
            close_old_connections()
            try:
                budget = EnquiryBudget.objects.get()
                return budget.short_count, budget.daily_count
            finally:
                close_old_connections()

        observed = []

        def fail_send(**kwargs):
            with ThreadPoolExecutor(max_workers=1) as pool:
                observed.append(pool.submit(read_from_independent_connection).result(timeout=10))
            raise RuntimeError('SMTP unavailable')

        with (
            patch('core.enquiries.time', return_value=100000.0),
            patch('core.enquiries.EmailMessage.send', side_effect=fail_send),
            self.assertLogs('core.enquiries', level='ERROR'),
        ):
            self.assertFalse(self.deliver())
        self.assertEqual(observed, [(1, 1)])
        budget = EnquiryBudget.objects.get()
        self.assertEqual((budget.short_count, budget.daily_count), (1, 1))
