"""Кого убирать из focus-чата: удалённые и не бывшие в сети больше месяца."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

STALE_DAYS = 30
KICK_PAUSE_SEC = 1.0
CLEAN_INTERVAL_SEC = 24 * 60 * 60

REASON_DELETED = "deleted"
REASON_OFFLINE = "offline"
REASON_LONG_AGO = "long_ago"

_KEEP_PRESENCE = frozenset({"online", "recently", "last_week", "last_month"})
_STATUS_BY_CLASS = {
    "UserStatusOnline": "online",
    "UserStatusRecently": "recently",
    "UserStatusLastWeek": "last_week",
    "UserStatusLastMonth": "last_month",
    "UserStatusEmpty": "empty",
    "UserStatusOffline": "offline",
}
_CLEAN_RE = re.compile(r"/clean(?:@[A-Za-z0-9_]+)?", re.IGNORECASE)


def is_clean_command(text: str | None) -> bool:
    return bool(_CLEAN_RE.fullmatch((text or "").strip()))


def describe_presence(status: object) -> tuple[str | None, datetime | None]:
    """Имя статуса Telegram и точная дата, если она есть. Неизвестный статус — не кикать."""
    if status is None:
        return None, None
    kind = _STATUS_BY_CLASS.get(type(status).__name__)
    if kind is None:
        return None, None
    if kind != "offline":
        return kind, None
    was_online = getattr(status, "was_online", None)
    if not isinstance(was_online, datetime):
        return "offline", None
    return "offline", was_online


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def cleanup_reason(
    *,
    user_id: int,
    is_bot: bool,
    deleted: bool,
    presence: str | None,
    was_online: datetime | None,
    protected_ids: set[int],
    now: datetime,
) -> str | None:
    """deleted / offline / long_ago, либо None если человека оставляем."""
    uid = int(user_id)
    if uid <= 0 or uid in protected_ids or is_bot:
        return None
    if deleted:
        return REASON_DELETED
    if presence in _KEEP_PRESENCE:
        return None
    if presence == "offline":
        if was_online is None:
            return None
        moment = _utc(now)
        seen = _utc(was_online)
        if moment - seen > timedelta(days=STALE_DAYS):
            return REASON_OFFLINE
        return None
    if presence == "empty":
        return REASON_LONG_AGO
    return None


def is_stale_reason(reason: str | None) -> bool:
    return reason in {REASON_OFFLINE, REASON_LONG_AGO}


def summary_line(stale: int, deleted: int) -> str:
    return f"Авточистка focus-чата: давно {int(stale)}, удалённые {int(deleted)}"
