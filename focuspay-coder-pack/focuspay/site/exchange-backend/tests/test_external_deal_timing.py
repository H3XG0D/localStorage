"""Константы тайминга внештатных сделок."""
import unittest

from external_deal_timing import (
    EXTERNAL_DEAL_CLIENT_PAY_TEXT,
    EXTERNAL_DEAL_DEADLINE_SEC,
    EXTERNAL_DEAL_WARNING_ELAPSED_SEC,
    EXTERNAL_DEAL_WARNING_REMAINING_SEC,
    EXTERNAL_DEAL_WARNING_TEXT,
)


class ExternalDealTimingTests(unittest.TestCase):
    def test_deadline_sec(self):
        self.assertEqual(EXTERNAL_DEAL_DEADLINE_SEC, 1350)

    def test_warning_elapsed_sec(self):
        self.assertEqual(EXTERNAL_DEAL_WARNING_ELAPSED_SEC, 900)

    def test_warning_remaining_sec(self):
        self.assertEqual(EXTERNAL_DEAL_WARNING_REMAINING_SEC, 450)

    def test_deadline_equals_elapsed_plus_remaining(self):
        self.assertEqual(
            EXTERNAL_DEAL_DEADLINE_SEC,
            EXTERNAL_DEAL_WARNING_ELAPSED_SEC + EXTERNAL_DEAL_WARNING_REMAINING_SEC,
        )

    def test_client_pay_text(self):
        self.assertIn("20 минут", EXTERNAL_DEAL_CLIENT_PAY_TEXT)
        self.assertIn("одним платежом", EXTERNAL_DEAL_CLIENT_PAY_TEXT)

    def test_warning_text(self):
        self.assertIn("7.5", EXTERNAL_DEAL_WARNING_TEXT)


if __name__ == "__main__":
    unittest.main()
