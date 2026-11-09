"""SELL CoinGecko market + markup pricing mode."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from commission import commission_percent
from routers.public import merge_sell_market
from service_profit import order_service_profit


class MergeSellMarketTests(unittest.TestCase):
    def test_prefers_coingecko(self):
        out = merge_sell_market({"usdt": 110.0, "btc": 1.0}, {"usdt": 100.0, "btc": 2.0, "ltc": 3.0})
        self.assertEqual(out["usdt"], 110.0)
        self.assertEqual(out["btc"], 1.0)
        self.assertEqual(out["ltc"], 3.0)

    def test_rapira_when_coingecko_empty(self):
        out = merge_sell_market({}, {"usdt": 100.0})
        self.assertEqual(out["usdt"], 100.0)


class SellMarketResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_sell_market_rates_prefers_coingecko(self):
        from routers import public as pub

        need = {"usdt": 110.0, "btc": 1.0, "ltc": 2.0, "trx": 3.0}
        rapira = {"usdt": 100.0, "btc": 9.0, "ltc": 8.0, "trx": 7.0}
        with patch.object(pub, "get_need_rates_cached", new=AsyncMock(return_value=need)), patch.object(
            pub, "_ensure_raw_rapira", new=AsyncMock(return_value=rapira)
        ):
            out = await pub.get_sell_market_rates()
        self.assertEqual(out["usdt"], 108.0)
        self.assertEqual(out["btc"], 1.0)

    async def test_get_sell_market_rates_falls_back_to_rapira(self):
        from routers import public as pub

        rapira = {"usdt": 100.0, "btc": 9.0, "ltc": 8.0, "trx": 7.0}
        with patch.object(pub, "get_need_rates_cached", new=AsyncMock(return_value={})), patch.object(
            pub, "_ensure_raw_rapira", new=AsyncMock(return_value=rapira)
        ):
            out = await pub.get_sell_market_rates()
        self.assertEqual(out["usdt"], 98.0)
        self.assertEqual(out["btc"], 9.0)


class CommissionDisplayTests(unittest.TestCase):
    def tearDown(self):
        import runtime_settings as rs

        rs._cache = None
        rs._cache_ts = 0.0

    def test_markup_commission_is_positive(self):
        import runtime_settings as rs

        rs._cache = {
            "buy_spread_auto_pct": 20,
            "buy_spread_manual_pct": 20,
            "sell_spread_pct": 5,
            "sell_pricing_mode": "markup",
            "sell_markup_pct": 5,
        }
        rs._cache_ts = __import__("time").time()
        self.assertEqual(commission_percent("usdt", "sell"), 5.0)
        from payment_methods_display import public_tariffs_data

        tariffs = public_tariffs_data()
        sell_qr = next(c for c in tariffs["commissions"] if c["id"] == "sell_qr")
        self.assertEqual(sell_qr["pct"], 5.0)
        self.assertEqual(sell_qr["mode"], "markup")
        self.assertIn("доплачиваем 5% за вашу крипту", sell_qr["note"])
        buy = next(c for c in tariffs["commissions"] if c["id"] == "buy_crypto")
        self.assertEqual(buy["pct"], 20)


class MarkupProfitTests(unittest.TestCase):
    def test_markup_skips_profit_factor(self):
        with patch("service_profit.sell_discount", return_value=1.05), patch(
            "service_profit.sell_pricing_mode", return_value="markup"
        ), patch("service_profit.sell_profit_factor", return_value=0.75):
            net = order_service_profit("sell", "usdt", 1050, clamp=False)
        self.assertAlmostEqual(net, -50.0)

    def test_markup_clamp_hides_loss(self):
        with patch("service_profit.sell_discount", return_value=1.05), patch(
            "service_profit.sell_pricing_mode", return_value="markup"
        ):
            self.assertEqual(order_service_profit("sell", "usdt", 1050, clamp=True), 0.0)


class AdminPreviewTests(unittest.TestCase):
    def test_preview_markup_multiplier(self):
        from routers.admin_pricing import _preview

        preview = _preview(
            {
                "buy_spread_auto_pct": 20,
                "buy_spread_manual_pct": 22,
                "sell_spread_pct": 5,
                "sell_pricing_mode": "markup",
                "sell_markup_pct": 5,
            }
        )
        self.assertIn("1.05", preview["sell"])
        self.assertIn("наценка", preview["sell"])


if __name__ == "__main__":
    unittest.main()
