"""ACL для operator_external: permissions, ownership/team, finance field strip."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from permissions import (
    PERM_EXTERNAL_CONFIRM_ANY,
    PERM_FINANCE_ANALYTICS,
    attach_operator_permissions_sync,
)
from routers import operator_external as ox


def _client(oid: int = 1):
    return attach_operator_permissions_sync(
        {"id": oid, "username": f"op{oid}", "operator_roles": ["client"], "percent": 10}
    )


class StripFinanceTests(unittest.TestCase):
    def test_strips_without_analytics(self):
        principal = _client(1)
        deal = {"id": 1, "reward_usdt": 1.5, "amount_rub": 1000, "operator_earnings_rub": 50}
        out = ox._strip_finance_fields(deal, principal)
        self.assertNotIn("reward_usdt", out)
        self.assertNotIn("operator_earnings_rub", out)
        self.assertEqual(out["amount_rub"], 1000)

    def test_keeps_with_analytics_grant(self):
        principal = _client(1)
        principal["permissions"] = list(principal["permissions"]) + [PERM_FINANCE_ANALYTICS]
        deal = {"id": 1, "reward_usdt": 1.5}
        out = ox._strip_finance_fields(deal, principal)
        self.assertEqual(out["reward_usdt"], 1.5)


class DealAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_allowed(self):
        conn = AsyncMock()
        await ox._assert_deal_access(
            conn, _client(3), {"operator_id": 3}, action="confirm"
        )

    async def test_foreign_without_team_denied(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await ox._assert_deal_access(
                conn, _client(3), {"operator_id": 9}, action="confirm"
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_team_on_shift_allowed(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"?column?": 1})
        await ox._assert_deal_access(
            conn, _client(3), {"operator_id": 9}, action="cancel"
        )

    async def test_confirm_any_allows_admin_created(self):
        principal = _client(3)
        principal["permissions"] = list(principal["permissions"]) + [PERM_EXTERNAL_CONFIRM_ANY]
        conn = AsyncMock()
        await ox._assert_deal_access(
            conn, principal, {"operator_id": None}, action="confirm"
        )

    async def test_hmac_unassigned_allowed_with_confirm(self):
        conn = AsyncMock()
        await ox._assert_deal_access(
            conn, _client(3), {"operator_id": None}, action="confirm"
        )

    async def test_unassigned_denied_without_confirm(self):
        from permissions import attach_operator_permissions_sync

        finance = attach_operator_permissions_sync(
            {"id": 3, "username": "fin", "operator_roles": ["finance"], "percent": 10}
        )
        conn = AsyncMock()
        with self.assertRaises(HTTPException) as ctx:
            await ox._assert_deal_access(
                conn, finance, {"operator_id": None}, action="confirm"
            )
        self.assertEqual(ctx.exception.status_code, 403)


class ActiveShiftTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_shift_403(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await ox._require_active_shift(conn, 1)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_returns_latest_open_shift(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": 42, "operator_id": 1})
        row = await ox._require_active_shift(conn, 1)
        self.assertEqual(row["id"], 42)
        conn.fetchrow.assert_awaited()
        sql = conn.fetchrow.await_args.args[0]
        self.assertIn("ended_at IS NULL", sql)
        self.assertIn("ORDER BY started_at DESC", sql)


class ConfirmEndpointIdorTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_rejects_foreign_deal(self):
        op = {"id": 1, "username": "op1", "operator_roles": ["client"], "percent": 0}
        deal = {"id": 99, "operator_id": 2, "status": "awaiting_receipt"}

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(side_effect=[
            {"id": 1},  # shift
            deal,  # deal FOR UPDATE
            None,  # team check
        ])
        mock_tx = MagicMock()
        mock_tx.__aenter__ = AsyncMock(return_value=None)
        mock_tx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction = MagicMock(return_value=mock_tx)

        mock_pool = MagicMock()
        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire

        with patch("routers.operator_external.get_pool", AsyncMock(return_value=mock_pool)):
            with patch(
                "routers.operator_external.enrich_operator_permissions",
                AsyncMock(return_value=attach_operator_permissions_sync(op)),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await ox.confirm_deal(99, op)
        self.assertEqual(ctx.exception.status_code, 403)


class OpsExternalRoutesTests(unittest.TestCase):
    def test_new_routes_registered(self):
        from pathlib import Path

        src = Path(ox.__file__).read_text()
        self.assertIn('@router.get("/external/deals")', src)
        self.assertIn('@router.get("/external/deals/{deal_id}")', src)
        self.assertIn('@router.post("/external/deals/{deal_id}/video")', src)
        self.assertIn('@router.post("/external/deals/{deal_id}/extend")', src)
        paths = {getattr(r, "path", "") for r in ox.router.routes}
        self.assertIn("/external/deals", paths)
        self.assertIn("/external/deals/{deal_id}/video", paths)
        self.assertIn("/external/deals/{deal_id}/extend", paths)

    def test_list_query_includes_client_stat(self):
        from pathlib import Path

        self.assertIn("client_stat", ox._OPS_DEAL_COLS)
        self.assertIn("_ensure_ops_deal_schema", Path(ox.__file__).read_text())


if __name__ == "__main__":
    unittest.main()
