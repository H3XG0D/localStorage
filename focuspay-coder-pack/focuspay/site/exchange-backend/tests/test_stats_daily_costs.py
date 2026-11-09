"""Daily cost overhead includes cashback accruals and USDT."""
import unittest

from stats_daily_costs import daily_cost_overhead


class DailyCostOverheadTests(unittest.TestCase):
    def test_includes_cashback_and_usdt(self):
        overhead = daily_cost_overhead(
            {
                "cost_cashback": 100.0,
                "cost_referral": 50.0,
                "cost_partner": 0.0,
                "cost_review": 25.0,
                "cost_swap": 10.0,
                "cost_payroll": 200.0,
                "cost_admin": 300.0,
                "cost_usdt": 1500.0,
            }
        )
        self.assertEqual(overhead, 2185.0)

    def test_includes_focus_lucky(self):
        overhead = daily_cost_overhead(
            {
                "cost_cashback": 0.0,
                "cost_focus_lucky": 14500.0,
            }
        )
        self.assertEqual(overhead, 14500.0)

    def test_excludes_card_from_overhead(self):
        overhead = daily_cost_overhead({"cost_card": 500.0, "cost_cashback": 0.0})
        self.assertEqual(overhead, 0.0)


if __name__ == "__main__":
    unittest.main()
