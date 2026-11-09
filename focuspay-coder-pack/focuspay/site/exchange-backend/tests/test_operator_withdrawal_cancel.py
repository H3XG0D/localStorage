"""Оператор отменяет pending-вывод баланса из очереди заявок."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from routers.operator import cancel_balance_withdrawal


def _pool(conn):
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = ctx
    return pool


def _finance(operator_id=4):
    return {"id": operator_id, "operator_role": "finance", "operator_roles": ["finance"]}


class CancelBalanceWithdrawalTests(unittest.IsolatedAsyncioTestCase):
    async def test_finance_cancels_incoming_and_notifies(self):
        pending = {
            "id": 67,
            "status": "pending",
            "operator_id": None,
            "source": "balance",
            "referrer_user_id": 9,
        }
        rejected = {**pending, "status": "rejected"}
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"id": 1}, pending, rejected])
        notify = AsyncMock()
        release = AsyncMock()
        with patch("routers.operator.get_pool", new=AsyncMock(return_value=_pool(conn))), patch(
            "user_referral_withdraw.release_empty_withdrawal_triangle", new=release
        ), patch("user_referral_withdraw.notify_withdrawal_rejected", new=notify):
            out = await cancel_balance_withdrawal(67, op=_finance())

        self.assertEqual(out["withdrawal"]["status"], "rejected")
        self.assertEqual(out["withdrawal"]["id"], 67)
        release.assert_awaited_once()
        notify.assert_awaited_once()
        update_sql = conn.fetchrow.await_args_list[-1].args[0]
        self.assertIn("status = 'rejected'", update_sql)
        self.assertIn("operator_id IS NULL OR operator_id = $2", update_sql)

    async def test_client_role_forbidden(self):
        with self.assertRaises(HTTPException) as ctx:
            await cancel_balance_withdrawal(
                67,
                op={"id": 2, "operator_role": "client", "operator_roles": ["client"]},
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_other_operator_forbidden(self):
        pending = {
            "id": 67,
            "status": "pending",
            "operator_id": 99,
            "source": "balance",
            "referrer_user_id": 9,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"id": 1}, pending])
        with patch("routers.operator.get_pool", new=AsyncMock(return_value=_pool(conn))):
            with self.assertRaises(HTTPException) as ctx:
                await cancel_balance_withdrawal(67, op=_finance())
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("другого оператора", ctx.exception.detail)

    async def test_casino_hidden_from_balance_queue(self):
        pending = {
            "id": 67,
            "status": "pending",
            "operator_id": None,
            "source": "casino",
            "referrer_user_id": 9,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"id": 1}, pending])
        with patch("routers.operator.get_pool", new=AsyncMock(return_value=_pool(conn))):
            with self.assertRaises(HTTPException) as ctx:
                await cancel_balance_withdrawal(67, op=_finance())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_already_paid_conflict(self):
        paid = {
            "id": 67,
            "status": "paid",
            "operator_id": 4,
            "source": "balance",
            "referrer_user_id": 9,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"id": 1}, paid])
        with patch("routers.operator.get_pool", new=AsyncMock(return_value=_pool(conn))):
            with self.assertRaises(HTTPException) as ctx:
                await cancel_balance_withdrawal(67, op=_finance())
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_paid_triangle_blocks_cancel(self):
        from user_referral_withdraw import WithdrawalCancelError

        pending = {
            "id": 67,
            "status": "pending",
            "operator_id": None,
            "source": "balance",
            "referrer_user_id": 9,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"id": 1}, pending])
        release = AsyncMock(
            side_effect=WithdrawalCancelError(
                "triangle_paid",
                "По карте уже есть оплата, отменить вывод нельзя",
            )
        )
        with patch("routers.operator.get_pool", new=AsyncMock(return_value=_pool(conn))), patch(
            "user_referral_withdraw.release_empty_withdrawal_triangle", new=release
        ):
            with self.assertRaises(HTTPException) as ctx:
                await cancel_balance_withdrawal(67, op=_finance())
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("оплата", ctx.exception.detail)

    async def test_closed_shift_forbidden(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        with patch("routers.operator.get_pool", new=AsyncMock(return_value=_pool(conn))):
            with self.assertRaises(HTTPException) as ctx:
                await cancel_balance_withdrawal(67, op=_finance())
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("смену", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
