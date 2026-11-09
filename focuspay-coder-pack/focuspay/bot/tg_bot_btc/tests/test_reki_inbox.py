"""Разбор «PDF не пройден» и поиск заявки — без Telethon."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

from services.reki_inbox import find_reki_order_id, poll_reki_inbox_once  # noqa: E402


def _pool(row):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=row)
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire)
    return pool, conn


class FindRekiOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_ticket_uuid_wins(self):
        pool, conn = _pool({"order_id": "ORD-1"})
        with patch("services.db.get_pool", new=AsyncMock(return_value=pool)), patch(
            "services.db.get_order", new=AsyncMock()
        ) as get_order:
            found = await find_reki_order_id(
                "ce8c63d1-5230-47d6-b8e7-4610d4b6991b", "29166406"
            )
        self.assertEqual(found, "ORD-1")
        get_order.assert_not_awaited()
        sql = conn.fetchrow.await_args.args[0]
        self.assertIn("manual_requisite_tickets", sql)

    async def test_client_ref_is_our_order_id(self):
        pool, conn = _pool(None)
        with patch("services.db.get_pool", new=AsyncMock(return_value=pool)), patch(
            "services.db.get_order",
            new=AsyncMock(return_value={"order_id": "29166406"}),
        ):
            found = await find_reki_order_id(None, "29166406")
        self.assertEqual(found, "29166406")
        self.assertEqual(conn.fetchrow.await_count, 0)


class InboxPollTests(unittest.IsolatedAsyncioTestCase):
    async def test_pdf_failed_asks_for_video(self):
        import services.reki_inbox as inbox

        inbox._seen.clear()
        inbox._seen_order.clear()
        text = (
            "⚠️ Проверка pdf не пройдена\n"
            "🆔 ID заявки: ce8c63d1-5230-47d6-b8e7-4610d4b6991b\n"
            "🆔 Ваш id заявки: 29166406\n"
            "📄 Необходимо запросить у клиента видео подтверждение перевода."
        )
        ask = AsyncMock(return_value=(True, "ok"))
        with patch(
            "services.reki_request.fetch_recent_incoming_texts",
            new=AsyncMock(return_value=[(15, text)]),
        ), patch(
            "services.reki_inbox.find_reki_order_id",
            new=AsyncMock(return_value="ORD-9"),
        ), patch(
            "services.video_receipt_request.request_client_receipt_check",
            new=ask,
        ):
            asked = await poll_reki_inbox_once()
        self.assertEqual(asked, 1)
        ask.assert_awaited_once()
        self.assertEqual(ask.await_args.args[0], "ORD-9")
        self.assertEqual(ask.await_args.args[1], 3)
        self.assertEqual(ask.await_args.kwargs["source"], "reki_inbox")
