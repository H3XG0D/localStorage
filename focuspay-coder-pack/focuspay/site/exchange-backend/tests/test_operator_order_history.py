"""Архив заявок для старших: 403 junior, 200 senior, без прибыли."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from permissions import (
    PERM_ORDERS_HISTORY,
    attach_operator_permissions_sync,
    resolve_operator_permissions,
)

ROOT = Path(__file__).resolve().parents[1]


def _history_mod():
    try:
        from routers import operator_order_history as mod
    except ModuleNotFoundError as exc:
        raise unittest.SkipTest(str(exc)) from exc
    return mod


def _senior(**extra):
    return attach_operator_permissions_sync(
        {
            "id": 10,
            "operator_roles": ["client"],
            "role_grades": {"client": "senior"},
            **extra,
        }
    )


def _junior_finance():
    return attach_operator_permissions_sync(
        {
            "id": 11,
            "operator_roles": ["finance"],
            "operator_role": "finance",
            "role_grades": {"finance": "junior"},
        }
    )


def _pool():
    from unittest.mock import MagicMock

    conn = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = ctx

    async def _get_pool():
        return pool

    return _get_pool, conn


PAID_ROW = {
    "id": 1,
    "order_id": "0P4F",
    "user_id": 42,
    "status": "PAID",
    "direction": "buy",
    "crypto": "btc",
    "fiat_amount": 5000,
    "crypto_amount": 0.05,
    "operator_display_name": "miltos",
    "created_at": "2026-01-01T00:00:00+00:00",
}


class ResolveSeniorHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_db_senior_adds_permission(self):
        op = {"id": 9, "operator_roles": ["client"]}
        with patch(
            "permissions.load_operator_role_grades",
            new=AsyncMock(return_value={"client": "senior"}),
        ), patch(
            "permissions.load_operator_permission_grants",
            new=AsyncMock(return_value=[]),
        ):
            perms = await resolve_operator_permissions(op)
        self.assertIn(PERM_ORDERS_HISTORY, perms)

    async def test_db_junior_finance_no_permission(self):
        op = {"id": 8, "operator_roles": ["finance"]}
        with patch(
            "permissions.load_operator_role_grades",
            new=AsyncMock(return_value={"finance": "junior"}),
        ), patch(
            "permissions.load_operator_permission_grants",
            new=AsyncMock(return_value=[]),
        ):
            perms = await resolve_operator_permissions(op)
        self.assertNotIn(PERM_ORDERS_HISTORY, perms)


class OperatorOrderHistoryEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_junior_forbidden(self):
        mod = _history_mod()
        with patch(
            "routers.operator_order_history.enrich_operator_permissions",
            new=AsyncMock(side_effect=lambda o: o),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await mod.list_order_history(op=_junior_finance())
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("orders.history", str(ctx.exception.detail))

    async def test_senior_list_has_counts_no_profit(self):
        mod = _history_mod()
        get_pool, _conn = _pool()
        archive = {
            "rows": [PAID_ROW],
            "total": 1,
            "partner_rows": [],
            "counts": {"all": 1, "PAID": 1, "CANCELED": 0},
        }
        with patch(
            "routers.operator_order_history.enrich_operator_permissions",
            new=AsyncMock(side_effect=lambda o: o),
        ), patch(
            "routers.operator_order_history.get_pool",
            new=get_pool,
        ), patch(
            "routers.operator_order_history.fetch_orders_archive",
            new=AsyncMock(return_value=archive),
        ):
            result = await mod.list_order_history(op=_senior(), search="0P4F", status="PAID")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["counts"]["PAID"], 1)
        self.assertEqual(result["orders"][0]["order_id"], "0P4F")
        self.assertNotIn("service_profit_rub", result["orders"][0])

    async def test_senior_item_and_404(self):
        mod = _history_mod()
        get_pool, _conn = _pool()
        with patch(
            "routers.operator_order_history.enrich_operator_permissions",
            new=AsyncMock(side_effect=lambda o: o),
        ), patch(
            "routers.operator_order_history.get_pool",
            new=get_pool,
        ), patch(
            "routers.operator_order_history.fetch_order_archive_row",
            new=AsyncMock(return_value=PAID_ROW),
        ):
            item = await mod.get_order_history_item(order_id="0p4f", op=_senior())
        self.assertEqual(item["order_id"], "0P4F")
        self.assertNotIn("service_profit_rub", item)

        with patch(
            "routers.operator_order_history.enrich_operator_permissions",
            new=AsyncMock(side_effect=lambda o: o),
        ), patch(
            "routers.operator_order_history.get_pool",
            new=get_pool,
        ), patch(
            "routers.operator_order_history.fetch_order_archive_row",
            new=AsyncMock(return_value=None),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await mod.get_order_history_item(order_id="NOPE", op=_senior())
        self.assertEqual(ctx.exception.status_code, 404)


class WiringTests(unittest.TestCase):
    def test_router_wired_and_read_only(self):
        main = (ROOT / "main.py").read_text()
        router = (ROOT / "routers" / "operator_order_history.py").read_text()
        self.assertIn("operator_order_history", main)
        self.assertIn("PERM_ORDERS_HISTORY", router)
        self.assertIn("/orders/history", router)
        self.assertIn("/orders/history/{order_id}", router)
        self.assertNotIn("PATCH", router)
        self.assertNotIn("/payout", router)
        self.assertNotIn("include_finance=True", router)


if __name__ == "__main__":
    unittest.main()
