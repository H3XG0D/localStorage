"""Scheduled and recurring broadcast queue."""
from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from fastapi import HTTPException

import broadcast_service as bs

MSK = ZoneInfo("Europe/Moscow")


class CoerceScheduledAtTests(unittest.TestCase):
    def test_none_is_asap(self):
        self.assertIsNone(bs.coerce_scheduled_at(None))

    def test_naive_is_moscow(self):
        now = datetime(2026, 8, 21, 7, 0, tzinfo=MSK)
        slot = bs.coerce_scheduled_at(datetime(2026, 8, 21, 12, 0), now=now)
        self.assertEqual(slot.astimezone(MSK).hour, 12)
        self.assertEqual(slot.astimezone(MSK).date(), date(2026, 8, 21))

    def test_too_soon_rejected(self):
        now = datetime(2026, 8, 21, 12, 0, tzinfo=MSK)
        with self.assertRaises(HTTPException) as ctx:
            bs.coerce_scheduled_at(datetime(2026, 8, 21, 12, 0, 30, tzinfo=MSK), now=now)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_too_far_rejected(self):
        now = datetime(2026, 8, 21, 12, 0, tzinfo=MSK)
        with self.assertRaises(HTTPException) as ctx:
            bs.coerce_scheduled_at(datetime(2026, 10, 1, 12, 0, tzinfo=MSK), now=now)
        self.assertEqual(ctx.exception.status_code, 400)


class JobDueTests(unittest.TestCase):
    def test_pending_without_slot_is_due(self):
        self.assertTrue(bs.job_is_due("pending", None))

    def test_future_slot_not_due(self):
        now = datetime(2026, 8, 21, 12, 0, tzinfo=MSK)
        later = now + timedelta(hours=2)
        self.assertFalse(bs.job_is_due("pending", later, now=now))

    def test_past_slot_due(self):
        now = datetime(2026, 8, 21, 12, 0, tzinfo=MSK)
        self.assertTrue(bs.job_is_due("pending", now - timedelta(minutes=1), now=now))

    def test_running_not_due(self):
        self.assertFalse(bs.job_is_due("running", None))


class RecurringActionTests(unittest.TestCase):
    def test_before_slot_waits(self):
        now = datetime(2026, 8, 17, 8, 59, tzinfo=MSK)  # Monday
        self.assertEqual(
            bs.recurring_action(now, time_local=time(9, 0), days_of_week=[1], last_enqueued_date=None),
            "wait",
        )

    def test_within_window_enqueues(self):
        now = datetime(2026, 8, 17, 9, 30, tzinfo=MSK)
        self.assertEqual(
            bs.recurring_action(now, time_local=time(9, 0), days_of_week=[1], last_enqueued_date=None),
            "enqueue",
        )

    def test_same_day_idempotent(self):
        now = datetime(2026, 8, 17, 9, 30, tzinfo=MSK)
        self.assertEqual(
            bs.recurring_action(
                now,
                time_local=time(9, 0),
                days_of_week=[1],
                last_enqueued_date=date(2026, 8, 17),
            ),
            "wait",
        )

    def test_missed_window_skips(self):
        now = datetime(2026, 8, 17, 12, 1, tzinfo=MSK)
        self.assertEqual(
            bs.recurring_action(now, time_local=time(9, 0), days_of_week=[1], last_enqueued_date=None),
            "skip_missed",
        )

    def test_wrong_weekday_waits(self):
        now = datetime(2026, 8, 18, 9, 30, tzinfo=MSK)  # Tuesday
        self.assertEqual(
            bs.recurring_action(now, time_local=time(9, 0), days_of_week=[1], last_enqueued_date=None),
            "wait",
        )


class CreateScheduledJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_future_slot_does_not_run_immediately(self):
        from unittest.mock import patch
        captured = {}
        now = datetime(2026, 8, 21, 10, 0, tzinfo=MSK)
        slot = datetime(2026, 8, 21, 14, 0, tzinfo=MSK)

        class FakeConn:
            async def fetchval(self, query, *args):
                return 0

            async def fetchrow(self, query, *args):
                captured["args"] = args
                return {
                    "id": 3,
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
                    "created_at": now,
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
        ) as kick, patch("broadcast_service.run_job", AsyncMock()) as run_job:
            job = await bs.create_job(
                sender_role="operator",
                sender_id=2,
                sender_label="op",
                segment="all",
                message_text="later",
                scheduled_at=slot,
                require_future_slot=True,
                now=now,
            )
        self.assertEqual(job["status"], "pending")
        self.assertIsNotNone(job["scheduled_at"])
        kick.assert_called_once()
        run_job.assert_not_called()
        self.assertIsNotNone(captured["args"][9])


class PatchJobGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_started_job(self):
        started = datetime(2026, 8, 21, 10, 0, tzinfo=MSK)

        async def fake_get(job_id):
            return {
                "id": job_id,
                "status": "pending",
                "started_at": started.isoformat(),
                "message_text": "hi",
                "photo_file_id": None,
            }

        with patch("broadcast_service.get_job", fake_get):
            with self.assertRaises(HTTPException) as ctx:
                await bs.patch_job(8, text="new")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_updates_text_and_segment_of_pending(self):
        captured = {}

        async def fake_get(job_id):
            return {
                "id": job_id,
                "status": "pending",
                "started_at": None,
                "message_text": "old",
                "photo_file_id": None,
                "sticker_ids": [],
                "sticker_mode": "none",
            }

        class FakeConn:
            async def fetchrow(self, query, *args):
                captured["query"] = query
                captured["args"] = args
                return {
                    "id": 8,
                    "sender_role": "operator",
                    "sender_id": 1,
                    "sender_label": "op",
                    "segment": "paid",
                    "message_text": "new text",
                    "photo_file_id": None,
                    "status": "pending",
                    "total_count": 0,
                    "sent_count": 0,
                    "failed_count": 0,
                    "sticker_ids": None,
                    "sticker_mode": "none",
                    "sticker_status": "none",
                    "scheduled_at": None,
                    "schedule_id": None,
                    "created_at": None,
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

        with patch("broadcast_service.get_job", fake_get), patch(
            "broadcast_service.get_pool", AsyncMock(return_value=FakePool())
        ), patch("broadcast_service.kick_worker"):
            job = await bs.patch_job(8, text="new text", segment="paid")
        self.assertEqual(job["message_text"], "new text")
        self.assertIn("message_text", captured["query"])
        self.assertIn("segment", captured["query"])


class StartNextIdleTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_in_process_running(self):
        bs._running_jobs.add(99)
        try:
            with patch("broadcast_service.claim_next_job", AsyncMock()) as claim:
                await bs.start_next_if_idle()
            claim.assert_not_called()
        finally:
            bs._running_jobs.discard(99)

    async def test_does_not_start_second_when_claim_empty(self):
        with patch("broadcast_service.claim_next_job", AsyncMock(return_value=None)), patch(
            "broadcast_service.asyncio.create_task"
        ) as create_task:
            await bs.start_next_if_idle()
        create_task.assert_not_called()


class EnqueueDueSchedulesTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueues_once_and_marks_day(self):
        now = datetime(2026, 8, 17, 9, 15, tzinfo=MSK)
        schedule_row = {
            "id": 4,
            "sender_role": "admin",
            "sender_id": 1,
            "sender_label": "a",
            "segment": "all",
            "message_text": "daily",
            "photo_file_id": None,
            "sticker_ids": None,
            "sticker_mode": "none",
            "sticker_status": "none",
            "time_local": time(9, 0),
            "days_of_week": [1],
            "timezone": "Europe/Moscow",
            "enabled": True,
            "last_enqueued_date": None,
            "created_at": now,
            "updated_at": now,
        }

        class FakeConn:
            async def fetch(self, query, *args):
                return [schedule_row]

            async def execute(self, query, *args):
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class FakePool:
            def acquire(self):
                return FakeConn()

        with patch("broadcast_service.get_pool", AsyncMock(return_value=FakePool())), patch(
            "broadcast_service.create_job", AsyncMock()
        ) as create_job, patch(
            "broadcast_service._mark_schedule_enqueued", AsyncMock()
        ) as mark:
            n = await bs.enqueue_due_schedules(now=now)
        self.assertEqual(n, 1)
        create_job.assert_called_once()
        mark.assert_called_once()
        self.assertEqual(mark.call_args.args[1], date(2026, 8, 17))

    async def test_missed_window_marks_without_job(self):
        now = datetime(2026, 8, 17, 12, 30, tzinfo=MSK)
        schedule_row = {
            "id": 5,
            "sender_role": "operator",
            "sender_id": 2,
            "sender_label": "op",
            "segment": "paid",
            "message_text": "late",
            "photo_file_id": None,
            "sticker_ids": None,
            "sticker_mode": "none",
            "sticker_status": "none",
            "time_local": time(9, 0),
            "days_of_week": [1],
            "timezone": "Europe/Moscow",
            "enabled": True,
            "last_enqueued_date": None,
            "created_at": now,
            "updated_at": now,
        }

        class FakeConn:
            async def fetch(self, query, *args):
                return [schedule_row]

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class FakePool:
            def acquire(self):
                return FakeConn()

        with patch("broadcast_service.get_pool", AsyncMock(return_value=FakePool())), patch(
            "broadcast_service.create_job", AsyncMock()
        ) as create_job, patch(
            "broadcast_service._mark_schedule_enqueued", AsyncMock()
        ) as mark:
            n = await bs.enqueue_due_schedules(now=now)
        self.assertEqual(n, 0)
        create_job.assert_not_called()
        mark.assert_called_once()


class RecoverStaleTests(unittest.TestCase):
    def test_recover_sql_only_running(self):
        import inspect

        src = inspect.getsource(bs.recover_stale_jobs)
        self.assertIn("status = 'running'", src)
        self.assertNotIn("pending", src)


if __name__ == "__main__":
    unittest.main()
