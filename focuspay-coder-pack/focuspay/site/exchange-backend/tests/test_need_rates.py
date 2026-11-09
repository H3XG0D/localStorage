"""CoinGecko RUB need-rates for BUY quotes."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

try:
    from routers import public as pub
except ImportError:
    pub = None


@unittest.skipIf(pub is None, "exchange-backend deps missing")
class CoingeckoRubNeedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        pub._need_cache.clear()
        pub._need_fail_ts = 0.0

    def tearDown(self):
        pub._need_cache.clear()
        pub._need_fail_ts = 0.0

    def test_parse_full_payload(self):
        rates = pub.parse_coingecko_rub(
            {
                "tether": {"rub": 86.15},
                "bitcoin": {"rub": 6690230},
                "litecoin": {"rub": 4233.68},
                "tron": {"rub": 29.31},
            }
        )
        self.assertAlmostEqual(rates["usdt"], 86.15)
        self.assertAlmostEqual(rates["btc"], 6690230)

    def test_parse_partial(self):
        rates = pub.parse_coingecko_rub({"tether": {"rub": 86.15}})
        self.assertEqual(set(rates), {"usdt"})

    async def test_cached_complete_skips_fetch(self):
        pub._store_need({"usdt": 86.0, "btc": 1.0, "ltc": 2.0, "trx": 3.0})
        with patch.object(
            pub, "_fetch_coingecko_rub", new=AsyncMock(side_effect=AssertionError("no fetch"))
        ):
            rates = await pub.get_need_rates_cached()
        self.assertAlmostEqual(rates["usdt"], 86.0)

    async def test_fetch_failure_empty(self):
        with patch.object(
            pub, "_fetch_coingecko_rub", new=AsyncMock(side_effect=RuntimeError("429"))
        ):
            rates = await pub.get_need_rates_cached()
        self.assertEqual(rates, {})


if __name__ == "__main__":
    unittest.main()
