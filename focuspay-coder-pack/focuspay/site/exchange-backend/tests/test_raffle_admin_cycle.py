"""FocusLucky admin: next cycle, schedule, campaign history. Fake DB."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

from casino_raffle import resolve_schedule
import raffle_service as rs


MSK = timezone(timedelta(hours=3))


class _Tx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return False


class FakeConn:
    def __init__(self, *, latest_id=2, campaign=None, insert_row=None, winner_rows=None, campaigns=None):
        self.latest_id = latest_id
        self.campaign = campaign or {}
        self.insert_row = insert_row
        self.winner_rows = winner_rows or []
        self.campaigns = campaigns or []
        self.sql: list[tuple[str, str]] = []
        self.deleted_winners = False
        self.updated_old = False

    def transaction(self):
        return _Tx(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def _note(self, kind: str, sql: str) -> str:
        text = " ".join(sql.split())
        self.sql.append((kind, text))
        return text

    async def fetchval(self, sql, *args):
        text = self._note("fetchval", sql)
        if "ORDER BY id DESC LIMIT 1 FOR UPDATE" in text:
            return self.latest_id
        if "to_regclass" in text:
            return "raffle_campaigns"
        return None

    async def fetchrow(self, sql, *args):
        text = self._note("fetchrow", sql)
        if "INSERT INTO raffle_campaigns" in text:
            return self.insert_row
        return self.campaign

    async def execute(self, sql, *args):
        text = self._note("execute", sql)
        if "DELETE FROM raffle_winners" in text:
            self.deleted_winners = True
        if "UPDATE raffle_campaigns" in text and "status = 'closed'" in text:
            self.updated_old = True
        return "UPDATE 1"

    async def fetch(self, sql, *args):
        text = self._note("fetch", sql)
        if "FROM raffle_winners" in text:
            return self.winner_rows
        if "FROM raffle_campaigns" in text:
            return self.campaigns
        return []


class FakePool:
    def __init__(self, conn: FakeConn):
        self.conn = conn

    def acquire(self):
        return self.conn


class ResolveScheduleTests(unittest.TestCase):
    def test_naive_iso_is_msk_and_ends_one_second_before_draw(self):
        start, draw, ends = resolve_schedule(
            starts_at="2026-09-01T12:00",
            draw_at="2026-09-10T20:00",
        )
        self.assertEqual(start.tzinfo, timezone.utc)
        self.assertEqual(draw.hour, 17)
        self.assertEqual(ends, draw - timedelta(seconds=1))
        self.assertLess(start, draw)

    def test_start_must_be_before_draw(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_schedule(
                starts_at="2026-09-10T20:00:00+03:00",
                draw_at="2026-09-10T20:00:00+03:00",
            )
        self.assertIn("раньше", str(ctx.exception))

    def test_keeps_existing_start_when_only_draw_sent(self):
        existing = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
        start, draw, _ends = resolve_schedule(
            draw_at="2026-09-10T20:00:00+03:00",
            existing_starts=existing,
        )
        self.assertEqual(start, existing)
        self.assertEqual(draw.day, 10)


class MergeHistoryTests(unittest.TestCase):
    def test_attaches_winners_and_marks_current(self):
        campaigns = [
            {
                "id": 5,
                "title": "FocusLucky",
                "month_label": "сентябрь 2026",
                "status": "draft",
                "starts_at": datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
                "draw_at": datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc),
                "ends_at": datetime(2026, 10, 1, 16, 59, 59, tzinfo=timezone.utc),
                "prize_pool_rub": 14500,
                "ticket_count": 0,
            },
            {
                "id": 4,
                "title": "FocusLucky",
                "month_label": "август 2026",
                "status": "drawn",
                "starts_at": "2026-08-01T00:00:00+00:00",
                "draw_at": "2026-08-31T17:00:00+00:00",
                "ends_at": "2026-08-31T16:59:59+00:00",
                "prize_pool_rub": 8000,
                "ticket_count": 100,
            },
        ]
        winners = [
            {"campaign_id": 4, "place": 1, "user_id": 940001, "username": "alice", "prize_rub": 5000, "payout_status": "paid"},
            {"campaign_id": 4, "place": 2, "user_id": 940002, "username": None, "prize_rub": 3000, "status": "paid"},
        ]
        out = rs.merge_admin_campaign_history(campaigns, winners, current_id=5)
        self.assertEqual(out[0]["campaign_id"], 5)
        self.assertTrue(out[0]["is_current"])
        self.assertEqual(out[0]["winner_count"], 0)
        self.assertEqual(out[1]["winner_count"], 2)
        self.assertEqual(out[1]["winners"][0]["username"], "alice")
        self.assertEqual(out[1]["winners"][1]["payout_status"], "paid")
        self.assertFalse(out[1]["is_current"])


class StartNextTests(unittest.IsolatedAsyncioTestCase):
    async def test_drawn_with_paid_winners_inserts_draft_and_keeps_winners(self):
        old = {
            "id": 2,
            "status": "drawn",
            "title": "FocusLucky",
            "info_text": "свой",
            "how_to_text": "как",
            "spin_interval_seconds": 20,
            "pre_show_seconds": 15,
            "notify_minutes_before": 15,
        }
        inserted = {
            "id": 3,
            "status": "draft",
            "slug": "focuslucky-next",
            "prize_pool_rub": 14500,
        }
        conn = FakeConn(latest_id=2, campaign=old, insert_row=inserted)
        with patch("raffle_service.get_pool", AsyncMock(return_value=FakePool(conn))):
            row = await rs.start_next_campaign(2)
        self.assertEqual(row["id"], 3)
        self.assertEqual(row["status"], "draft")
        self.assertFalse(conn.deleted_winners)
        self.assertFalse(conn.updated_old)
        insert_sql = next(sql for kind, sql in conn.sql if kind == "fetchrow" and "INSERT INTO raffle_campaigns" in sql)
        self.assertIn("'draft'", insert_sql)
        self.assertIn("info_text", insert_sql)
        self.assertIn("spin_interval_seconds", insert_sql)
        self.assertNotIn("DELETE FROM raffle_winners", " ".join(sql for _, sql in conn.sql))

    async def test_insert_skips_admin_text_columns_when_table_lacks_them(self):
        old = {
            "id": 2,
            "status": "drawn",
            "title": "FocusLucky",
            "spin_interval_seconds": 12,
            "pre_show_seconds": 8,
            "notify_minutes_before": 15,
        }
        conn = FakeConn(
            latest_id=2,
            campaign=old,
            insert_row={"id": 3, "status": "draft", "slug": "next"},
        )
        with patch("raffle_service.get_pool", AsyncMock(return_value=FakePool(conn))):
            await rs.start_next_campaign(2)
        insert_sql = next(sql for kind, sql in conn.sql if kind == "fetchrow" and "INSERT INTO raffle_campaigns" in sql)
        self.assertNotIn("info_text", insert_sql)
        self.assertNotIn("how_to_text", insert_sql)
        self.assertIn("spin_interval_seconds", insert_sql)

    async def test_refuses_when_latest_is_not_drawn(self):
        conn = FakeConn(latest_id=2, campaign={"id": 2, "status": "active"})
        with patch("raffle_service.get_pool", AsyncMock(return_value=FakePool(conn))):
            with self.assertRaises(ValueError) as ctx:
                await rs.start_next_campaign(2)
        self.assertIn("проведённого", str(ctx.exception))
        self.assertFalse(conn.deleted_winners)


class UpdateScheduleLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_drawn_is_409_message(self):
        conn = FakeConn(
            campaign={
                "id": 2,
                "status": "drawn",
                "starts_at": datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
                "draw_at": datetime(2026, 9, 1, 21, 0, tzinfo=timezone.utc),
            }
        )
        with patch("db.get_pool", AsyncMock(return_value=FakePool(conn))):
            with self.assertRaises(ValueError) as ctx:
                await rs.raffle_show.update_schedule(
                    2,
                    starts_at="2026-09-02T12:00:00+03:00",
                    draw_at="2026-09-20T20:00:00+03:00",
                )
        self.assertIn("шоу", str(ctx.exception))
        self.assertFalse(any("SET starts_at" in sql for _, sql in conn.sql))

    async def test_active_writes_starts_and_draw(self):
        conn = FakeConn(
            campaign={
                "id": 3,
                "status": "active",
                "starts_at": datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
                "draw_at": datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc),
            }
        )
        with patch("db.get_pool", AsyncMock(return_value=FakePool(conn))):
            out = await rs.raffle_show.update_schedule(
                3,
                starts_at="2026-09-02T12:00:00+03:00",
                draw_at="2026-09-20T20:00:00+03:00",
            )
        self.assertIn("starts_at", out)
        self.assertIn("draw_at", out)
        update_sql = next(sql for kind, sql in conn.sql if kind == "execute" and "SET starts_at" in sql)
        self.assertIn("ends_at", update_sql)


class NextCycleTimesTests(unittest.TestCase):
    def test_draw_is_thirty_days_later_at_2000_msk(self):
        now = datetime(2026, 9, 1, 0, 51, tzinfo=MSK)
        starts, ends, draw, label, slug = rs.next_cycle_times(now=now)
        self.assertEqual(starts, now)
        self.assertEqual(draw.day, 1)
        self.assertEqual(draw.month, 10)
        self.assertEqual(draw.hour, 20)
        self.assertEqual(ends, draw - timedelta(seconds=1))
        self.assertEqual(label, "сентябрь 2026")
        self.assertTrue(slug.startswith("focuslucky-20260901"))


if __name__ == "__main__":
    unittest.main()
