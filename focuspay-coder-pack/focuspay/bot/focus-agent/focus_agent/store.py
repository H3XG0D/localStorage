"""Dialogue notes and the operator Telegram bind. Bodies stored here are already redacted."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import asyncpg

_pool: asyncpg.Pool | None = None


async def open_pool(dsn: str) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("database pool is not open")
    return _pool


async def remember_chat(chat_id: int, title: str | None) -> None:
    await pool().execute(
        """
        INSERT INTO focus_agent_chats (chat_id, title)
        VALUES ($1, $2)
        ON CONFLICT (chat_id) DO UPDATE
        SET title = COALESCE(EXCLUDED.title, focus_agent_chats.title),
            updated_at = NOW()
        """,
        chat_id,
        (title or "")[:200] or None,
    )


async def add_line(chat_id: int, body: str) -> None:
    text = (body or "").strip()
    if not text:
        return
    await pool().execute(
        """
        INSERT INTO focus_agent_notes (chat_id, kind, body)
        VALUES ($1, 'line', $2)
        """,
        chat_id,
        text[:2000],
    )


async def recent_lines(chat_id: int, limit: int = 12) -> list[str]:
    rows = await pool().fetch(
        """
        SELECT body FROM focus_agent_notes
        WHERE chat_id = $1 AND kind = 'line'
        ORDER BY id DESC
        LIMIT $2
        """,
        chat_id,
        limit,
    )
    return [str(row["body"]) for row in reversed(rows)]


async def recent_summaries(chat_id: int, limit: int = 3) -> list[str]:
    rows = await pool().fetch(
        """
        SELECT body FROM focus_agent_notes
        WHERE chat_id = $1 AND kind = 'summary'
        ORDER BY id DESC
        LIMIT $2
        """,
        chat_id,
        limit,
    )
    return [str(row["body"]) for row in reversed(rows)]


async def lines_ready_to_fold(min_age_hours: int = 3) -> list[asyncpg.Record]:
    return await pool().fetch(
        """
        SELECT id, chat_id, body
        FROM focus_agent_notes
        WHERE kind = 'line'
          AND created_at < NOW() - ($1::int * INTERVAL '1 hour')
        ORDER BY chat_id, id
        """,
        min_age_hours,
    )


async def drop_lines(line_ids: list[int]) -> None:
    if not line_ids:
        return
    await pool().execute(
        "DELETE FROM focus_agent_notes WHERE id = ANY($1::bigint[])",
        line_ids,
    )


async def save_summary(chat_id: int, body: str, line_ids: list[int]) -> None:
    text = (body or "").strip()
    if not text or not line_ids:
        return
    async with pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO focus_agent_notes (chat_id, kind, body)
                VALUES ($1, 'summary', $2)
                """,
                chat_id,
                text[:4000],
            )
            await conn.execute(
                "DELETE FROM focus_agent_notes WHERE id = ANY($1::bigint[])",
                line_ids,
            )


async def chats_due_report(reports_id: int) -> list[asyncpg.Record]:
    """User groups whose day has not been reported yet. The reports group is not one of them."""
    return await pool().fetch(
        """
        SELECT chat_id
        FROM focus_agent_chats
        WHERE chat_id < 0
          AND chat_id <> $1
          AND (
                last_daily_at IS NULL
                OR last_daily_at < NOW() - INTERVAL '24 hours'
          )
        """,
        int(reports_id or 0),
    )


async def chats_due_idea(reports_id: int) -> list[asyncpg.Record]:
    """User groups that have not been asked for ideas in three days, and are not muted."""
    return await pool().fetch(
        """
        SELECT chat_id
        FROM focus_agent_chats
        WHERE chat_id < 0
          AND chat_id <> $1
          AND (
                last_idea_at IS NULL
                OR last_idea_at < NOW() - INTERVAL '3 days'
          )
          AND (muted_until IS NULL OR muted_until <= NOW())
        """,
        int(reports_id or 0),
    )


async def fresh_material(chat_id: int) -> str:
    rows = await pool().fetch(
        """
        SELECT kind, body FROM focus_agent_notes
        WHERE chat_id = $1
          AND created_at > COALESCE(
                (SELECT last_daily_at FROM focus_agent_chats WHERE chat_id = $1),
                '-infinity'::timestamptz
          )
        ORDER BY id
        LIMIT 40
        """,
        chat_id,
    )
    parts = [f"{row['kind']}: {row['body']}" for row in rows]
    return "\n".join(parts).strip()


async def chat_clock(chat_id: int) -> tuple[datetime | None, datetime | None]:
    row = await pool().fetchrow(
        """
        SELECT muted_until, last_chime_at
        FROM focus_agent_chats
        WHERE chat_id = $1
        """,
        chat_id,
    )
    if row is None:
        return None, None

    def aware(value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    return aware(row["muted_until"]), aware(row["last_chime_at"])


async def is_muted(chat_id: int, now: datetime | None = None) -> bool:
    muted_until, _ = await chat_clock(chat_id)
    if muted_until is None:
        return False
    current = now or datetime.now(timezone.utc)
    if muted_until.tzinfo is None:
        muted_until = muted_until.replace(tzinfo=timezone.utc)
    return muted_until > current


async def mute_for(chat_id: int, minutes: int = 5) -> datetime:
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    await pool().execute(
        """
        INSERT INTO focus_agent_chats (chat_id, muted_until)
        VALUES ($1, $2)
        ON CONFLICT (chat_id) DO UPDATE
        SET muted_until = EXCLUDED.muted_until,
            updated_at = NOW()
        """,
        chat_id,
        until,
    )
    return until


async def mark_chime(chat_id: int) -> None:
    await pool().execute(
        """
        INSERT INTO focus_agent_chats (chat_id, last_chime_at)
        VALUES ($1, NOW())
        ON CONFLICT (chat_id) DO UPDATE
        SET last_chime_at = NOW(),
            updated_at = NOW()
        """,
        chat_id,
    )


async def mark_daily(chat_id: int) -> None:
    await pool().execute(
        """
        UPDATE focus_agent_chats SET last_daily_at = NOW(), updated_at = NOW()
        WHERE chat_id = $1
        """,
        chat_id,
    )


async def mark_idea(chat_id: int) -> None:
    await pool().execute(
        """
        UPDATE focus_agent_chats SET last_idea_at = NOW(), updated_at = NOW()
        WHERE chat_id = $1
        """,
        chat_id,
    )

