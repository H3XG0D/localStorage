"""BUY RUB quote: crypto from CoinGecko, pay from Rapira."""
from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from services.buy_rub_quote import quote_buy_rub_base
from services import rates_api as ra


class QuoteBuyRubBaseTests(unittest.TestCase):
    def test_same_rates_is_base_times_markup(self):
        crypto, pay, rate = quote_buy_rub_base(
            base_fiat=Decimal("1000"),
            rapira=Decimal("100"),
            coingecko=Decimal("100"),
            markup=Decimal("1.21"),
        )
        self.assertEqual(crypto, Decimal("10"))
        self.assertEqual(pay, Decimal("1210"))
        self.assertEqual(rate, Decimal("121"))

    def test_coingecko_cheaper_gives_more_crypto_and_higher_pay(self):
        crypto, pay, rate = quote_buy_rub_base(
            base_fiat=Decimal("1000"),
            rapira=Decimal("87.59"),
            coingecko=Decimal("86.15"),
            markup=Decimal("1.21"),
        )
        self.assertGreater(crypto, Decimal("1000") / Decimal("87.59"))
        self.assertGreater(pay, Decimal("1210"))
        self.assertEqual(rate, Decimal("87.59") * Decimal("1.21"))
        self.assertEqual(pay % 1, 0)


class ParseCoingeckoRubTests(unittest.TestCase):
    def test_full_payload(self):
        rates = ra.parse_coingecko_rub(
            {
                "tether": {"rub": 86.15},
                "bitcoin": {"rub": 6690230},
                "litecoin": {"rub": 4233.68},
                "tron": {"rub": 29.31},
            }
        )
        self.assertAlmostEqual(rates["usdt"], 86.15)
        self.assertAlmostEqual(rates["btc"], 6690230)
        self.assertAlmostEqual(rates["ltc"], 4233.68)
        self.assertAlmostEqual(rates["trx"], 29.31)

    def test_partial_skips_missing(self):
        rates = ra.parse_coingecko_rub({"tether": {"rub": 86.15}})
        self.assertEqual(set(rates), {"usdt"})

    def test_invalid_body(self):
        with self.assertRaises(ValueError):
            ra.parse_coingecko_rub("nope")


class NeedCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ra.reset_rates_state(clear_file=False)
        ra._NEED.clear()

    def tearDown(self):
        ra._NEED.clear()
        ra.reset_rates_state(clear_file=False)

    async def test_fresh_cache_hit(self):
        ra._store_need({"usdt": 86.0, "btc": 1.0, "ltc": 2.0, "trx": 3.0}, __import__("time").time())
        with patch(
            "services.rates_api.fetch_coingecko_rub",
            new=AsyncMock(side_effect=AssertionError("no fetch")),
        ):
            rates = await ra.get_need_rates_cached()
        self.assertAlmostEqual(rates["usdt"], 86.0)

    async def test_fetch_failure_returns_empty(self):
        with patch(
            "services.rates_api.fetch_coingecko_rub",
            new=AsyncMock(side_effect=RuntimeError("CoinGecko HTTP 429")),
        ):
            rates = await ra.get_need_rates_cached()
            self.assertEqual(rates, {})
            self.assertIsNone(await ra.get_need_price("usdt"))

    async def test_stale_complete_used_when_fetch_fails(self):
        ra._store_need(
            {"usdt": 86.0, "btc": 1.0, "ltc": 2.0, "trx": 3.0},
            __import__("time").time() - 120,
        )
        with patch(
            "services.rates_api.fetch_coingecko_rub",
            new=AsyncMock(side_effect=RuntimeError("down")),
        ):
            rates = await ra.get_need_rates_cached()
            self.assertAlmostEqual(rates["usdt"], 86.0)
            self.assertAlmostEqual(await ra.get_need_price("usdt"), 86.0)


if __name__ == "__main__":
    unittest.main()
