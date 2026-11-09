"""Runtime settings merge and markup helpers."""
import unittest

from runtime_settings import buy_markup, merge_settings, sell_discount, sell_multiplier


class RuntimeSettingsTests(unittest.TestCase):
    def tearDown(self):
        import runtime_settings as rs

        rs._cache = None
        rs._cache_ts = 0.0
    def test_merge_defaults(self):
        s = merge_settings(None)
        self.assertEqual(s["buy_spread_auto_pct"], 20)
        self.assertEqual(s["buy_spread_auto_tiers"], [])
        self.assertEqual(s["review_bonus_text_rub"], 50)
        self.assertEqual(s["sell_pricing_mode"], "discount")
        self.assertEqual(s["sell_spread_pct"], 4.0)
        self.assertEqual(s["sell_markup_pct"], 4.0)
        self.assertEqual(s["min_withdraw_card_rub"], 20000)
        self.assertEqual(s["sell_snap_enabled"], False)
        self.assertEqual(s["sell_snap_cap_rub"], 1500.0)

    def test_merge_patch(self):
        s = merge_settings({"buy_spread_auto_pct": 21, "buy_spread_manual_pct": 22})
        self.assertEqual(s["buy_spread_auto_pct"], 21)
        self.assertEqual(s["buy_spread_manual_pct"], 22)

    def test_buy_markup_auto_vs_manual(self):
        import runtime_settings as rs

        rs._cache = {
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
        rs._cache_ts = __import__("time").time()
        self.assertAlmostEqual(buy_markup(manual=False), 1.21)
        self.assertAlmostEqual(buy_markup(manual=True), 1.22)
        self.assertAlmostEqual(sell_discount(), 0.95)
        self.assertAlmostEqual(sell_multiplier(), 0.95)

    def test_sell_multiplier_markup_mode(self):
        import runtime_settings as rs

        rs._cache = {
            "sell_spread_pct": 5,
            "sell_pricing_mode": "markup",
            "sell_markup_pct": 5,
        }
        rs._cache_ts = __import__("time").time()
        self.assertEqual(rs.sell_pricing_mode(), "markup")
        self.assertAlmostEqual(rs.sell_multiplier(), 1.05)
        self.assertAlmostEqual(rs.sell_discount(), 1.05)
        self.assertAlmostEqual(rs.sell_client_pct(), 5.0)


if __name__ == "__main__":
    unittest.main()
