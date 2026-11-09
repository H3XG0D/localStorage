"""Реквизитчик не требует Payfast UUID ни на автоподтверждении, ни на кнопке в Telegram."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _pool():
    conn = MagicMock()
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction.return_value = tx
    pool = MagicMock()
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = acquire
    return pool


class ConfirmRequisitePayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_skips_payfast_for_requisite(self):
        from services.buy_payout import confirm_buy_payout

        tx = "a" * 64
        order_pre = {
            "order_id": "20182006",
            "status": "COMPLETED",
            "direction": "buy",
            "payin_requisite_id": 6,
            "crypto": "btc",
            "user_id": 1,
        }
        order_out = {**order_pre, "status": "PAID", "payout_tx_hash": tx}
        verify = AsyncMock(side_effect=AssertionError("payfast"))
        with patch(
            "services.db.get_order", new=AsyncMock(return_value=order_pre)
        ), patch(
            "services.db.get_pool", new=AsyncMock(return_value=_pool())
        ), patch(
            "services.db.transition_buy_payout_to_paid_in_tx",
            new=AsyncMock(return_value=(True, None, order_out)),
        ), patch(
            "services.buy_payout.schedule_paid_notifications",
        ), patch(
            "services.partner_tracking.schedule_partner_exchange",
        ), patch(
            "services.payfast_payin_guard.verify_payfast_ready_for_payout",
            new=verify,
        ):
            ok, err, out = await confirm_buy_payout(
                "20182006", tx_hash=tx, actor="auto"
            )
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(out["status"], "PAID")
        verify.assert_not_called()

    async def test_confirm_still_blocks_payfast_without_uuid(self):
        from services.buy_payout import confirm_buy_payout

        order_pre = {
            "order_id": "1",
            "status": "COMPLETED",
            "direction": "buy",
            "payin_requisite_id": None,
            "crypto": "btc",
        }
        with patch(
            "services.db.get_order", new=AsyncMock(return_value=order_pre)
        ), patch(
            "services.payfast_payin_guard.verify_payfast_ready_for_payout",
            new=AsyncMock(return_value=(False, "payfast_uuid_missing", None)),
        ), patch(
            "services.db.transition_buy_payout_to_paid_in_tx",
            new=AsyncMock(side_effect=AssertionError("paid")),
        ):
            ok, err, _out = await confirm_buy_payout("1", tx_hash="b" * 64, actor="auto")
        self.assertFalse(ok)
        self.assertEqual(err, "payfast_uuid_missing")


class TelegramPayButtonTests(unittest.IsolatedAsyncioTestCase):
    async def _press(self, order: dict):
        from services.admin_callbacks import admin_callback_handler

        query = MagicMock()
        query.data = f"pay:{order['order_id']}:sig"
        query.from_user.id = 7
        query.message.chat_id = -100
        query.message.message_id = 3
        query.answer = AsyncMock()
        update = MagicMock()
        update.callback_query = query
        prompt = AsyncMock()
        verify = AsyncMock(return_value=(False, "payfast_uuid_missing", None))
        with patch("services.admin_callbacks.is_ops_group_chat", return_value=True), patch(
            "services.admin_callbacks.TELEGRAM_ADMIN_IDS", {7}
        ), patch(
            "services.admin_callbacks.verify_signature", return_value=True
        ), patch(
            "services.admin_callbacks.get_order", new=AsyncMock(return_value=order)
        ), patch(
            "services.admin_callbacks._send_hash_prompt", new=prompt
        ), patch(
            "services.payfast_payin_guard.verify_payfast_ready_for_payout", new=verify
        ):
            await admin_callback_handler(update, MagicMock())
        return query, prompt, verify

    async def test_requisite_pay_does_not_ask_payfast(self):
        query, prompt, verify = await self._press(
            {
                "order_id": "20182006",
                "status": "COMPLETED",
                "direction": "buy",
                "payin_requisite_id": 6,
            }
        )
        verify.assert_not_called()
        prompt.assert_awaited()
        query.answer.assert_not_awaited()

    async def test_payfast_pay_still_blocks_without_uuid(self):
        query, prompt, verify = await self._press(
            {
                "order_id": "1",
                "status": "COMPLETED",
                "direction": "buy",
                "payin_requisite_id": None,
            }
        )
        verify.assert_awaited()
        prompt.assert_not_awaited()
        query.answer.assert_awaited()


if __name__ == "__main__":
    unittest.main()
