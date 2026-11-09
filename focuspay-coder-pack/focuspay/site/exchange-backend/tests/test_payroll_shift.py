"""Зарплата оператора: засчёт по payout_confirmed_at."""
import unittest
from datetime import datetime, timezone

from payroll_base import order_completed_in_shift, operator_order_completed_at


class PayrollShiftTests(unittest.TestCase):
    def test_uses_payout_confirmed_at_not_created(self):
        shift_start = datetime(2026, 6, 5, 2, 8, 27, tzinfo=timezone.utc)
        shift_end = None
        order = {
            "created_at": datetime(2026, 6, 4, 12, 18, tzinfo=timezone.utc),
            "payout_confirmed_at": datetime(2026, 6, 5, 2, 9, 21, tzinfo=timezone.utc),
        }
        self.assertEqual(
            operator_order_completed_at(order),
            order["payout_confirmed_at"],
        )
        self.assertTrue(order_completed_in_shift(order, shift_start, shift_end))

    def test_created_before_shift_confirmed_inside_counts(self):
        shift_start = datetime(2026, 6, 2, 20, 46, tzinfo=timezone.utc)
        shift_end = datetime(2026, 6, 3, 8, 51, tzinfo=timezone.utc)
        order = {
            "created_at": datetime(2026, 6, 2, 20, 39, tzinfo=timezone.utc),
            "payout_confirmed_at": datetime(2026, 6, 2, 20, 47, tzinfo=timezone.utc),
        }
        self.assertTrue(order_completed_in_shift(order, shift_start, shift_end))

    def test_confirmed_outside_shift_excluded(self):
        shift_start = datetime(2026, 6, 2, 20, 46, tzinfo=timezone.utc)
        shift_end = datetime(2026, 6, 3, 8, 51, tzinfo=timezone.utc)
        order = {
            "created_at": datetime(2026, 6, 3, 3, 16, tzinfo=timezone.utc),
            "payout_confirmed_at": datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc),
        }
        self.assertFalse(order_completed_in_shift(order, shift_start, shift_end))


if __name__ == "__main__":
    unittest.main()
