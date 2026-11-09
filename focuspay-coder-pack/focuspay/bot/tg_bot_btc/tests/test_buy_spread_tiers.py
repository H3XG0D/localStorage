"""Amount-based buy spread grid (bot copy)."""
from __future__ import annotations

import time
import unittest

from services.buy_spread_tiers import (
    parse_buy_spread_auto_tiers,
    parse_buy_spread_auto_tiers_patch,
    resolve_buy_spread_pct,
)
from services import runtime_settings


SAMPLE = [
    {"min_amount_rub": 0, "pct": 25},
    {"min_amount_rub": 1000, "pct": 23},
]


class BotBuySpreadTiersTests(unittest.TestCase):
    def tearDown(self):
        runtime_settings._cache = None
        runtime_settings._cache_ts = 0.0

    def test_boundaries(self):
        tiers = parse_buy_spread_auto_tiers(SAMPLE)
        self.assertEqual(resolve_buy_spread_pct(tiers, 999, fallback_pct=20), 25)
        self.assertEqual(resolve_buy_spread_pct(tiers, 1000, fallback_pct=20), 23)

    def test_buy_markup_uses_amount(self):
        runtime_settings._cache = {
            "buy_spread_auto_pct": 25,
            "buy_spread_manual_pct": 18,
            "buy_spread_auto_tiers": SAMPLE,
        }
        runtime_settings._cache_ts = time.time()
        self.assertAlmostEqual(runtime_settings.buy_markup(manual=False, amount_rub=500), 1.25)
        self.assertAlmostEqual(runtime_settings.buy_markup(manual=False, amount_rub=1500), 1.23)

    def test_patch_rejects_empty(self):
        with self.assertRaises(ValueError):
            parse_buy_spread_auto_tiers_patch([])

    def test_commission_label_is_range(self):
        from services.commission import commission_label

        runtime_settings._cache = {
            "buy_spread_auto_pct": 25,
            "buy_spread_manual_pct": 18,
            "buy_spread_auto_tiers": SAMPLE,
        }
        runtime_settings._cache_ts = time.time()
        self.assertEqual(commission_label("usdt", "buy"), "23–25%")
        self.assertEqual(commission_label("usdt", "buy", amount_rub=1500), "23%")

    def test_rates_message_buy_line_uses_range(self):
        from services.payment_methods_display import public_tariffs_data

        runtime_settings._cache = {
            "buy_spread_auto_pct": 99,
            "buy_spread_manual_pct": 18,
            "buy_spread_auto_tiers": SAMPLE,
            "sell_spread_pct": 5,
            "sell_pricing_mode": "markup",
            "sell_markup_pct": 5,
        }
        runtime_settings._cache_ts = time.time()
        data = public_tariffs_data()
        buy = next(c for c in data["commissions"] if c["id"] == "buy_crypto")
        self.assertEqual(buy["pct"], 25)
        self.assertEqual(buy["note"], "23–25%")


if __name__ == "__main__":
    unittest.main()
