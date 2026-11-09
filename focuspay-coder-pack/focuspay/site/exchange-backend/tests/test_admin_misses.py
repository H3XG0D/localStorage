from datetime import datetime, timedelta, timezone
from unittest import TestCase
from zoneinfo import ZoneInfo

from miss_unique import as_utc, dedupe_miss_rows


class _Row(dict):
    pass


class DedupeMissRowsTests(TestCase):
    def test_keeps_first_retry_inside_hour_dropped(self):
        t0 = datetime(2026, 8, 19, 14, 0, tzinfo=timezone.utc)
        rows = [
            _Row(user_id=1, created_at=t0, fiat_amount=5000, direction="buy"),
            _Row(user_id=1, created_at=t0 + timedelta(minutes=5), fiat_amount=5000, direction="buy"),
            _Row(user_id=1, created_at=t0 + timedelta(minutes=15), fiat_amount=8000, direction="buy"),
            _Row(user_id=1, created_at=t0 + timedelta(minutes=30), fiat_amount=5000, direction="buy"),
            _Row(user_id=2, created_at=t0 + timedelta(minutes=10), fiat_amount=2000, direction="sell"),
        ]
        kept = dedupe_miss_rows(rows)
        self.assertEqual([r["user_id"] for r in kept], [1, 2])
        self.assertEqual(kept[0]["fiat_amount"], 5000)

    def test_keeps_same_client_after_hour(self):
        t0 = datetime(2026, 8, 19, 14, 0, tzinfo=timezone.utc)
        rows = [
            _Row(user_id=7, created_at=t0, fiat_amount=1000),
            _Row(user_id=7, created_at=t0 + timedelta(hours=1), fiat_amount=1000),
        ]
        kept = dedupe_miss_rows(rows)
        self.assertEqual(len(kept), 2)

    def test_retry_after_midnight_uses_lookback(self):
        first = datetime(2026, 8, 18, 23, 50, tzinfo=ZoneInfo("Europe/Moscow"))
        retry = datetime(2026, 8, 19, 0, 10, tzinfo=ZoneInfo("Europe/Moscow"))
        start = datetime(2026, 8, 19, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        rows = [
            _Row(user_id=1, created_at=first, fiat_amount=5000),
            _Row(user_id=1, created_at=retry, fiat_amount=9000),
        ]
        start_utc = start.astimezone(timezone.utc)
        kept = [
            row
            for row in dedupe_miss_rows(rows)
            if as_utc(row["created_at"]) is not None and as_utc(row["created_at"]) >= start_utc
        ]
        self.assertEqual(kept, [])
