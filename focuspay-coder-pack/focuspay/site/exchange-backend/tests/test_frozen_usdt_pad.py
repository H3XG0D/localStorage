"""USDT serve pads: BUY +2 (frozen +0.5 extra), SELL −2. Cache stays raw."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

try:
    from routers import public as pub
except ImportError:  # local machine without backend venv
    pub = None


@unittest.skipIf(pub is None, "exchange-backend deps missing")
class FrozenUsdtPadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        pub._cache.clear()
        pub._LAST_SOURCE = "none"

    def tearDown(self):
        pub._cache.clear()
        pub._LAST_SOURCE = "none"

    def test_live_usdt_earn_pad_does_not_stack(self):
        pub._store_rates({"usdt": 85.6, "btc": 1.0, "ltc": 2.0, "trx": 3.0}, source="rapira")
        first = pub._with_buy_usdt_pad(pub._cached_rates())
        second = pub._with_buy_usdt_pad(pub._cached_rates())
        self.assertAlmostEqual(first["usdt"], 87.6)
        self.assertAlmostEqual(second["usdt"], 87.6)
        self.assertAlmostEqual(pub._cache["usdt"], 85.6)
        self.assertAlmostEqual(first["btc"], 1.0)

    def test_frozen_adds_earn_pad_and_stale_pad(self):
        pub._store_rates({"usdt": 85.6, "btc": 1.0, "ltc": 2.0, "trx": 3.0}, source="frozen")
        first = pub._with_buy_usdt_pad(pub._cached_rates())
        second = pub._with_buy_usdt_pad(pub._cached_rates())
        self.assertAlmostEqual(first["usdt"], 88.1)
        self.assertAlmostEqual(second["usdt"], 88.1)
        self.assertAlmostEqual(pub._cache["usdt"], 85.6)
        self.assertAlmostEqual(first["btc"], 1.0)

    def test_sell_usdt_pad_leaves_other_coins(self):
        raw = {"usdt": 85.6, "btc": 1.0, "ltc": 2.0, "trx": 3.0}
        served = pub._with_sell_usdt_pad(raw)
        self.assertAlmostEqual(served["usdt"], 83.6)
        self.assertAlmostEqual(served["btc"], 1.0)
        self.assertAlmostEqual(raw["usdt"], 85.6)

    async def test_get_rates_cached_live_pads_not_cache(self):
        live = {"usdt": 85.6, "btc": 1.0, "ltc": 2.0, "trx": 3.0}
        with patch.object(pub, "_cached_rates", return_value=None), patch.object(
            pub, "_load_snapshot_rates", return_value=None
        ), patch.object(pub, "_fetch_rapira_only", new=AsyncMock(return_value=live)):
            served = await pub.get_rates_cached()
        self.assertAlmostEqual(served["usdt"], 87.6)
        self.assertAlmostEqual(pub._cache["usdt"], 85.6)
        self.assertEqual(pub.rates_source(), "rapira")

    async def test_get_rates_cached_pads_snapshot_not_cache(self):
        snap = {"usdt": 85.6, "btc": 1.0, "ltc": 2.0, "trx": 3.0}
        with patch.object(pub, "_load_snapshot_rates", return_value=snap), patch.object(
            pub, "_schedule_refresh"
        ), patch.object(pub, "_fetch_rapira_only", new=AsyncMock(side_effect=AssertionError("no live fetch"))):
            served = await pub.get_rates_cached()
        self.assertAlmostEqual(served["usdt"], 88.1)
        self.assertAlmostEqual(pub._cache["usdt"], 85.6)
        self.assertEqual(pub.rates_source(), "frozen")
        again = await pub.get_rates_cached()
        self.assertAlmostEqual(again["usdt"], 88.1)
        self.assertAlmostEqual(pub._cache["usdt"], 85.6)
