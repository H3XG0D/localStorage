"""Concurrent live PvP seats and the 10-second start countdown."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from fastapi import HTTPException

from casino_settings_registry import REGISTRY, default_numeric

START_COUNTDOWN_SECONDS = 10
DEFAULT_CONCURRENT = 10
ROOM_LIVE_STATUSES = ("open", "countdown", "locked")
V2_LIVE_STATUSES = (
    "open",
    "ready",
    "running",
    "tie_break_running",
    "outcome_committed",
    "settling",
)
JACKPOT_LIVE_STATUSES = ("open", "locked")
ROULETTE_LIVE_STATUSES = ("open", "locked", "spinning")


def countdown_deadline(seconds: int | None = None) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=int(seconds or START_COUNTDOWN_SECONDS))


def merge_starts_at(game_state: object, *, seconds: int | None = None) -> dict[str, Any]:
    state = dict(game_state) if isinstance(game_state, Mapping) else {}
    state["starts_at"] = countdown_deadline(seconds).isoformat()
    return state


def _int_setting(raw: object) -> int | None:
    if isinstance(raw, Mapping) and raw.get("value") is not None:
        try:
            return int(raw["value"])
        except (TypeError, ValueError):
            return None
    if isinstance(raw, (int, float, str)) and str(raw).strip():
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return None


async def _scalar(conn, sql: str, *args) -> object:
    fetchval = getattr(conn, "fetchval", None)
    if not callable(fetchval):
        return None
    return await fetchval(sql, *args)


async def max_concurrent_games(conn) -> int:
    spec = REGISTRY.get("max_concurrent_games_per_player")
    fallback = int(spec.default) if spec is not None else DEFAULT_CONCURRENT
    try:
        raw = await _scalar(
            conn,
            "/* live:concurrent-setting */ SELECT value FROM casino_settings WHERE key = $1",
            "max_concurrent_games_per_player",
        )
    except Exception:
        return max(1, fallback)
    parsed = _int_setting(raw)
    if parsed is None:
        try:
            parsed = int(default_numeric("max_concurrent_games_per_player"))
        except Exception:
            parsed = fallback
    return max(1, int(parsed or fallback))


async def count_live_pvp_seats(conn, user_id: int) -> int:
    uid = int(user_id)
    rooms = await _scalar(
        conn,
        """
        /* live:count-rooms */
        SELECT COUNT(*)::int
        FROM casino_fixed_room_seats s
        JOIN casino_fixed_room_rounds r ON r.id = s.room_pk
        WHERE s.user_id = $1 AND r.status = ANY($2::text[])
        """,
        uid,
        list(ROOM_LIVE_STATUSES),
    )
    v2 = await _scalar(
        conn,
        """
        /* live:count-v2 */
        SELECT COUNT(*)::int
        FROM casino_v2_table_seats s
        JOIN casino_v2_tables t ON t.id = s.table_id
        WHERE s.telegram_id = $1
          AND s.status = 'seated'
          AND t.status = ANY($2::text[])
        """,
        uid,
        list(V2_LIVE_STATUSES),
    )
    jackpot = await _scalar(
        conn,
        """
        /* live:count-jackpot */
        SELECT COUNT(*)::int
        FROM (
            SELECT 1
            FROM casino_jackpot_bets b
            JOIN casino_jackpot_rounds r ON r.id = b.round_pk
            WHERE b.user_id = $1 AND r.status = ANY($2::text[])
            LIMIT 1
        ) j
        """,
        uid,
        list(JACKPOT_LIVE_STATUSES),
    )
    roulette = await _scalar(
        conn,
        """
        /* live:count-roulette */
        SELECT COUNT(*)::int
        FROM (
            SELECT 1
            FROM casino_roulette_bets b
            JOIN casino_roulette_rounds r ON r.id = b.round_pk
            WHERE b.user_id = $1 AND r.status = ANY($2::text[])
            LIMIT 1
        ) q
        """,
        uid,
        list(ROULETTE_LIVE_STATUSES),
    )
    return int(rooms or 0) + int(v2 or 0) + int(jackpot or 0) + int(roulette or 0)


async def assert_can_sit(conn, user_id: int) -> None:
    limit = await max_concurrent_games(conn)
    n = await count_live_pvp_seats(conn, user_id)
    if n >= limit:
        raise HTTPException(status_code=409, detail=f"Уже в {limit} играх")
