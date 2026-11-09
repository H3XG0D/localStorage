"""Cancel waiting 1×1 duels; expire unjoined house tables after 10 minutes.

V2 equal-stake tables are not timed out. The creator cancels them from the bot
or the site. Cards stay until that cancel, then the bot deletes the message.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from casino_finance import lock_casino_game, lock_casino_users, money, release_unified_hold

logger = logging.getLogger(__name__)

WAITING_JOIN_TIMEOUT_SECONDS = 600
EXPIRE_BATCH = 20
REASON_CREATOR = "creator_cancelled"
REASON_TIMEOUT = "waiting_join_timeout"

_closer_started = False


def ensure_closer() -> None:
    global _closer_started
    if _closer_started:
        return
    _closer_started = True
    asyncio.create_task(_closer_loop())


def waiting_cutoff(now: datetime | None = None) -> datetime:
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    return clock - timedelta(seconds=WAITING_JOIN_TIMEOUT_SECONDS)


async def cancel_waiting_duel(
    conn,
    game_id: str,
    *,
    actor_id: int | None = None,
    reason: str = REASON_CREATOR,
) -> dict[str, Any]:
    """Refund the creator hold and mark a waiting 1×1 cancelled. Join race → 409."""
    gid = str(game_id or "").strip()
    if not gid:
        raise HTTPException(status_code=404, detail="Дуэль не найдена")
    await lock_casino_game(conn, gid)
    game = await conn.fetchrow(
        """
        SELECT game_id, creator_id, creator_hold_id, bet_rub, status, opponent_id
        FROM casino_games
        WHERE game_id = $1
        FOR UPDATE
        """,
        gid,
    )
    if not game:
        raise HTTPException(status_code=404, detail="Дуэль не найдена")
    if actor_id is not None and int(game["creator_id"]) != int(actor_id):
        raise HTTPException(status_code=403, detail="Отменить может только создатель")
    if str(game["status"]) != "waiting" or game["opponent_id"] is not None:
        raise HTTPException(status_code=409, detail="Эту игру уже нельзя отменить")
    creator_id = int(game["creator_id"])
    hold_id = str(game["creator_hold_id"] or "")
    if not hold_id:
        raise HTTPException(status_code=409, detail="У дуэли нет холда создателя")
    await lock_casino_users(conn, (creator_id,))
    hold = await conn.fetchrow(
        """
        SELECT hold_id, telegram_id, game_id, amount_rub, ledger_order_ref, status
        FROM casino_balance_holds
        WHERE hold_id = $1
        FOR UPDATE
        """,
        hold_id,
    )
    if (
        not hold
        or str(hold["status"]) != "active"
        or int(hold["telegram_id"]) != creator_id
        or str(hold["game_id"]) != gid
        or money(hold["amount_rub"]) != money(game["bet_rub"])
        or not hold["ledger_order_ref"]
    ):
        raise HTTPException(status_code=409, detail="Холд дуэли не сходится")
    await release_unified_hold(
        conn,
        user_id=creator_id,
        order_ref=str(hold["ledger_order_ref"]),
        amount_rub=money(game["bet_rub"]),
        note=f"Casino waiting duel cancelled: {gid}",
    )
    await conn.execute(
        """
        UPDATE casino_balance_holds
        SET status = 'released', released_at = now()
        WHERE hold_id = $1 AND status = 'active'
        """,
        hold_id,
    )
    cancelled = await conn.fetchrow(
        """
        UPDATE casino_games
        SET status = 'cancelled', finished_at = now(), updated_at = now(),
            game_data = COALESCE(game_data, '{}'::jsonb)
                || jsonb_build_object('release_reason', $2::text)
        WHERE game_id = $1 AND status = 'waiting' AND opponent_id IS NULL
        RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, status,
                  game_state, outcome, game_data, created_at
        """,
        gid,
        str(reason),
    )
    if not cancelled:
        raise HTTPException(status_code=409, detail="Эту игру уже нельзя отменить")
    return dict(cancelled)


async def cancel_player_duel(
    conn,
    game_id: str,
    *,
    actor_id: int | None = None,
    reason: str = REASON_CREATOR,
) -> dict[str, Any]:
    """Waiting cancel, or refund a stuck demo/no-commit card duel."""
    from casino_pvp_cards import abort_unfinishable_card_duel

    aborted = await abort_unfinishable_card_duel(conn, game_id, actor_id=actor_id)
    if aborted:
        return aborted
    return await cancel_waiting_duel(conn, game_id, actor_id=actor_id, reason=reason)


async def expire_waiting_duels(conn, *, now: datetime | None = None, limit: int = EXPIRE_BATCH) -> int:
    cutoff = waiting_cutoff(now)
    rows = await conn.fetch(
        """
        /* duel:expire-unjoined */
        SELECT game_id
        FROM casino_games
        WHERE status = 'waiting'
          AND opponent_id IS NULL
          AND created_at <= $1
        ORDER BY created_at
        LIMIT $2
        """,
        cutoff,
        int(limit),
    )
    expired = 0
    for row in rows:
        try:
            await cancel_waiting_duel(
                conn,
                str(row["game_id"]),
                reason=REASON_TIMEOUT,
            )
        except HTTPException as exc:
            if int(exc.status_code) not in {403, 404, 409}:
                raise
            continue
        expired += 1
    return expired


async def expire_unjoined_v2(conn, *, now: datetime | None = None, limit: int = EXPIRE_BATCH) -> int:
    """V2 open/ready tables wait until the creator cancels. No join-timeout refund."""
    return 0


async def expire_stale_v2_play(conn, *, now: datetime | None = None, limit: int = EXPIRE_BATCH) -> int:
    from routers.internal_casino import expire_stale_v2_play_with_conn

    return await expire_stale_v2_play_with_conn(conn, now=now, limit=limit)


async def expire_open_house_unjoined(conn, *, now: datetime | None = None, limit: int = EXPIRE_BATCH) -> int:
    from casino_house_tables import expire_open_unjoined, expire_pending_choices

    closed = await expire_open_unjoined(conn, now=now, limit=limit)
    closed += await expire_pending_choices(conn, now=now, limit=limit)
    return closed


async def expire_unjoined_due(conn, *, now: datetime | None = None, limit: int = EXPIRE_BATCH) -> dict[str, int]:
    from casino_pvp_cards import abort_unfinishable_card_duels_due

    return {
        "duels": await expire_waiting_duels(conn, now=now, limit=limit),
        "v2": await expire_unjoined_v2(conn, now=now, limit=limit),
        "stale_play": await expire_stale_v2_play(conn, now=now, limit=limit),
        "house": await expire_open_house_unjoined(conn, now=now, limit=limit),
        "cards": await abort_unfinishable_card_duels_due(conn, limit=limit),
    }


async def _closer_loop() -> None:
    from db import get_pool

    while True:
        await asyncio.sleep(10)
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await expire_waiting_duels(conn)
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await expire_unjoined_v2(conn)
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await expire_stale_v2_play(conn)
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await expire_open_house_unjoined(conn)
            async with pool.acquire() as conn:
                async with conn.transaction():
                    from casino_pvp_cards import abort_unfinishable_card_duels_due

                    await abort_unfinishable_card_duels_due(conn)
        except Exception:
            logger.exception("waiting-join expire")
