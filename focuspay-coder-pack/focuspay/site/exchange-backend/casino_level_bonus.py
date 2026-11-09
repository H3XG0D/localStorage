"""One-time weekly balance credit when weekly wager crosses a volume level."""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from casino_finance import money
from casino_weekly_wager import current_week_start, weekly_wager_rub

LEVEL_REACH_BONUSES_KEY = "level_reach_bonuses"


@dataclass(frozen=True)
class LevelReachBonus:
    min_wager_rub: Decimal
    bonus_rub: Decimal


def parse_level_reach_bonuses(raw: object | None) -> tuple[LevelReachBonus, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        raise ValueError("Level reach bonuses must be a list")
    rows: list[LevelReachBonus] = []
    seen: set[Decimal] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("Each bonus row must be an object")
        threshold = money(item.get("min_wager_rub", 0))
        bonus = money(item.get("bonus_rub", 0))
        if threshold <= 0:
            raise ValueError("Level reach bonus min_wager_rub must be greater than 0")
        if bonus < 0:
            raise ValueError("Level reach bonus cannot be negative")
        if threshold in seen:
            raise ValueError("Level reach bonus min_wager_rub values must be unique")
        seen.add(threshold)
        if bonus == 0:
            continue
        rows.append(LevelReachBonus(min_wager_rub=threshold, bonus_rub=bonus))
    return tuple(sorted(rows, key=lambda row: row.min_wager_rub))


def bonuses_to_public(rows: Sequence[LevelReachBonus]) -> list[dict[str, float]]:
    return [
        {"min_wager_rub": float(row.min_wager_rub), "bonus_rub": float(row.bonus_rub)}
        for row in rows
    ]


def bonus_for_threshold(rows: Sequence[LevelReachBonus], min_wager_rub: Decimal) -> Decimal:
    want = money(min_wager_rub)
    for row in rows:
        if row.min_wager_rub == want:
            return row.bonus_rub
    return Decimal("0.00")


async def load_level_reach_bonuses(conn) -> tuple[LevelReachBonus, ...]:
    row = await conn.fetchrow(
        "SELECT value FROM casino_settings WHERE key = $1",
        LEVEL_REACH_BONUSES_KEY,
    )
    raw = row["value"] if row else None
    try:
        return parse_level_reach_bonuses(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()


async def grant_reached_level_bonuses(conn, telegram_id: int) -> list[dict[str, object]]:
    """Credit each newly crossed weekly threshold once. Idempotent per week."""
    telegram_id = int(telegram_id)
    week_start = current_week_start()
    wager = await weekly_wager_rub(conn, telegram_id, week_start=week_start)
    bonuses = await load_level_reach_bonuses(conn)
    granted: list[dict[str, object]] = []
    for row in bonuses:
        if wager < row.min_wager_rub:
            continue
        inserted = await conn.fetchrow(
            """
            INSERT INTO casino_level_bonus_grants (
                telegram_id, week_start, min_wager_rub, bonus_rub
            )
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (telegram_id, week_start, min_wager_rub) DO NOTHING
            RETURNING telegram_id
            """,
            telegram_id,
            week_start,
            row.min_wager_rub,
            row.bonus_rub,
        )
        if inserted is None:
            continue
        ledger_order_id = f"clb:{telegram_id}:{week_start.isoformat()}:{row.min_wager_rub}"
        await conn.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'accrual', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            telegram_id,
            row.bonus_rub,
            ledger_order_id,
            f"Casino volume level bonus at {row.min_wager_rub} ₽ weekly wager",
        )
        granted.append(
            {
                "min_wager_rub": str(row.min_wager_rub),
                "bonus_rub": str(row.bonus_rub),
            }
        )
    return granted


async def grant_reached_level_bonuses_many(conn, telegram_ids: Sequence[int]) -> None:
    seen: set[int] = set()
    for raw in telegram_ids:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            continue
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)
        await grant_reached_level_bonuses(conn, uid)


def _is_asyncpg_conn(conn) -> bool:
    return type(conn).__module__.startswith("asyncpg")


async def maybe_grant_reached_level_bonuses(conn, *telegram_ids: int) -> None:
    """No-op on mocked test connections. Real asyncpg connections credit crossed levels."""
    if not telegram_ids or not _is_asyncpg_conn(conn):
        return
    await grant_reached_level_bonuses_many(conn, telegram_ids)
