"""Amount-based buy spread grid."""
from __future__ import annotations

import unittest

from buy_spread_tiers import (
    buy_spread_range_label,
    parse_buy_spread_auto_tiers,
    parse_buy_spread_auto_tiers_patch,
    resolve_buy_spread_pct,
)


SAMPLE = [
    {"min_amount_rub": 0, "pct": 25},
    {"min_amount_rub": 1000, "pct": 23},
    {"min_amount_rub": 2000, "pct": 20},
]


class ParseBuySpreadTiersTests(unittest.TestCase):
    def test_empty_is_ok(self):
        self.assertEqual(parse_buy_spread_auto_tiers(None), ())
        self.assertEqual(parse_buy_spread_auto_tiers([]), ())

    def test_rejects_missing_zero(self):
        with self.assertRaises(ValueError):
            parse_buy_spread_auto_tiers([{"min_amount_rub": 1000, "pct": 23}])

    def test_rejects_duplicate_and_gap_overlap_mins(self):
        with self.assertRaises(ValueError):
            parse_buy_spread_auto_tiers(
                [{"min_amount_rub": 0, "pct": 25}, {"min_amount_rub": 0, "pct": 23}]
            )

    def test_rejects_pct_out_of_range(self):
        with self.assertRaises(ValueError):
            parse_buy_spread_auto_tiers([{"min_amount_rub": 0, "pct": 51}])

    def test_non_strict_junk_is_empty(self):
        self.assertEqual(parse_buy_spread_auto_tiers("nope", strict=False), ())
        self.assertEqual(parse_buy_spread_auto_tiers({"pct": 1}, strict=False), ())

    def test_patch_rejects_empty_and_missing_zero(self):
        with self.assertRaises(ValueError) as ctx:
            parse_buy_spread_auto_tiers_patch([])
        self.assertIn("empty", str(ctx.exception))
        with self.assertRaises(ValueError):
            parse_buy_spread_auto_tiers_patch([{"min_amount_rub": 1000, "pct": 23}])
        parsed = parse_buy_spread_auto_tiers_patch(SAMPLE)
        self.assertEqual(parsed[0].pct, 25)


class ResolveBuySpreadPctTests(unittest.TestCase):
    def setUp(self):
        self.tiers = parse_buy_spread_auto_tiers(SAMPLE)

    def test_boundaries(self):
        self.assertEqual(resolve_buy_spread_pct(self.tiers, 0, fallback_pct=20), 25)
        self.assertEqual(resolve_buy_spread_pct(self.tiers, 999, fallback_pct=20), 25)
        self.assertEqual(resolve_buy_spread_pct(self.tiers, 1000, fallback_pct=20), 23)
        self.assertEqual(resolve_buy_spread_pct(self.tiers, 1999.99, fallback_pct=20), 23)
        self.assertEqual(resolve_buy_spread_pct(self.tiers, 2000, fallback_pct=20), 20)
        self.assertEqual(resolve_buy_spread_pct(self.tiers, 999999, fallback_pct=20), 20)

    def test_empty_or_no_amount_uses_fallback(self):
        self.assertEqual(resolve_buy_spread_pct((), 500, fallback_pct=20), 20)
        self.assertEqual(resolve_buy_spread_pct(self.tiers, None, fallback_pct=20), 20)

    def test_range_label(self):
        self.assertEqual(buy_spread_range_label(self.tiers, fallback_pct=20), "20–25%")
        self.assertEqual(buy_spread_range_label((), fallback_pct=20), "20%")


class RuntimeBuyMarkupTiersTests(unittest.TestCase):
    def tearDown(self):
        import runtime_settings as rs

        rs._cache = None
        rs._cache_ts = 0.0

    def test_buy_markup_picks_tier(self):
        import time

        import runtime_settings as rs

        rs._cache = {
            "buy_spread_auto_pct": 25,
            "buy_spread_manual_pct": 22,
            "buy_spread_auto_tiers": SAMPLE,
        }
        rs._cache_ts = time.time()
        self.assertAlmostEqual(rs.buy_markup(manual=False, amount_rub=999), 1.25)
        self.assertAlmostEqual(rs.buy_markup(manual=False, amount_rub=1000), 1.23)
        self.assertAlmostEqual(rs.buy_markup(manual=False), 1.25)
        self.assertAlmostEqual(rs.buy_markup(manual=True, amount_rub=1000), 1.22)

    def test_commission_label_range_then_selected(self):
        import time

        import runtime_settings as rs
        from commission import commission_label

        rs._cache = {
            "buy_spread_auto_pct": 25,
            "buy_spread_manual_pct": 22,
            "buy_spread_auto_tiers": SAMPLE,
        }
        rs._cache_ts = time.time()
        self.assertEqual(commission_label("usdt", "buy"), "20–25%")
        self.assertEqual(commission_label("usdt", "buy", amount_rub=999), "25%")
        self.assertEqual(commission_label("usdt", "buy", amount_rub=1000), "23%")

    def test_patch_model_accepts_grid(self):
        from pydantic import ValidationError
        from routers.admin_pricing import PricingSettingsPatch

        body = PricingSettingsPatch(
            buy_spread_auto_tiers=[
                {"min_amount_rub": 0, "pct": 25},
                {"min_amount_rub": 1000, "pct": 23},
            ]
        )
        dumped = body.model_dump(exclude_unset=True)["buy_spread_auto_tiers"]
        parse_buy_spread_auto_tiers(dumped, strict=True)
        with self.assertRaises(ValidationError):
            PricingSettingsPatch(buy_spread_auto_tiers=[{"min_amount_rub": 0, "pct": 51}])

    def test_merge_defaults_include_empty_grid(self):
        from runtime_settings import merge_settings

        s = merge_settings(None)
        self.assertEqual(s["buy_spread_auto_tiers"], [])

    def test_public_tariffs_include_grid(self):
        import time

        import runtime_settings as rs
        from payment_methods_display import public_tariffs_data

        rs._cache = {
            "buy_spread_auto_pct": 99,
            "buy_spread_manual_pct": 20,
            "buy_spread_auto_tiers": SAMPLE,
            "sell_spread_pct": 5,
            "sell_pricing_mode": "markup",
            "sell_markup_pct": 5,
        }
        rs._cache_ts = time.time()
        data = public_tariffs_data()
        buy = next(c for c in data["commissions"] if c["id"] == "buy_crypto")
        self.assertEqual(buy["pct"], 25)
        self.assertEqual(buy["pct_from"], 20)
        self.assertEqual(buy["pct_to"], 25)
        self.assertEqual(data["buy_spread_auto_tiers"][0]["pct"], 25)
        self.assertIn("–", buy["note"])


if __name__ == "__main__":
    unittest.main()
