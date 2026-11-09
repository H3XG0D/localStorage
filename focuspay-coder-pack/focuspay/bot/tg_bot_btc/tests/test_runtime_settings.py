"""Bot runtime settings."""
import unittest
import time

from services import runtime_settings


class BotRuntimeSettingsTests(unittest.TestCase):
    def tearDown(self):
        runtime_settings._cache = None
        runtime_settings._cache_ts = 0.0

    def test_buy_markup_manual_diff(self):
        runtime_settings._cache = {
            "buy_spread_auto_pct": 21,
            "buy_spread_manual_pct": 22,
            "sell_spread_pct": 5,
            "card_fee_auto_pct": 12,
            "card_fee_manual_pct": 14,
            "sell_profit_factor_pct": 75,
            "user_cashback_base_pct": 5,
            "user_cashback_tier_step_pct": 2,
            "user_cashback_tier_every_n": 5,
            "user_cashback_max_pct": 15,
            "user_referral_pct": 5,
            "review_bonus_text_rub": 50,
            "review_bonus_photo_rub": 100,
        }
        runtime_settings._cache_ts = time.time()
        self.assertAlmostEqual(runtime_settings.buy_markup(manual=False), 1.21)
        self.assertAlmostEqual(runtime_settings.buy_markup(manual=True), 1.22)

    def test_merge_defaults_discount(self):
        s = runtime_settings.merge_settings(None)
        self.assertEqual(s["sell_pricing_mode"], "discount")
        self.assertEqual(s["sell_markup_pct"], 4.0)
        self.assertEqual(s["buy_spread_auto_tiers"], [])

    def test_sell_multiplier_markup_mode(self):
        runtime_settings._cache = {
            "sell_spread_pct": 5,
            "sell_pricing_mode": "markup",
            "sell_markup_pct": 5,
        }
        runtime_settings._cache_ts = time.time()
        self.assertEqual(runtime_settings.sell_pricing_mode(), "markup")
        self.assertAlmostEqual(runtime_settings.sell_multiplier(), 1.05)
        self.assertAlmostEqual(runtime_settings.sell_discount(), 1.05)
        self.assertEqual(runtime_settings.sell_client_pct(), 5.0)


if __name__ == "__main__":
    unittest.main()
