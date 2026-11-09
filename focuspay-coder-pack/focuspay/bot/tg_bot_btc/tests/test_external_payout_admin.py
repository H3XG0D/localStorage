"""Тесты админ-кнопок вывода внештатников (extwd)."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import config_rates
from services.callback_signatures import (
    sign_external_payout,
    verify_external_payout_signature,
)
from services.payout_pending_store import (
    clear_pending,
    clear_user_data_pending,
    lookup_pending,
    save_pending,
    sync_user_data_pending,
)


class ExternalPayoutSignatureTests(unittest.TestCase):
    def test_extwd_sig_roundtrip(self):
        with patch.object(config_rates, "CALLBACK_SECRET", "extwd-secret"):
            sig = sign_external_payout(17)
            self.assertTrue(verify_external_payout_signature(17, sig))
            self.assertFalse(verify_external_payout_signature(18, sig))
            self.assertFalse(verify_external_payout_signature(17, "bad"))


class ExternalPayoutPendingStoreTests(unittest.TestCase):
    def test_extwd_receipt_kind(self):
        bot_data: dict = {}
        save_pending(
            bot_data,
            kind="extwd_receipt",
            chat_id=-1001,
            user_id=42,
            prompt_message_id=10,
            card_message_id=9,
            payload={"payout_id": 55},
        )
        hit = lookup_pending(
            bot_data,
            chat_id=-1001,
            user_id=42,
            reply_to_message_id=10,
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["kind"], "extwd_receipt")
        self.assertEqual(hit["payout_id"], 55)
        clear_pending(bot_data, hit)
        self.assertIsNone(lookup_pending(bot_data, chat_id=-1001, user_id=42))

    def test_sync_user_data_extwd(self):
        ctx = MagicMock()
        ctx.user_data = {}
        sync_user_data_pending(
            ctx,
            kind="extwd_receipt",
            chat_id=-1,
            user_id=1,
            card_message_id=2,
            payload={"payout_id": 9},
        )
        self.assertEqual(ctx.user_data["pending_extwd_receipt"]["payout_id"], 9)
        clear_user_data_pending(ctx, "extwd_receipt")
        self.assertNotIn("pending_extwd_receipt", ctx.user_data)


class ExternalPayoutAdminProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_payout_paid_ok(self):
        from services.external_payout_admin import process_payout_paid

        row = {
            "id": 3,
            "exchanger_id": 7,
            "gross_usd": 20.0,
            "fee_usd": 3.0,
            "net_usd": 17.0,
            "status": "pending",
            "tx_hash": None,
            "receipt_file": None,
        }
        updated = {**row, "status": "paid", "receipt_file": "extwd_3.pdf"}

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[row, updated])
        conn.fetchval = AsyncMock(return_value=100.0)
        conn.execute = AsyncMock()
        tx = AsyncMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=tx)

        pool = MagicMock()
        acquire_cm = AsyncMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=None)
        pool.acquire = MagicMock(return_value=acquire_cm)

        with patch("services.external_payout_admin.get_pool", AsyncMock(return_value=pool)):
            ok, err, payout = await process_payout_paid(
                3,
                completed_by="telegram:1",
                receipt_file="extwd_3.pdf",
            )
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(payout["status"], "paid")
        self.assertEqual(conn.execute.await_count, 1)

    async def test_process_payout_rejected_ok(self):
        from services.external_payout_admin import process_payout_rejected

        updated = {"id": 4, "status": "rejected", "note": "[rejected by tg]"}
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=updated)
        conn.fetchval = AsyncMock()

        pool = MagicMock()
        acquire_cm = AsyncMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=None)
        pool.acquire = MagicMock(return_value=acquire_cm)

        with patch("services.external_payout_admin.get_pool", AsyncMock(return_value=pool)):
            ok, err, payout = await process_payout_rejected(
                4, rejected_by="telegram:1"
            )
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(payout["status"], "rejected")

    async def test_process_payout_paid_insufficient(self):
        from services.external_payout_admin import process_payout_paid

        row = {
            "id": 3,
            "exchanger_id": 7,
            "gross_usd": 20.0,
            "fee_usd": 3.0,
            "net_usd": 17.0,
            "status": "pending",
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.fetchval = AsyncMock(return_value=5.0)
        conn.execute = AsyncMock()
        tx = AsyncMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=tx)

        pool = MagicMock()
        acquire_cm = AsyncMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=None)
        pool.acquire = MagicMock(return_value=acquire_cm)

        with patch("services.external_payout_admin.get_pool", AsyncMock(return_value=pool)):
            ok, err, _ = await process_payout_paid(3, completed_by="telegram:1")
        self.assertFalse(ok)
        self.assertEqual(err, "insufficient_balance")
        conn.execute.assert_not_awaited()
