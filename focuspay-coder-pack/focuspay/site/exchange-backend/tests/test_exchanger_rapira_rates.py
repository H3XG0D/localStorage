"""Freelancer cabinet uses raw Rapira — no USDT pad, no CoinGecko fill."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

try:
    from routers import public as pub
except ImportError:  # local machine without backend venv
    pub = None


@unittest.skipIf(pub is None, "exchange-backend deps missing")
class ExchangerRapiraRatesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        pub._cache.clear()
        pub._LAST_SOURCE = "none"

    def tearDown(self):
        pub._cache.clear()
        pub._LAST_SOURCE = "none"

    def test_parse_rapira_body_without_coingecko(self):
        body = {
            "data": [
                {"symbol": "USDT/RUB", "close": 91.81},
                {"symbol": "BTC/USDT", "close": 0.000012},
            ]
        }
        market = pub._parse_rapira_body(body)
        self.assertAlmostEqual(market["usdt"], 91.81)
        self.assertAlmostEqual(market["btc"], 0.000012 * 91.81)
        self.assertNotIn("ltc", market)
        self.assertNotIn("trx", market)

    async def test_get_rates_cached_still_pads_and_fills(self):
        live = {"usdt": 85.6}
        filled = {"usdt": 85.6, "btc": 1.0, "ltc": 2.0, "trx": 3.0}
        with patch.object(pub, "_ensure_raw_rapira", new=AsyncMock(return_value=live)), patch.object(
            pub, "_fill_missing_from_coingecko", new=AsyncMock(return_value=filled)
        ):
            served = await pub.get_rates_cached()
        self.assertAlmostEqual(served["usdt"], 87.6)
        self.assertIn("btc", served)

    async def test_get_exchanger_rates_cached_no_pad(self):
        live = {"usdt": 85.6, "btc": 1.0, "ltc": 2.0, "trx": 3.0}
        with patch.object(pub, "_cached_rates", return_value=None), patch.object(
            pub, "_load_snapshot_rates", return_value=None
        ), patch.object(pub, "_fetch_rapira_only", new=AsyncMock(return_value=live)):
            served = await pub.get_exchanger_rates_cached()
        self.assertAlmostEqual(served["usdt"], 85.6)
        self.assertAlmostEqual(pub._cache["usdt"], 85.6)

    async def test_exchanger_rates_skip_coingecko_when_btc_missing(self):
        live = {"usdt": 85.6}
        with patch.object(pub, "_cached_rates", return_value=live):
            served = await pub.get_exchanger_rates_cached()
        self.assertAlmostEqual(served["usdt"], 85.6)
        self.assertNotIn("btc", served)


if __name__ == "__main__":
    unittest.main()
