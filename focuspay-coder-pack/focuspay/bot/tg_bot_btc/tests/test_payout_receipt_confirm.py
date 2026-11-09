"""Клиент жмёт «подтвердить получение» на чеке выплаты."""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def _update(user_id=777, data="spayout:S1"):
    query = SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(callback_query=query), query


class MarkConfirmedTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreign_user_forbidden(self):
        from services.payout_receipt_confirm import mark_payout_receipt_confirmed

        with patch(
            "services.payout_receipt_confirm.get_order",
            new=AsyncMock(return_value={"user_id": 1, "direction": "sell"}),
        ):
            self.assertEqual(await mark_payout_receipt_confirmed("S1", 2), "forbidden")

    async def test_owner_confirms(self):
        from services.payout_receipt_confirm import mark_payout_receipt_confirmed

        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"id": 11, "client_confirmed_at": None})
        conn.execute = AsyncMock()
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction.return_value = tx
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        with patch(
            "services.payout_receipt_confirm.get_order",
            new=AsyncMock(return_value={"user_id": 777, "direction": "sell"}),
        ), patch(
            "services.payout_receipt_confirm.get_pool", new=AsyncMock(return_value=pool)
        ), patch(
            "services.payout_receipt_confirm.close_sell_after_client_confirm",
            new=AsyncMock(),
        ) as close:
            self.assertEqual(await mark_payout_receipt_confirmed("S1", 777), "ok")
        conn.execute.assert_awaited_once()
        close.assert_awaited_once()


class CallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreign_user_alert(self):
        from services.payout_receipt_confirm import payout_receipt_confirm_callback

        update, query = _update(user_id=2)
        with patch(
            "services.payout_receipt_confirm.mark_payout_receipt_confirmed",
            new=AsyncMock(return_value="forbidden"),
        ):
            await payout_receipt_confirm_callback(update, SimpleNamespace())
        query.answer.assert_awaited_once_with("Это не ваша заявка", show_alert=True)
        query.edit_message_reply_markup.assert_not_awaited()

    async def test_owner_removes_button(self):
        from services.payout_receipt_confirm import payout_receipt_confirm_callback

        update, query = _update()
        with patch(
            "services.payout_receipt_confirm.mark_payout_receipt_confirmed",
            new=AsyncMock(return_value="ok"),
        ):
            await payout_receipt_confirm_callback(update, SimpleNamespace())
        query.answer.assert_awaited_once_with("Получение подтверждено", show_alert=False)
        query.edit_message_reply_markup.assert_awaited_once_with(reply_markup=None)


class CloseSellTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_already_paid(self):
        from services.payout_receipt_confirm import close_sell_after_client_confirm

        with patch(
            "services.payout_receipt_confirm.update_order_status",
            new=AsyncMock(),
        ) as status:
            await close_sell_after_client_confirm(
                "S1", {"status": "PAID", "crypto_amount": 1, "fiat_amount": 100}
            )
        status.assert_not_awaited()

    async def test_sets_paid_and_amounts(self):
        from services.payout_receipt_confirm import close_sell_after_client_confirm

        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=4800)
        conn.execute = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx
        with patch(
            "services.payout_receipt_confirm.update_order_status",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.payout_receipt_confirm.get_pool", new=AsyncMock(return_value=pool)
        ), patch(
            "services.payout_receipt_confirm._try_finalize_payroll",
            new=AsyncMock(),
        ):
            await close_sell_after_client_confirm(
                "S1",
                {
                    "status": "OPERATOR_PENDING",
                    "crypto_amount": 0.05,
                    "fiat_amount": 4800,
                    "finance_operator_id": 5,
                },
            )
        conn.execute.assert_awaited_once()
        self.assertIn("operator_crypto_received", conn.execute.await_args.args[0])


class WiringTests(unittest.TestCase):
    def test_handler_registered(self):
        src = (ROOT / "main.py").read_text()
        self.assertIn("payout_receipt_confirm_callback", src)
        self.assertIn('pattern="^spayout:"', src)


if __name__ == "__main__":
    unittest.main()
