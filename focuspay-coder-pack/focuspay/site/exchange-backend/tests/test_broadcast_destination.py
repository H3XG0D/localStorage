"""Куда слать рассылку: лички бота или один пост в новости."""
from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import ValidationError

import broadcast_service as bs
from routers import broadcast_handlers as bh

MSK = ZoneInfo("Europe/Moscow")


def _job_row(**extra):
    row = {
        "id": 1,
        "sender_role": "admin",
        "sender_id": 1,
        "segment": "all",
        "message_text": "hi",
        "status": "done",
        "total_count": 1,
        "sent_count": 1,
        "failed_count": 0,
    }
    row.update(extra)
    return row


class DestinationValidationTests(unittest.TestCase):
    def test_unknown_destination_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            bs.normalize_destination("channel")
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(ValidationError):
            bh.CreateJobBody(segment="all", text="hi", destination="channel")
        with self.assertRaises(ValidationError):
            bh.CreateScheduleBody(segment="all", text="hi", time_local="10:00", destination="dm")

    def test_omitted_destination_is_bot(self):
        body = bh.CreateJobBody(segment="paid", text="hello")
        self.assertEqual(body.destination, "bot")
        job = bs._job_row(_job_row())
        self.assertEqual(job["destination"], "bot")
        self.assertEqual(job["destination_label"], "Бот")

    def test_news_label(self):
        job = bs._job_row(_job_row(destination="news"))
        self.assertEqual(job["destination"], "news")
        self.assertEqual(job["destination_label"], "Новости")


class PreviewNewsTests(unittest.IsolatedAsyncioTestCase):
    async def test_news_preview_skips_segment_count(self):
        with patch("broadcast_service.count_segment", AsyncMock(return_value=99)) as count:
            out = await bh.preview_segment(bh.PreviewBody(segment="paid", destination="news", text="hi"))
        count.assert_not_called()
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["label"], "Новости FocusPay")
        self.assertEqual(out["destination"], "news")

    async def test_bot_preview_still_counts_segment(self):
        with patch("broadcast_service.count_segment", AsyncMock(return_value=12)) as count:
            out = await bh.preview_segment(bh.PreviewBody(segment="paid", text="hi"))
        count.assert_awaited_once()
        self.assertEqual(out["count"], 12)
        self.assertEqual(out["destination"], "bot")


class ResolveNewsChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_env_wins_over_allowlist(self):
        with patch.object(bs.settings, "telegram_news_chat_id", -100555), patch(
            "broadcast_service.get_pool", AsyncMock()
        ) as pool:
            chat_id = await bs.resolve_news_chat_id()
        self.assertEqual(chat_id, -100555)
        pool.assert_not_called()

    async def test_allowlist_when_env_empty(self):
        class FakeConn:
            async def fetchrow(self, query, *args):
                self.query = query
                return {"chat_id": -100777}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class FakePool:
            def acquire(self):
                return FakeConn()

        with patch.object(bs.settings, "telegram_news_chat_id", 0), patch(
            "broadcast_service.get_pool", AsyncMock(return_value=FakePool())
        ):
            chat_id = await bs.resolve_news_chat_id()
        self.assertEqual(chat_id, -100777)


class NewsJobRunTests(unittest.IsolatedAsyncioTestCase):
    def _pool(self, row):
        holder = {"exec": []}

        class FakeConn:
            async def fetchrow(self, query, *args):
                return row

            async def execute(self, query, *args):
                holder["exec"].append((query, args))

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class FakePool:
            def acquire(self):
                return FakeConn()

        return FakePool(), holder

    async def test_news_sends_once_and_skips_users(self):
        row = {
            "id": 7,
            "status": "running",
            "segment": "paid",
            "destination": "news",
            "message_text": "<b>hello</b>",
            "photo_file_id": None,
            "sticker_ids": None,
        }
        pool, holder = self._pool(row)
        send = AsyncMock(return_value=(True, None))
        recipients = AsyncMock(return_value=[1, 2, 3])
        bs._running_jobs.discard(7)
        with patch("broadcast_service.get_pool", AsyncMock(return_value=pool)), patch(
            "broadcast_service.resolve_news_chat_id", AsyncMock(return_value=-100555)
        ), patch("broadcast_service.send_user_message_detailed", send), patch(
            "broadcast_service.get_recipient_ids", recipients
        ):
            await bs.run_job(7)
        recipients.assert_not_called()
        send.assert_awaited_once()
        self.assertEqual(send.await_args.args[0], -100555)
        self.assertIn("<b>hello</b>", send.await_args.args[1])
        finished = [args for _query, args in holder["exec"] if args and args[0] == 7 and "done" in args]
        self.assertTrue(finished)
        self.assertNotIn(7, bs._running_jobs)

    async def test_unbound_news_fails_without_dms(self):
        row = {
            "id": 8,
            "status": "running",
            "segment": "all",
            "destination": "news",
            "message_text": "hi",
            "photo_file_id": None,
            "sticker_ids": None,
        }
        pool, holder = self._pool(row)
        send = AsyncMock(return_value=(True, None))
        recipients = AsyncMock(return_value=[1])
        bs._running_jobs.discard(8)
        with patch("broadcast_service.get_pool", AsyncMock(return_value=pool)), patch(
            "broadcast_service.resolve_news_chat_id", AsyncMock(return_value=0)
        ), patch("broadcast_service.send_user_message_detailed", send), patch(
            "broadcast_service.get_recipient_ids", recipients
        ):
            await bs.run_job(8)
        send.assert_not_called()
        recipients.assert_not_called()
        blob = " ".join(str(args) for _query, args in holder["exec"])
        self.assertIn("Группа новостей не привязана", blob)
        self.assertNotIn(8, bs._running_jobs)


class CreateNewsJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_job_stores_destination_last(self):
        captured = {}

        class FakeConn:
            async def fetchval(self, query, *args):
                return 0

            async def fetchrow(self, query, *args):
                captured["query"] = query
                captured["args"] = args
                return {
                    "id": 4,
                    "sender_role": args[0],
                    "sender_id": args[1],
                    "sender_label": args[2],
                    "segment": args[3],
                    "message_text": args[4],
                    "photo_file_id": args[5],
                    "status": "pending",
                    "total_count": 0,
                    "sent_count": 0,
                    "failed_count": 0,
                    "sticker_ids": args[6],
                    "sticker_mode": args[7],
                    "sticker_status": args[8],
                    "scheduled_at": args[9],
                    "schedule_id": args[10],
                    "destination": args[11],
                    "created_at": datetime(2026, 8, 21, 10, 0, tzinfo=MSK),
                    "started_at": None,
                    "finished_at": None,
                    "error_summary": None,
                }

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class FakePool:
            def acquire(self):
                return FakeConn()

        with patch("broadcast_service.get_pool", AsyncMock(return_value=FakePool())), patch(
            "broadcast_service.kick_worker"
        ):
            job = await bs.create_job(
                sender_role="admin",
                sender_id=1,
                sender_label="a",
                segment="all",
                message_text="post",
                destination="news",
            )
        self.assertEqual(captured["args"][11], "news")
        self.assertIn("destination", captured["query"])
        self.assertEqual(job["destination"], "news")
        self.assertEqual(captured["args"][9], None)


if __name__ == "__main__":
    unittest.main()
