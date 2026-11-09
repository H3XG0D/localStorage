"""Чеки на карточке payin: подтверждение и отклонение без PayFast."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from permissions import attach_operator_permissions_sync


def _senior(op_id: int = 5):
    return attach_operator_permissions_sync(
        {
            "id": op_id,
            "username": "fin-senior",
            "display_name": "Старший финанс",
            "operator_roles": ["finance"],
            "operator_role": "finance",
            "role_grades": {"finance": "senior"},
        }
    )


def buy_payin_row(**over):
    row = {
        "order_id": "B1",
        "direction": "buy",
        "status": "AWAITING_CHECK",
        "payin_requisite_id": 13,
        "operator_id": 5,
        "finance_operator_id": 5,
        "user_id": 111,
        "crypto": "usdt",
        "fiat_amount": 15000,
        "receipt_file": "buyer.pdf",
    }
    row.update(over)
    return row


def _pool(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = ctx

    async def get_pool():
        return pool

    return get_pool


def _conn(row, updated=None):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        side_effect=[row, updated or {**row, "status": "COMPLETED"}, None]
    )
    conn.execute = AsyncMock()
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction.return_value = tx
    return conn


class PayinReceivedTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, row, updated=None, op=None):
        from routers import operator as mod

        conn = _conn(row, updated)
        settle = AsyncMock(return_value=13)
        bot_set = AsyncMock(return_value=True)
        with patch("routers.operator.get_pool", new=_pool(conn)), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch("permissions.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)), patch(
            "bot_status_bridge.update_order_status", new=bot_set
        ), patch(
            "payin_requisite_rail.settle_payin_allocation", new=settle
        ), patch(
            "payin_requisite_rail.complete_triangle_sell", new=AsyncMock(return_value=None)
        ):
            out = await mod.confirm_payin_fiat_received("B1", op=op or _senior())
        return out, conn, bot_set, settle

    async def test_completes_and_settles(self):
        out, _conn_obj, bot_set, settle = await self._call(buy_payin_row())
        self.assertEqual(out["order"]["order_id"], "B1")
        bot_set.assert_awaited_with("B1", "COMPLETED")
        settle.assert_awaited()

    async def test_closed_triangle_card_completes_sell(self):
        from routers import operator as mod

        row = buy_payin_row()
        updated = {**row, "status": "COMPLETED"}
        triangle = {
            "id": 13,
            "status": "CLOSED",
            "source_sell_order_id": "S1",
            "paid_rub": 5000,
            "amount_rub": 5000,
        }
        conn = _conn(row, updated)
        conn.fetchrow = AsyncMock(side_effect=[row, updated, triangle])
        settle = AsyncMock(return_value=13)
        bot_set = AsyncMock(return_value=True)
        complete = AsyncMock(return_value={"order_id": "S1"})
        with patch("routers.operator.get_pool", new=_pool(conn)), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch("permissions.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)), patch(
            "bot_status_bridge.update_order_status", new=bot_set
        ), patch(
            "payin_requisite_rail.settle_payin_allocation", new=settle
        ), patch(
            "payin_requisite_rail.complete_triangle_sell", new=complete
        ):
            await mod.confirm_payin_fiat_received("B1", op=_senior())
        complete.assert_awaited()
        self.assertEqual(complete.await_args.args[0]["source_sell_order_id"], "S1")

    async def test_local_fallback_when_bridge_off(self):
        from routers import operator as mod

        row = buy_payin_row()
        updated = {**row, "status": "COMPLETED"}
        conn = _conn(row, updated)
        conn.fetchrow = AsyncMock(
            side_effect=[
                row,
                {"order_id": "B1"},
                updated,
                None,
            ]
        )
        bot_set = AsyncMock(return_value=False)
        settle = AsyncMock(return_value=13)
        with patch("routers.operator.get_pool", new=_pool(conn)), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch("permissions.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)), patch(
            "bot_status_bridge.update_order_status", new=bot_set
        ), patch(
            "payin_requisite_rail.settle_payin_allocation", new=settle
        ):
            out = await mod.confirm_payin_fiat_received("B1", op=_senior())
        self.assertEqual(out["order"]["status"], "COMPLETED")
        self.assertGreaterEqual(settle.await_count, 1)

    async def test_sell_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(buy_payin_row(direction="sell", payin_requisite_id=None))
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_non_rail_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(buy_payin_row(payin_requisite_id=None))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("пейин", str(ctx.exception.detail))

    async def test_foreign_finance_operator_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(buy_payin_row(finance_operator_id=9))
        self.assertEqual(ctx.exception.status_code, 403)


class PayinRejectTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, row, updated=None, op=None):
        from routers import operator as mod

        conn = _conn(row, updated or {**row, "status": "CANCELED"})
        bot_set = AsyncMock(return_value=True)
        notify = AsyncMock()
        cancel_pf = AsyncMock()
        with patch("routers.operator.get_pool", new=_pool(conn)), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch("permissions.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)), patch(
            "bot_status_bridge.update_order_status", new=bot_set
        ), patch(
            "telegram_notify.send_user_message", new=notify
        ), patch(
            "merchant_api_helpers.cancel_payin_for_order", new=cancel_pf
        ):
            out = await mod.reject_payin_receipt("B1", op=op or _senior())
        return out, conn, bot_set, notify, cancel_pf

    async def test_cancels_without_payfast_or_ban(self):
        out, conn, bot_set, notify, cancel_pf = await self._call(buy_payin_row())
        self.assertEqual(out["order"]["order_id"], "B1")
        bot_set.assert_awaited_with("B1", "CANCELED")
        cancel_pf.assert_not_called()
        notify.assert_awaited()
        sql = conn.execute.await_args.args[0]
        self.assertIn("cancel_reason", sql)
        self.assertIn("Чек не принят", conn.execute.await_args.args)

    async def test_does_not_settle(self):
        settle = AsyncMock()
        from routers import operator as mod

        conn = _conn(buy_payin_row(), {**buy_payin_row(), "status": "CANCELED"})
        with patch("routers.operator.get_pool", new=_pool(conn)), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch("permissions.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)), patch(
            "bot_status_bridge.update_order_status", new=AsyncMock(return_value=True)
        ), patch(
            "telegram_notify.send_user_message", new=AsyncMock()
        ), patch(
            "payin_requisite_rail.settle_payin_allocation", new=settle
        ):
            await mod.reject_payin_receipt("B1", op=_senior())
        settle.assert_not_called()

    async def test_completed_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(buy_payin_row(status="COMPLETED"))
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
