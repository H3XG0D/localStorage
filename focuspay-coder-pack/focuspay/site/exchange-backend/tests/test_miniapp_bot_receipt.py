"""Miniapp orders are their own source and their receipts follow the bot review tree."""
import inspect
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from buy_order_web import create_buy_web
from order_service import attach_receipt, create_web_order
from routers.web_orders import order_source_from_bearer


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _pool(conn):
    pool = MagicMock()
    pool.acquire.return_value = _Acquire(conn)
    return pool


def _row(**extra):
    base = {
        "order_id": "100",
        "user_id": 7,
        "status": "AWAITING_CHECK",
        "direction": "buy",
        "order_source": "site",
        "payin_requisite_id": None,
        "merchant_order_id": "100",
        "receipt_file": None,
        "required_receipt_type": 2,
    }
    base.update(extra)
    return base


class MiniappSourceTests(unittest.TestCase):
    def test_create_defaults_stay_site(self):
        self.assertEqual(inspect.signature(create_web_order).parameters["order_source"].default, "site")
        self.assertEqual(inspect.signature(create_buy_web).parameters["order_source"].default, "site")

    def test_bearer_via_selects_bot_only_for_miniapp(self):
        creds = SimpleNamespace(scheme="Bearer", credentials="tok")
        with patch("routers.web_orders.decode_token", return_value={"via": "tg_miniapp", "sub": "1"}):
            self.assertEqual(order_source_from_bearer(creds), "tg_miniapp")
        with patch("routers.web_orders.decode_token", return_value={"sub": "1"}):
            self.assertEqual(order_source_from_bearer(creds), "site")
        self.assertEqual(order_source_from_bearer(None), "site")


class AttachReceiptChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_miniapp_receipt_is_routed_and_not_sent_to_merchant(self):
        row = _row(order_source="tg_miniapp")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute = AsyncMock()
        routed = {
            "route": "submitted",
            "status": "PENDING",
            "client_message": "Чек отправлен",
            "parse_mode": None,
        }
        with patch("order_service._fetch_order_row_for_web", new=AsyncMock(return_value=row)), patch(
            "order_service.get_pool", new=AsyncMock(return_value=_pool(conn))
        ), patch("order_service.payfast_requisites_are_closed", return_value=False), patch(
            "bot_status_bridge.route_uploaded_receipt", new=AsyncMock(return_value=routed)
        ) as route, patch(
            "merchant_api_helpers.payin_set_check_for_order", new=AsyncMock()
        ) as payin:
            out = await attach_receipt("100", 7, "https://receipt", receipt_file="a.pdf")
        route.assert_awaited_once()
        payin.assert_not_awaited()
        self.assertEqual(out["status"], "PENDING")
        self.assertTrue(out["receipt_submitted"])

    async def test_bot_receipt_is_routed_and_not_sent_to_merchant(self):
        row = _row(order_source="bot")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute = AsyncMock()
        routed = {
            "route": "held",
            "status": "AWAITING_CHECK",
            "client_message": "Чек принят",
            "parse_mode": None,
        }
        with patch("order_service._fetch_order_row_for_web", new=AsyncMock(return_value=row)), patch(
            "order_service.get_pool", new=AsyncMock(return_value=_pool(conn))
        ), patch("order_service.payfast_requisites_are_closed", return_value=False), patch(
            "bot_status_bridge.route_uploaded_receipt", new=AsyncMock(return_value=routed)
        ) as route, patch(
            "merchant_api_helpers.payin_set_check_for_order", new=AsyncMock()
        ) as payin:
            out = await attach_receipt("100", 7, "https://receipt", receipt_file="a.pdf")
        route.assert_awaited_once()
        payin.assert_not_awaited()
        self.assertEqual(out["status"], "AWAITING_CHECK")
        self.assertTrue(out["receipt_submitted"])

    async def test_site_receipt_still_goes_straight_to_merchant(self):
        row = _row(order_source="site")
        refreshed = {**row, "status": "PENDING"}
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[row, refreshed])
        conn.execute = AsyncMock()
        with patch("order_service._fetch_order_row_for_web", new=AsyncMock(return_value=row)), patch(
            "order_service.get_pool", new=AsyncMock(return_value=_pool(conn))
        ), patch("order_service.payfast_requisites_are_closed", return_value=False), patch(
            "bot_status_bridge.route_uploaded_receipt", new=AsyncMock()
        ) as route, patch(
            "merchant_api_helpers.payin_set_check_for_order",
            new=AsyncMock(return_value={"status": 200, "body": {}}),
        ) as payin, patch(
            "bot_status_bridge.update_order_status", new=AsyncMock(return_value=True)
        ), patch(
            "bot_status_bridge.try_complete_if_payfast_settled", new=AsyncMock()
        ), patch("order_service._safe_notify_ops", new=AsyncMock()):
            out = await attach_receipt("100", 7, "https://receipt", receipt_file="a.pdf")
        route.assert_not_awaited()
        payin.assert_awaited_once()
        self.assertEqual(out["status"], "PENDING")

    async def test_reki_receipt_uses_bot_route_not_merchant(self):
        row = _row(
            order_source="manual_operator",
            merchant_order_id=None,
            payment_snapshot={
                "reki_payfast_id": "d84a6631-28dc-4afd-aa52-533a5b5bdaa3",
            },
        )
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute = AsyncMock()
        routed = {
            "route": "reki_sent",
            "status": "PENDING",
            "client_message": "Чек отправлен",
            "parse_mode": None,
        }
        with patch("order_service._fetch_order_row_for_web", new=AsyncMock(return_value=row)), patch(
            "order_service.get_pool", new=AsyncMock(return_value=_pool(conn))
        ), patch("order_service.payfast_requisites_are_closed", return_value=False), patch(
            "bot_status_bridge.route_uploaded_receipt", new=AsyncMock(return_value=routed)
        ) as route, patch(
            "merchant_api_helpers.payin_set_check_for_order", new=AsyncMock()
        ) as payin:
            out = await attach_receipt("100", 7, "https://receipt", receipt_file="a.pdf")
        route.assert_awaited_once()
        payin.assert_not_awaited()
        self.assertEqual(out["status"], "PENDING")

    async def test_bot_reject_does_not_pretend_the_receipt_was_accepted(self):
        row = _row(order_source="bot")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute = AsyncMock()
        routed = {
            "route": "rejected",
            "status": "AWAITING_CHECK",
            "client_message": "Чек не принят <b>банком</b>",
            "parse_mode": "HTML",
        }
        with patch("order_service._fetch_order_row_for_web", new=AsyncMock(return_value=row)), patch(
            "order_service.get_pool", new=AsyncMock(return_value=_pool(conn))
        ), patch("order_service.payfast_requisites_are_closed", return_value=False), patch(
            "bot_status_bridge.route_uploaded_receipt", new=AsyncMock(return_value=routed)
        ), patch("merchant_api_helpers.payin_set_check_for_order", new=AsyncMock()) as payin:
            with self.assertRaises(HTTPException) as exc:
                await attach_receipt("100", 7, "https://receipt", receipt_file="a.pdf")
        payin.assert_not_awaited()
        self.assertEqual(exc.exception.status_code, 400)
        self.assertNotIn("<b>", exc.exception.detail)
