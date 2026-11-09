"""Участники, которых бот видит в чате: сообщения и входы."""
from __future__ import annotations

import logging
import re
import time

from services.chat_call import CallUser

logger = logging.getLogger("chat_roster")

_REMEMBER_TTL_SEC = 60.0
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")
_recent: dict[tuple[int, int], tuple[str, float]] = {}

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS chat_call_members (
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    username TEXT,
    first_name TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chat_id, user_id)
)
"""

_SCAN_SQL = """
CREATE TABLE IF NOT EXISTS chat_call_scans (
    chat_id BIGINT PRIMARY KEY,
    scanned_at TIMESTAMPTZ NOT NULL,
    found INTEGER NOT NULL,
    chat_size INTEGER NOT NULL
)
"""

_KEEP_STATUSES = frozenset({"creator", "administrator", "member", "restricted"})
_DROP_STATUSES = frozenset({"left", "kicked"})
_SWEEP_CONCURRENCY = 8


def clean_username(value: str | None) -> str | None:
    name = (value or "").strip().lstrip("@")
    if not _USERNAME_RE.fullmatch(name):
        return None
    return name


async def ensure_chat_call_members() -> None:
    from services.db import get_pool

    pool = await get_pool()
    await pool.execute(_CREATE_SQL)
    await pool.execute(_SCAN_SQL)


def should_refresh_roster(
    roster_count: int,
    chat_size: int,
    *,
    scanned_recently: bool,
) -> bool:
    """Полная сверка, если в списке меньше половины чата или сверка устарела."""
    if chat_size <= 0:
        return False
    if roster_count * 2 < chat_size:
        return True
    return not scanned_recently


def _status_name(status: object) -> str:
    value = getattr(status, "value", status)
    return str(value or "").strip().lower()


async def remember_member(
    chat_id: int,
    user_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
) -> None:
    uid = int(user_id)
    if uid <= 0:
        return
    cid = int(chat_id)
    stored_name = clean_username(username) or ""
    key = (cid, uid)
    now = time.monotonic()
    prev = _recent.get(key)
    if prev is not None and prev[0] == stored_name and now - prev[1] < _REMEMBER_TTL_SEC:
        return
    from services.db import get_pool

    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO chat_call_members (chat_id, user_id, username, first_name, updated_at)
        VALUES ($1, $2, $3, $4, now())
        ON CONFLICT (chat_id, user_id) DO UPDATE
        SET username = EXCLUDED.username,
            first_name = EXCLUDED.first_name,
            updated_at = now()
        """,
        cid,
        uid,
        stored_name or None,
        (first_name or "").strip()[:255],
    )
    _recent[key] = (stored_name, now)


async def forget_member(chat_id: int, user_id: int) -> None:
    cid = int(chat_id)
    uid = int(user_id)
    _recent.pop((cid, uid), None)
    from services.db import get_pool

    pool = await get_pool()
    await pool.execute(
        "DELETE FROM chat_call_members WHERE chat_id = $1 AND user_id = $2",
        cid,
        uid,
    )


async def _candidate_ids(chat_id: int) -> list[int]:
    from services.db import get_pool

    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT user_id FROM bot_users
        UNION
        SELECT user_id FROM chat_call_members WHERE chat_id = $1
        """,
        int(chat_id),
    )
    return [int(row["user_id"]) for row in rows if int(row["user_id"]) > 0]


async def _scan_is_recent(chat_id: int) -> bool:
    from services.db import get_pool

    pool = await get_pool()
    scanned = await pool.fetchval(
        """
        SELECT scanned_at > now() - interval '12 hours'
        FROM chat_call_scans
        WHERE chat_id = $1
        """,
        int(chat_id),
    )
    return bool(scanned)


async def _roster_count(chat_id: int) -> int:
    from services.db import get_pool

    pool = await get_pool()
    value = await pool.fetchval(
        "SELECT count(*) FROM chat_call_members WHERE chat_id = $1",
        int(chat_id),
    )
    return int(value or 0)


async def _save_sweep(
    chat_id: int,
    kept: list[tuple[int, str | None, str]],
    dropped: list[int],
    chat_size: int,
) -> None:
    from services.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        if kept:
            await conn.executemany(
                """
                INSERT INTO chat_call_members (chat_id, user_id, username, first_name, updated_at)
                VALUES ($1, $2, $3, $4, now())
                ON CONFLICT (chat_id, user_id) DO UPDATE
                SET username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    updated_at = now()
                """,
                [(int(chat_id), user_id, username, first_name) for user_id, username, first_name in kept],
            )
        if dropped:
            await conn.executemany(
                "DELETE FROM chat_call_members WHERE chat_id = $1 AND user_id = $2",
                [(int(chat_id), user_id) for user_id in dropped],
            )
        await conn.execute(
            """
            INSERT INTO chat_call_scans (chat_id, scanned_at, found, chat_size)
            VALUES ($1, now(), $2, $3)
            ON CONFLICT (chat_id) DO UPDATE
            SET scanned_at = now(), found = EXCLUDED.found, chat_size = EXCLUDED.chat_size
            """,
            int(chat_id),
            len(kept),
            int(chat_size),
        )


async def sweep_known_members(
    bot: object,
    chat_id: int,
    chat_size: int,
    on_keep=None,
) -> int:
    """Оставить в списке тех пользователей бота, кто сейчас состоит в чате."""
    import asyncio

    from telegram.error import BadRequest, RetryAfter, TimedOut

    ids = set(await _candidate_ids(chat_id))
    try:
        admins = await bot.get_chat_administrators(chat_id)  # type: ignore[attr-defined]
    except Exception:
        logger.warning("roster admins failed chat=%s", chat_id, exc_info=True)
        admins = ()
    for admin in admins or ():
        user = getattr(admin, "user", None)
        if user is not None and isinstance(getattr(user, "id", None), int):
            ids.add(int(user.id))

    kept: list[tuple[int, str | None, str]] = []
    dropped: list[int] = []
    checked = 0
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(_SWEEP_CONCURRENCY)

    async def one(user_id: int) -> None:
        nonlocal checked
        async with sem:
            member = None
            for _attempt in range(5):
                try:
                    member = await bot.get_chat_member(chat_id, user_id)  # type: ignore[attr-defined]
                    break
                except RetryAfter as exc:
                    wait = getattr(exc, "retry_after", 1)
                    if hasattr(wait, "total_seconds"):
                        wait = wait.total_seconds()
                    await asyncio.sleep(float(wait or 1) + 0.3)
                except TimedOut:
                    await asyncio.sleep(1)
                except BadRequest:
                    return
                except Exception:
                    logger.debug("roster member skip chat=%s user=%s", chat_id, user_id, exc_info=True)
                    return
            if member is None:
                return
            user = getattr(member, "user", None)
            if user is None or getattr(user, "is_bot", False):
                return
            status = _status_name(getattr(member, "status", ""))
            found = None
            async with lock:
                checked += 1
                if status in _KEEP_STATUSES:
                    found = (
                        int(user.id),
                        clean_username(getattr(user, "username", None)),
                        (getattr(user, "first_name", None) or "").strip()[:255],
                    )
                    kept.append(found)
                elif status in _DROP_STATUSES:
                    dropped.append(int(user.id))
                if checked % 500 == 0:
                    logger.info(
                        "roster sweep progress chat=%s checked=%s kept=%s",
                        chat_id,
                        checked,
                        len(kept),
                    )
            if found is not None and on_keep is not None:
                await on_keep(
                    CallUser(
                        user_id=found[0],
                        first_name=found[2],
                        username=found[1] or "",
                    )
                )

    await asyncio.gather(*(one(user_id) for user_id in ids))
    await _save_sweep(chat_id, kept, dropped, chat_size)
    logger.info(
        "roster sweep done chat=%s checked=%s kept=%s dropped=%s size=%s",
        chat_id,
        checked,
        len(kept),
        len(dropped),
        chat_size,
    )
    return len(kept)


async def ensure_chat_roster(bot: object, chat_id: int, on_keep=None) -> int | None:
    """Вернуть размер чата. При тонком списке сверить его с пользователями бота."""
    try:
        chat_size = int(await bot.get_chat_member_count(chat_id))  # type: ignore[attr-defined]
    except Exception:
        logger.warning("roster size failed chat=%s", chat_id, exc_info=True)
        return None
    try:
        roster_count = await _roster_count(chat_id)
        recent = await _scan_is_recent(chat_id)
        if should_refresh_roster(roster_count, chat_size, scanned_recently=recent):
            await sweep_known_members(bot, chat_id, chat_size, on_keep=on_keep)
    except Exception:
        logger.warning("roster refresh failed chat=%s", chat_id, exc_info=True)
    return chat_size


async def list_chat_members(chat_id: int) -> list[CallUser]:
    from services.db import get_pool

    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT user_id, username, first_name
        FROM chat_call_members
        WHERE chat_id = $1
        ORDER BY user_id
        """,
        int(chat_id),
    )
    return [
        CallUser(
            user_id=int(row["user_id"]),
            first_name=str(row["first_name"] or ""),
            username=str(row["username"] or ""),
        )
        for row in rows
    ]
