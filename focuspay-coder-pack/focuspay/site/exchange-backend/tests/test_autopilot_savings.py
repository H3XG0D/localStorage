"""Плюс автопилота: оператор 30→5/10, рефералы до 20%, кешбэк не растёт."""
from __future__ import annotations

import unittest

from autopilot_savings import assemble_savings


def _report(deals):
    return assemble_savings(
        deals,
        pool_percent=30,
        presence_percent=5,
        manual_percent=10,
        user_referral_percent=5,
    )


class AutopilotSavingsTests(unittest.TestCase):
    def test_auto_order_keeps_twenty_five_points(self):
        report = _report([{"profit": 1000, "lane": "auto"}])
        self.assertEqual(report["operator_save_auto_rub"], 250)
        self.assertEqual(report["operator_save_manual_rub"], 0)
        self.assertEqual(report["net_rub"], 250)
        self.assertEqual(report["cashback_extra_rub"], 0)

    def test_manual_order_keeps_twenty_points(self):
        report = _report([{"profit": 1000, "lane": "manual"}])
        self.assertEqual(report["operator_save_manual_rub"], 200)
        self.assertEqual(report["auto_deals"], 0)
        self.assertEqual(report["manual_deals"], 1)

    def test_partner_at_10_percent_is_lifted_to_20(self):
        report = _report(
            [{"profit": 1000, "lane": "auto", "partner_percent": 10, "user_referral_percent": None}]
        )
        self.assertEqual(report["partner_extra_rub"], 100)
        self.assertEqual(report["net_rub"], 150)
        self.assertEqual(report["cashback_extra_rub"], 0)

    def test_partner_above_20_is_not_raised(self):
        report = _report(
            [{"profit": 1000, "lane": "auto", "partner_percent": 40, "user_referral_percent": None}]
        )
        self.assertEqual(report["partner_extra_rub"], 0)
        self.assertEqual(report["partner_above_cap_rub"], 400)
        self.assertEqual(report["partner_above_cap_deals"], 1)
        self.assertEqual(report["net_rub"], 250)
        vip = next(line for line in report["lines"] if line["key"] == "partner_vip")
        self.assertEqual(vip["amount_rub"], 0)
        self.assertIn("не поднимаем", vip["hint"])

    def test_user_referral_below_20_is_lifted(self):
        report = _report(
            [{"profit": 1000, "lane": "manual", "user_referral_percent": 5, "partner_percent": None}]
        )
        self.assertEqual(report["user_referral_extra_rub"], 150)
        self.assertEqual(report["operator_save_rub"], 200)
        self.assertEqual(report["net_rub"], 50)

    def test_user_referral_above_20_stays(self):
        report = _report(
            [{"profit": 1000, "lane": "manual", "user_referral_percent": 25}]
        )
        self.assertEqual(report["user_referral_extra_rub"], 0)
        self.assertEqual(report["net_rub"], 200)

    def test_zero_profit_does_not_add_plus(self):
        report = _report([{"profit": 0, "lane": "auto", "partner_percent": 10}])
        self.assertEqual(report["deals"], 0)
        self.assertEqual(report["net_rub"], 0)
        self.assertEqual(report["cashback_extra_rub"], 0)

    def test_cashback_line_is_zero(self):
        report = _report([{"profit": 1000, "lane": "auto"}])
        cash = next(line for line in report["lines"] if line["key"] == "cashback")
        self.assertEqual(cash["amount_rub"], 0)
        self.assertIn("не увеличиваем", cash["hint"])
        self.assertIn("кешбэк не поднимаем", report["line"])


if __name__ == "__main__":
    unittest.main()
