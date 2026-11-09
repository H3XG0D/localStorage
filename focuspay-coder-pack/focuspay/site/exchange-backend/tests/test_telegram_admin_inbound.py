"""Тесты синхронизации ответов оператора из Telegram."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from chat_service import admin_send_from_telegram, _needs_reply


class NeedsReplyTests(unittest.TestCase):
    def test_buyer_and_exchanger_need_reply(self):
        self.assertTrue(_needs_reply("buyer"))
        self.assertTrue(_needs_reply("exchanger"))
        self.assertFalse(_needs_reply("admin"))
        self.assertFalse(_needs_reply(None))


class AdminSendFromTelegramTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_admin_reply_and_clears_unread(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        conn.fetchrow = AsyncMock(
            side_effect=[
                {
                    "id": 5,
                    "source": "telegram",
                    "telegram_dm_chat_id": 1001,
                    "business_connection_id": "conn-1",
                },
                {
                    "id": 99,
                    "thread_id": 5,
                    "sender_role": "admin",
                    "body": "Привет",
                    "message_type": "text",
                    "attachment_id": None,
                    "attachment_filename": None,
                    "created_at": None,
                },
            ]
        )
        conn.execute = AsyncMock()

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        import chat_service

        old_pool = chat_service.get_pool
        try:
            chat_service.get_pool = AsyncMock(return_value=pool)
            with patch(
                "exchanger_chat_escalation.clear_exchanger_escalation",
                new=AsyncMock(),
            ):
                msg = await admin_send_from_telegram(
                    connection_id="conn-1",
                    chat_id=1001,
                    user_id=42,
                    message_id=777,
                    body="Привет",
                )
        finally:
            chat_service.get_pool = old_pool

        self.assertIsNotNone(msg)
        self.assertEqual(msg["sender_role"], "admin")
        self.assertEqual(msg["body"], "Привет")
        execute_sql = " ".join(c.args[0] for c in conn.execute.await_args_list)
        self.assertIn("admin_unread = 0", execute_sql)

    async def test_duplicate_returns_none(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=55)

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        import chat_service

        old_pool = chat_service.get_pool
        try:
            chat_service.get_pool = AsyncMock(return_value=pool)
            msg = await admin_send_from_telegram(
                connection_id="conn-1",
                chat_id=1001,
                user_id=42,
                message_id=777,
                body="dup",
            )
        finally:
            chat_service.get_pool = old_pool

        self.assertIsNone(msg)


class TelegramStickerInboundTests(unittest.IsolatedAsyncioTestCase):
    def _pool(self, conn):
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        return pool

    async def test_buyer_sticker_from_telegram_is_saved(self):
        import chat_service

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        conn.execute = AsyncMock()
        insert = AsyncMock(return_value={"id": 1, "sender_role": "buyer", "message_type": "sticker"})
        with patch.object(chat_service, "get_pool", new=AsyncMock(return_value=self._pool(conn))), patch.object(
            chat_service, "_touch_bot_user", new=AsyncMock()
        ), patch.object(
            chat_service, "_get_or_create_telegram_thread", new=AsyncMock(return_value={"id": 5})
        ), patch.object(chat_service, "_insert_message", new=insert), patch.object(
            chat_service, "_msg_row", side_effect=lambda r: dict(r)
        ), patch("chat_auto_reply.maybe_reply_che_kogo", new=AsyncMock()):
            msg = await chat_service.buyer_send_from_telegram(
                connection_id="conn-1",
                chat_id=1001,
                user_id=42,
                message_id=778,
                body="😀",
                attachment_id="att1",
                message_type="sticker",
                sticker_file_id="CAACAg",
                sticker_emoji="😀",
                sticker_set_name="focus_pack",
            )

        self.assertEqual(msg["message_type"], "sticker")
        kw = insert.await_args.kwargs
        self.assertEqual(kw["message_type"], "sticker")
        self.assertEqual(kw["sticker_file_id"], "CAACAg")
        self.assertEqual(kw["sticker_set_name"], "focus_pack")
        self.assertEqual(kw["attachment_id"], "att1")
        self.assertEqual(kw["body"], "😀")

    async def test_buyer_text_from_telegram_accepts_empty_sticker_fields(self):
        import chat_service

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        insert = AsyncMock(return_value={"id": 2, "sender_role": "buyer", "message_type": "text"})
        with patch.object(chat_service, "get_pool", new=AsyncMock(return_value=self._pool(conn))), patch.object(
            chat_service, "_touch_bot_user", new=AsyncMock()
        ), patch.object(
            chat_service, "_get_or_create_telegram_thread", new=AsyncMock(return_value={"id": 5})
        ), patch.object(chat_service, "_insert_message", new=insert), patch.object(
            chat_service, "_msg_row", side_effect=lambda r: dict(r)
        ), patch("chat_auto_reply.maybe_reply_che_kogo", new=AsyncMock()):
            await chat_service.buyer_send_from_telegram(
                connection_id="conn-1",
                chat_id=1001,
                user_id=42,
                message_id=779,
                body="Привет",
                message_type="image",
                sticker_file_id=None,
                sticker_emoji=None,
                sticker_set_name=None,
            )

        self.assertEqual(insert.await_args.kwargs["message_type"], "text")
        self.assertEqual(insert.await_args.kwargs["body"], "Привет")


if __name__ == "__main__":
    unittest.main()
