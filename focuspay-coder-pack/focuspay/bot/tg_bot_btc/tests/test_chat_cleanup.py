"""Кого авточистка оставляет в focus-чате, без сети и без Telethon."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from services.chat_cleanup import (
    REASON_DELETED,
    REASON_LONG_AGO,
    REASON_OFFLINE,
    STALE_DAYS,
    cleanup_reason,
    describe_presence,
    is_clean_command,
    summary_line,
)


def _now() -> datetime:
    return datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def _reason(**kwargs: object) -> str | None:
    payload = {
        "user_id": 10,
        "is_bot": False,
        "deleted": False,
        "presence": None,
        "was_online": None,
        "protected_ids": set(),
        "now": _now(),
    }
    payload.update(kwargs)
    return cleanup_reason(**payload)  # type: ignore[arg-type]


class _Status:
    def __init__(self, was_online: datetime | None = None) -> None:
        self.was_online = was_online


class UserStatusOnline(_Status):
    pass


class UserStatusRecently(_Status):
    pass


class UserStatusLastWeek(_Status):
    pass


class UserStatusLastMonth(_Status):
    pass


class UserStatusEmpty(_Status):
    pass


class UserStatusOffline(_Status):
    pass


class UserStatusWeird(_Status):
    pass


class DescribePresenceTests(unittest.TestCase):
    def test_known_buckets(self):
        self.assertEqual(describe_presence(UserStatusOnline()), ("online", None))
        self.assertEqual(describe_presence(UserStatusRecently()), ("recently", None))
        self.assertEqual(describe_presence(UserStatusLastWeek()), ("last_week", None))
        self.assertEqual(describe_presence(UserStatusLastMonth()), ("last_month", None))
        self.assertEqual(describe_presence(UserStatusEmpty()), ("empty", None))
        self.assertEqual(describe_presence(None), (None, None))
        self.assertEqual(describe_presence(UserStatusWeird()), (None, None))

    def test_offline_keeps_exact_time(self):
        seen = _now() - timedelta(days=40)
        self.assertEqual(describe_presence(UserStatusOffline(seen)), ("offline", seen))

    def test_offline_without_datetime_has_no_date(self):
        self.assertEqual(describe_presence(UserStatusOffline(None)), ("offline", None))


class CleanupReasonTests(unittest.TestCase):
    def test_recent_buckets_stay(self):
        for presence in ("online", "recently", "last_week", "last_month"):
            self.assertIsNone(_reason(presence=presence))

    def test_missing_status_stays(self):
        self.assertIsNone(_reason(presence=None))

    def test_long_ago_goes(self):
        self.assertEqual(_reason(presence="empty"), REASON_LONG_AGO)

    def test_exact_date_older_than_30_days_goes(self):
        seen = _now() - timedelta(days=STALE_DAYS, seconds=1)
        self.assertEqual(
            _reason(presence="offline", was_online=seen),
            REASON_OFFLINE,
        )

    def test_exact_date_at_30_days_stays(self):
        seen = _now() - timedelta(days=STALE_DAYS)
        self.assertIsNone(_reason(presence="offline", was_online=seen))

    def test_exact_date_within_month_stays(self):
        seen = _now() - timedelta(days=29)
        self.assertIsNone(_reason(presence="offline", was_online=seen))

    def test_offline_without_date_stays(self):
        self.assertIsNone(_reason(presence="offline", was_online=None))

    def test_naive_timestamp_is_utc(self):
        seen = (_now() - timedelta(days=40)).replace(tzinfo=None)
        self.assertEqual(_reason(presence="offline", was_online=seen), REASON_OFFLINE)

    def test_deleted_goes(self):
        self.assertEqual(_reason(deleted=True, presence="online"), REASON_DELETED)

    def test_bot_stays_even_if_deleted(self):
        self.assertIsNone(_reason(is_bot=True, deleted=True, presence="empty"))

    def test_protected_stays_even_if_deleted(self):
        self.assertIsNone(_reason(user_id=5, deleted=True, protected_ids={5}))

    def test_non_positive_id_stays(self):
        self.assertIsNone(_reason(user_id=0, deleted=True))


class CleanCommandTests(unittest.TestCase):
    def test_bare_command(self):
        self.assertTrue(is_clean_command("/clean"))
        self.assertTrue(is_clean_command("/clean@focuscleear_bot"))
        self.assertFalse(is_clean_command("/clean зайдите"))
        self.assertFalse(is_clean_command("чистка"))

    def test_summary_line(self):
        self.assertEqual(
            summary_line(2, 1),
            "Авточистка focus-чата: давно 2, удалённые 1",
        )


if __name__ == "__main__":
    unittest.main()
