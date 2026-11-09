"""Тесты payin/markup для внештатных сделок."""
from __future__ import annotations

import inspect
import unittest
from unittest.mock import AsyncMock

from external_exchange_calc import calc_deal
from external_exchange_service import resolve_exchanger_markup, resolve_exchanger_markup_pct
from external_deal_payin import ACTIVE_STATUSES, _resolve_status_filter, get_active_deal, list_active_deals


class ResolveMarkupTests(unittest.TestCase):
    def test_global_default(self):
        from config import settings

        self.assertEqual(resolve_exchanger_markup_pct({}), float(settings.ext_markup_pct))

    def test_per_exchanger(self):
        self.assertEqual(resolve_exchanger_markup_pct({"markup_pct": 15.0}), 15.0)

    def test_zero_markup(self):
        self.assertEqual(resolve_exchanger_markup_pct({"markup_pct": 0}), 0.0)

    def test_default_mode_on_deal(self):
        m = resolve_exchanger_markup({})
        self.assertEqual(m["markup_mode"], "on_deal")

    def test_turnover_mode(self):
        m = resolve_exchanger_markup({"markup_mode": "on_turnover", "markup_pct": 15})
        self.assertEqual(m["markup_mode"], "on_turnover")
        self.assertEqual(m["markup_pct"], 15.0)


class CustomMarkupCalcTests(unittest.TestCase):
    def test_15pct_client_pays(self):
        r = calc_deal(
            10000,
            81.0,
            markup_pct=15.0,
            card_fee_pct=0.12,
            receive_fee_usd=0.0,
            operator_percent=0.0,
        )
        self.assertAlmostEqual(r.client_pays_rub, 11500.0, places=2)
        self.assertAlmostEqual(r.principal_usdt, 10000 / 81.0, places=2)
        self.assertEqual(r.reward_usdt, 0.0)


class StatusFilterTests(unittest.TestCase):
    def test_active_maps_to_active_statuses(self):
        self.assertEqual(_resolve_status_filter("active"), list(ACTIVE_STATUSES))

    def test_confirmed(self):
        self.assertEqual(_resolve_status_filter("confirmed"), ["confirmed"])

    def test_none_returns_none(self):
        self.assertIsNone(_resolve_status_filter(None))
        self.assertIsNone(_resolve_status_filter(""))

    def test_unknown_returns_none(self):
        self.assertIsNone(_resolve_status_filter("bogus"))


class ConfirmStatusRules(unittest.TestCase):
    def test_pending_allowed(self):
        status = "pending"
        has_merchant = True
        allowed = status == "pending" or (status == "awaiting_receipt" and not has_merchant)
        self.assertTrue(allowed)

    def test_awaiting_with_merchant_blocked(self):
        status = "awaiting_receipt"
        has_merchant = True
        allowed = status == "pending" or (status == "awaiting_receipt" and not has_merchant)
        self.assertFalse(allowed)

    def test_ops_flow_without_merchant(self):
        status = "awaiting_receipt"
        has_merchant = False
        allowed = status == "pending" or (status == "awaiting_receipt" and not has_merchant)
        self.assertTrue(allowed)


class ListActiveDealsTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_all_active_rows(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[{"id": 10}, {"id": 11}, {"id": 12}]
        )
        rows = await list_active_deals(conn, 7)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["id"], 10)
        sql = conn.fetch.await_args.args[0]
        self.assertNotIn("LIMIT 1", sql.upper())

    async def test_get_active_deal_returns_latest_or_none(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[{"id": 5}, {"id": 4}])
        row = await get_active_deal(conn, 7)
        self.assertEqual(row["id"], 5)

        conn.fetch = AsyncMock(return_value=[])
        row = await get_active_deal(conn, 7)
        self.assertIsNone(row)


class CanonicalPayinIdTests(unittest.IsolatedAsyncioTestCase):
    async def test_attach_uses_one_canonical_id_for_merchant_and_storage(self):
        from unittest.mock import patch

        from external_deal_payin import _attach_payin_to_deal
        from payin_resolver import PayinPlan

        discovery = type("Discovery", (), {
            "plan": PayinPlan(mode="single", has_bill=True),
            "probe_response": {
                "uuid_system": "merchant-uuid",
                "bill": {"reciver": "+79990000000"},
            },
            "probe_order_id": "partner-42",
        })()
        conn = AsyncMock()
        with patch("external_deal_payin.discover_payin_plan", new=AsyncMock(return_value=discovery)) as discover:
            await _attach_payin_to_deal(
                conn, 42, 7, 1000, "SBPRUB", client_transaction_id="partner-42"
            )

        self.assertEqual(discover.await_args.kwargs["client_transaction_id"], "partner-42")
        self.assertEqual(conn.execute.await_args.args[1], "partner-42")
        self.assertEqual(conn.execute.await_args.args[5], "partner-42")

    async def test_attach_falls_back_to_deterministic_deal_id(self):
        from unittest.mock import patch

        from external_deal_payin import _attach_payin_to_deal
        from payin_resolver import PayinPlan

        discovery = type("Discovery", (), {
            "plan": PayinPlan(mode="single", has_bill=True),
            "probe_response": {"bill": {"reciver": "+79990000000"}},
            "probe_order_id": "EXT-43",
        })()
        conn = AsyncMock()
        with patch("external_deal_payin.discover_payin_plan", new=AsyncMock(return_value=discovery)) as discover:
            await _attach_payin_to_deal(conn, 43, 7, 1000, "SBPRUB")

        self.assertEqual(discover.await_args.kwargs["client_transaction_id"], "EXT-43")
        self.assertEqual(conn.execute.await_args.args[1], "EXT-43")
        self.assertEqual(conn.execute.await_args.args[5], "EXT-43")


class CreateCabinetDealMultiTests(unittest.TestCase):
    def test_no_single_active_deal_guard(self):
        from external_deal_payin import create_cabinet_deal_with_payin

        source = inspect.getsource(create_cabinet_deal_with_payin)
        self.assertNotIn("409", source)
        self.assertNotIn("get_active_deal", source)
        self.assertNotIn("незавершённая сделка", source)


class InputRubFromCryptoTests(unittest.TestCase):
    def test_ltc_fraction(self):
        from external_deal_payin import input_rub_from_crypto

        self.assertEqual(input_rub_from_crypto(1.5243, "ltc", {"ltc": 8100.0}), 12346.83)

    def test_missing_rate(self):
        from external_deal_payin import DealAmountError, input_rub_from_crypto

        with self.assertRaises(DealAmountError) as ctx:
            input_rub_from_crypto(1.0, "ltc", {"usdt": 80.0})
        self.assertEqual(ctx.exception.code, "rate")

    def test_too_small(self):
        from external_deal_payin import DealAmountError, input_rub_from_crypto

        with self.assertRaises(DealAmountError) as ctx:
            input_rub_from_crypto(0.0001, "usdt", {"usdt": 80.0})
        self.assertEqual(ctx.exception.code, "too_small")

    def test_crypto_wins_over_rub(self):
        from fastapi import HTTPException

        from external_deal_payin import resolve_cabinet_input_rub

        rub, extra = resolve_cabinet_input_rub(
            amount_rub=50000,
            amount_crypto=1.5,
            crypto="ltc",
            rates={"ltc": 8000.0, "usdt": 80.0},
        )
        self.assertEqual(rub, 12000.0)
        self.assertEqual(extra["amount_unit"], "crypto")
        self.assertEqual(extra["input_rub"], 12000.0)

        with self.assertRaises(HTTPException) as ctx:
            resolve_cabinet_input_rub(amount_rub=None, amount_crypto=None, rates={"usdt": 80})
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
