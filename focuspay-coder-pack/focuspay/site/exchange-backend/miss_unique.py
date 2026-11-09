"""Unique-client window for no-shift requisites misses.

Keep the first miss per client inside a rolling hour. Retries at 5–30 min drop.
The first attempt's fiat_amount is the one that counts.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")
CLIENT_HOUR = timedelta(hours=1)


def as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def msk_clock(value: Any) -> tuple[str, int] | None:
    dt = as_utc(value)
    if dt is None:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat(), 0
        return None
    local = dt.astimezone(MSK)
    return local.date().isoformat(), local.hour


def dedupe_miss_rows(rows: list[Any], *, window: timedelta = CLIENT_HOUR) -> list[Any]:
    kept: list[Any] = []
    last_at: dict[int, datetime] = {}
    for row in rows:
        try:
            uid = int(row["user_id"] or 0)
        except (TypeError, ValueError, KeyError):
            continue
        ts = as_utc(row["created_at"])
        if not uid or ts is None:
            continue
        prev = last_at.get(uid)
        if prev is not None and ts - prev < window:
            continue
        kept.append(row)
        last_at[uid] = ts
    return kept


def row_fiat(row: Any) -> tuple[float, bool]:
    keys = row.keys() if hasattr(row, "keys") else ()
    if "fiat_amount" not in keys:
        return 0.0, False
    raw = row["fiat_amount"]
    if raw is None:
        return 0.0, False
    try:
        return float(raw), True
    except (TypeError, ValueError):
        return 0.0, False
