"""Immutable order economics snapshots survive later tariff changes."""
import unittest
from unittest.mock import patch

from economics_snapshot import (
    FORMULA_VERSION,
    FORMULA_VERSION_V2,
    LEGACY_LOCKED_VERSION,
    build_economics_snapshot,
    order_economics,
    snapshot_economics,
)


class EconomicsSnapshotTests(unittest.TestCase):
    def test_buy_snapshot_preserves_quote_time_margin_and_card_fee(self):
        with patch("economics_snapshot.buy_markup", return_value=1.2), patch(
            "economics_snapshot.card_fee_pct", return_value=0.1
        ):
            snapshot = build_economics_snapshot(
                "buy", "usdt", 1200, 10, 120, cashback_applied_rub=50
            )

        self.assertEqual(snapshot["formula_version"], FORMULA_VERSION)
        self.assertEqual(snapshot["market_rate"], 100.0)
        self.assertEqual(snapshot["merchant_fee_rub"], 120.0)
        self.assertEqual(snapshot["service_profit_rub"], 80.0)

        with patch("economics_snapshot.buy_markup", return_value=1.5), patch(
            "economics_snapshot.card_fee_pct", return_value=0.3
        ):
            economics = order_economics({"economics_snapshot": snapshot}, clamp=False)

        self.assertEqual(economics["gross_margin_rub"], 250.0)
        self.assertEqual(economics["merchant_fee_rub"], 120.0)
        self.assertEqual(economics["service_profit_rub"], 80.0)

    def test_sell_snapshot_preserves_quote_time_discount_and_factor(self):
        with patch("economics_snapshot.sell_discount", return_value=0.95), patch(
            "economics_snapshot.sell_profit_factor", return_value=0.75
        ), patch("economics_snapshot.sell_pricing_mode", return_value="discount"):
            snapshot = build_economics_snapshot("sell", "usdt", 950, 10, 0)

        self.assertEqual(snapshot["formula_version"], FORMULA_VERSION)
        self.assertAlmostEqual(snapshot["gross_margin_rub"], 50.0)
        self.assertAlmostEqual(snapshot["service_profit_rub"], 37.5)

        with patch("economics_snapshot.sell_discount", return_value=0.8), patch(
            "economics_snapshot.sell_profit_factor", return_value=0.2
        ):
            economics = order_economics({"economics_snapshot": snapshot}, clamp=False)

        self.assertAlmostEqual(economics["gross_margin_rub"], 50.0)
        self.assertAlmostEqual(economics["service_profit_rub"], 37.5)

    def test_sell_markup_snapshot_v2_skips_profit_factor(self):
        with patch("economics_snapshot.sell_discount", return_value=1.05), patch(
            "economics_snapshot.sell_pricing_mode", return_value="markup"
        ), patch("economics_snapshot.sell_profit_factor", return_value=0.75), patch(
            "economics_snapshot.sell_client_pct", return_value=5.0
        ):
            snapshot = build_economics_snapshot("sell", "usdt", 1050, 10, 0)

        self.assertEqual(snapshot["formula_version"], FORMULA_VERSION_V2)
        self.assertAlmostEqual(snapshot["gross_margin_rub"], -50.0)
        self.assertAlmostEqual(snapshot["service_profit_rub"], -50.0)
        self.assertEqual(snapshot["sell_profit_factor"], 1.0)

        with patch("economics_snapshot.sell_discount", return_value=0.95), patch(
            "economics_snapshot.sell_profit_factor", return_value=0.75
        ):
            economics = order_economics({"economics_snapshot": snapshot}, clamp=False)

        self.assertAlmostEqual(economics["gross_margin_rub"], -50.0)
        self.assertAlmostEqual(economics["service_profit_rub"], -50.0)

    def test_buy_snapshot_survives_later_tier_change(self):
        snapshot = build_economics_snapshot(
            "buy",
            "usdt",
            1200,
            10,
            120,
            buy_markup_override=1.2,
            card_fee=0.1,
        )
        with patch("economics_snapshot.buy_markup", return_value=1.25), patch(
            "economics_snapshot.card_fee_pct", return_value=0.3
        ):
            economics = order_economics({"economics_snapshot": snapshot}, clamp=False)
        self.assertEqual(snapshot["buy_markup"], 1.2)
        self.assertEqual(economics["service_profit_rub"], 80.0)

    def test_manual_buy_snapshot_uses_individual_spread(self):
        with patch("economics_snapshot.buy_markup", return_value=1.15), patch(
            "economics_snapshot.card_fee_pct", return_value=0.1
        ):
            snapshot = build_economics_snapshot(
                "buy",
                "usdt",
                1200,
                10,
                120,
                card_fee=0.1,
                manual_buy=True,
                buy_markup_override=1.2,
            )

        self.assertEqual(snapshot["buy_markup"], 1.2)
        self.assertEqual(snapshot["market_rate"], 100.0)
        self.assertEqual(snapshot["service_profit_rub"], 80.0)

    def test_negative_snapshot_profit_is_available_for_pnl_but_not_accruals(self):
        snapshot = {
            "formula_version": FORMULA_VERSION,
            "gross_margin_rub": -10.0,
            "merchant_fee_rub": 0.0,
            "service_profit_rub": -10.0,
        }

        self.assertEqual(snapshot_economics(snapshot)["service_profit_rub"], 0.0)
        self.assertEqual(snapshot_economics(snapshot, clamp=False)["service_profit_rub"], -10.0)

    def test_legacy_snapshot_is_read_as_immutable_economics(self):
        snapshot = {
            "formula_version": LEGACY_LOCKED_VERSION,
            "gross_margin_rub": 100.0,
            "merchant_fee_rub": 20.0,
            "service_profit_rub": 80.0,
            "locked_at": "2026-08-22T00:00:00+00:00",
        }

        self.assertEqual(order_economics({"economics_snapshot": snapshot}), {
            "gross_margin_rub": 100.0,
            "merchant_fee_rub": 20.0,
            "service_profit_rub": 80.0,
        })


    def test_buy_snapshot_subtracts_triangle_subsidy(self):
        snapshot = build_economics_snapshot(
            "buy",
            "usdt",
            900,
            720,
            1.25,
            card_fee=0,
            buy_markup_override=1.25,
            triangle_subsidy_rub=9,
        )
        self.assertEqual(snapshot["triangle_subsidy_rub"], 9.0)
        self.assertEqual(snapshot["service_profit_rub"], 171.0)
        self.assertEqual(
            order_economics({"economics_snapshot": snapshot}, clamp=False)["service_profit_rub"],
            171.0,
        )


if __name__ == "__main__":
    unittest.main()
