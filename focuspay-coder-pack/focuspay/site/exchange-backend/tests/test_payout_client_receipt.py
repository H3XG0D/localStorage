"""Пересылка чека выплаты клиенту и подтверждение получения."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException


def _pool(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = ctx

    async def get_pool():
        return pool

    return get_pool


def _conn(*, order=None, alloc=None):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=[order, alloc])
    conn.execute = AsyncMock()
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction.return_value = tx
    return conn


class CaptionTests(unittest.TestCase):
    def test_caption_asks_to_confirm(self):
        from payout_client_receipt import payout_receipt_keyboard, sell_payout_caption

        text = sell_payout_caption(
            {"order_id": "S1", "fiat_amount": 9700, "crypto": "btc", "crypto_amount": 0.05}
        )
        self.assertIn("S1", text)
        self.assertIn("Выплата отправлена", text)
        self.assertNotIn("Сделка завершена", text)
        self.assertIn("Нажмите кнопку", text)
        kb = payout_receipt_keyboard("S1")
        self.assertEqual(kb["inline_keyboard"][0][0]["callback_data"], "spayout:S1")


class DeliverTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_non_telegram_user(self):
        from payout_client_receipt import deliver_payout_receipt_to_client

        self.assertFalse(
            await deliver_payout_receipt_to_client({"user_id": 0, "order_id": "S1"}, "a.pdf")
        )

    async def test_sends_document_with_button(self):
        from payout_client_receipt import deliver_payout_receipt_to_client

        send = AsyncMock(return_value=42)
        with patch(
            "payout_client_receipt.receipt_disk_path", return_value="/tmp/a.pdf"
        ), patch("telegram_notify.send_user_document", new=send):
            ok = await deliver_payout_receipt_to_client(
                {
                    "user_id": 777,
                    "order_id": "S1",
                    "fiat_amount": 1000,
                    "crypto": "usdt",
                    "crypto_amount": 10,
                },
                "a.pdf",
            )
        self.assertTrue(ok)
        send.assert_awaited_once()
        self.assertEqual(send.await_args.args[0], 777)
        self.assertEqual(
            send.await_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"],
            "spayout:S1",
        )


class ConfirmTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_user_not_found(self):
        from payout_client_receipt import confirm_payout_receipt

        conn = _conn(order={"order_id": "S1", "user_id": 1, "direction": "sell"})
        with patch("db.get_pool", new=_pool(conn)), patch(
            "payout_client_receipt.close_sell_after_client_confirm",
            new=AsyncMock(),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await confirm_payout_receipt("S1", 2)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_missing_receipt_conflict(self):
        from payout_client_receipt import confirm_payout_receipt

        conn = _conn(
            order={"order_id": "S1", "user_id": 7, "direction": "sell"},
            alloc=None,
        )
        with patch("db.get_pool", new=_pool(conn)), patch(
            "payout_client_receipt.close_sell_after_client_confirm",
            new=AsyncMock(),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await confirm_payout_receipt("S1", 7)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_idempotent_when_already_confirmed(self):
        from payout_client_receipt import confirm_payout_receipt

        conn = _conn(
            order={"order_id": "S1", "user_id": 7, "direction": "sell"},
            alloc={"id": 11, "client_confirmed_at": datetime.now(timezone.utc)},
        )
        close = AsyncMock(return_value={"ok": True, "order": {"status": "PAID"}})
        with patch("db.get_pool", new=_pool(conn)), patch(
            "payout_client_receipt.close_sell_after_client_confirm",
            new=close,
        ):
            out = await confirm_payout_receipt("S1", 7)
        self.assertTrue(out["already_confirmed"])
        conn.execute.assert_not_awaited()
        close.assert_awaited_once_with("S1")

    async def test_confirms_once(self):
        from payout_client_receipt import confirm_payout_receipt

        conn = _conn(
            order={"order_id": "S1", "user_id": 7, "direction": "sell"},
            alloc={"id": 11, "client_confirmed_at": None},
        )
        close = AsyncMock(return_value={"ok": True, "order": {"status": "PAID"}})
        with patch("db.get_pool", new=_pool(conn)), patch(
            "payout_client_receipt.close_sell_after_client_confirm",
            new=close,
        ):
            out = await confirm_payout_receipt("S1", 7)
        self.assertFalse(out["already_confirmed"])
        conn.execute.assert_awaited_once()
        close.assert_awaited_once_with("S1")


class CloseSellTests(unittest.IsolatedAsyncioTestCase):
    async def test_already_paid_is_idempotent(self):
        from payout_client_receipt import close_sell_after_client_confirm

        order = {
            "order_id": "S1",
            "direction": "sell",
            "status": "PAID",
            "crypto_amount": 0.05,
            "fiat_amount": 4800,
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=order)
        with patch("db.get_pool", new=_pool(conn)), patch(
            "bot_status_bridge.update_order_status", new=AsyncMock()
        ) as status:
            out = await close_sell_after_client_confirm("S1")
        self.assertTrue(out["already_paid"])
        status.assert_not_awaited()

    async def test_closes_operator_pending_with_order_amounts(self):
        from payout_client_receipt import close_sell_after_client_confirm

        order = {
            "order_id": "S1",
            "direction": "sell",
            "status": "OPERATOR_PENDING",
            "crypto_amount": 0.05,
            "fiat_amount": 4800,
            "finance_operator_id": 5,
            "operator_id": 5,
        }
        paid = {**order, "status": "PAID", "operator_crypto_received": 0.05, "operator_fiat_paid_out": 4800}
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=[order, {"amount_rub": 4800}, paid])
        conn.execute = AsyncMock()
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction.return_value = tx
        payroll = AsyncMock()
        with patch("db.get_pool", new=_pool(conn)), patch(
            "bot_status_bridge.update_order_status", new=AsyncMock(return_value=True)
        ), patch(
            "bot_status_bridge.notify_order_completed_for_user", new=AsyncMock()
        ) as notify, patch(
            "operator_payroll_split.ensure_order_payroll_split", new=payroll
        ):
            out = await close_sell_after_client_confirm("S1")
        self.assertTrue(out["ok"])
        self.assertFalse(out["already_paid"])
        notify.assert_awaited_once()
        payroll.assert_awaited_once()
        update_sql = conn.fetchrow.await_args_list[-1].args[0]
        self.assertIn("operator_crypto_received", update_sql)


class SendUserDocumentTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_non_positive_chat(self):
        from telegram_notify import send_user_document

        with patch("telegram_notify.settings") as settings:
            settings.telegram_bot_token = "tok"
            self.assertIsNone(await send_user_document(0, "/tmp/x.pdf", "hi"))


if __name__ == "__main__":
    unittest.main()
