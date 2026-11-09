"""Недельный оборот ставок игрока (Europe/Moscow, понедельник 00:00)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from casino_finance import money

CASINO_TIMEZONE = ZoneInfo("Europe/Moscow")

CASHBACK_GAME_TYPES = (
    "pvp_dice",
    "baccara",
    "blackjack",
    "cub",
    "roulette",
    "holdem",
    "jackpot",
    "fixed_room",
    "clan_war",
)
PVP_GAME_TYPES = ("pvp_dice",)

# Shared-table roulette lands as casino_games.roulette (one row per chip) after settle.
# Web equal-stake tables live in casino_v2_*; they never write casino_games.
_WAGER_UNION_WEEK = """
            SELECT g.bet_rub::numeric AS wager_rub, g.game_type::text AS game_type
            FROM casino_games g, week
            WHERE g.status = 'finished'
              AND g.finished_at >= week.start_at
              AND g.finished_at < week.end_at
              AND g.game_type = ANY($3::text[])
              AND (g.creator_id = $1 OR g.opponent_id = $1){g_scope}
            UNION ALL
            SELECT (item.value)::numeric AS wager_rub, 'holdem'::text AS game_type
            FROM casino_poker_hands h, week, jsonb_each_text(h.wager_json) AS item
            WHERE h.settled_at IS NOT NULL
              AND h.settled_at >= week.start_at
              AND h.settled_at < week.end_at
              AND item.key = $1::text
            UNION ALL
            SELECT (item.value)::numeric AS wager_rub, 'jackpot'::text AS game_type
            FROM casino_jackpot_rounds r, week, jsonb_each_text(r.wager_json) AS item
            WHERE r.settled_at IS NOT NULL
              AND r.settled_at >= week.start_at
              AND r.settled_at < week.end_at
              AND item.key = $1::text{jp_scope}
            UNION ALL
            SELECT (item.value)::numeric AS wager_rub, 'fixed_room'::text AS game_type
            FROM casino_fixed_room_rounds r, week, jsonb_each_text(r.wager_json) AS item
            WHERE r.settled_at IS NOT NULL
              AND r.settled_at >= week.start_at
              AND r.settled_at < week.end_at
              AND item.key = $1::text{fr_scope}
            UNION ALL
            SELECT (item.value)::numeric AS wager_rub, 'clan_war'::text AS game_type
            FROM casino_clan_wars r, week, jsonb_each_text(r.wager_json) AS item
            WHERE r.settled_at IS NOT NULL
              AND r.settled_at >= week.start_at
              AND r.settled_at < week.end_at
              AND item.key = $1::text
            UNION ALL
            SELECT t.stake_rub::numeric AS wager_rub,
                   CASE WHEN t.game_type = 'pvp_emoji' THEN 'pvp_dice' ELSE t.game_type::text END AS game_type
            FROM casino_v2_tables t, week, casino_v2_table_seats s
            WHERE s.table_id = t.id
              AND t.status = 'finished'
              AND t.settled_at IS NOT NULL
              AND t.settled_at >= week.start_at
              AND t.settled_at < week.end_at
              AND s.telegram_id = $1
              AND s.participant_kind = 'player'{v2_scope}
"""

_WAGER_UNION_ALL = """
            SELECT g.bet_rub::numeric AS wager_rub, g.game_type::text AS game_type
            FROM casino_games g
            WHERE g.status = 'finished'
              AND g.finished_at IS NOT NULL
              AND g.game_type = ANY($2::text[])
              AND (g.creator_id = $1 OR g.opponent_id = $1){g_scope}
            UNION ALL
            SELECT (item.value)::numeric AS wager_rub, 'holdem'::text AS game_type
            FROM casino_poker_hands h, jsonb_each_text(h.wager_json) AS item
            WHERE h.settled_at IS NOT NULL
              AND item.key = $1::text
            UNION ALL
            SELECT (item.value)::numeric AS wager_rub, 'jackpot'::text AS game_type
            FROM casino_jackpot_rounds r, jsonb_each_text(r.wager_json) AS item
            WHERE r.settled_at IS NOT NULL
              AND item.key = $1::text{jp_scope}
            UNION ALL
            SELECT (item.value)::numeric AS wager_rub, 'fixed_room'::text AS game_type
            FROM casino_fixed_room_rounds r, jsonb_each_text(r.wager_json) AS item
            WHERE r.settled_at IS NOT NULL
              AND item.key = $1::text{fr_scope}
            UNION ALL
            SELECT (item.value)::numeric AS wager_rub, 'clan_war'::text AS game_type
            FROM casino_clan_wars r, jsonb_each_text(r.wager_json) AS item
            WHERE r.settled_at IS NOT NULL
              AND item.key = $1::text
            UNION ALL
            SELECT t.stake_rub::numeric AS wager_rub,
                   CASE WHEN t.game_type = 'pvp_emoji' THEN 'pvp_dice' ELSE t.game_type::text END AS game_type
            FROM casino_v2_tables t
            JOIN casino_v2_table_seats s ON s.table_id = t.id
            WHERE t.status = 'finished'
              AND t.settled_at IS NOT NULL
              AND s.telegram_id = $1
              AND s.participant_kind = 'player'{v2_scope}
"""

_WEEK_CTE = """
        WITH week AS (
            SELECT ($2::date::timestamp AT TIME ZONE 'Europe/Moscow') AS start_at,
                   (($2::date + 7)::timestamp AT TIME ZONE 'Europe/Moscow') AS end_at
        )
"""


async def _rub_only(conn, union_sql: str) -> str:
    """Кешбэк и уровни считаются только по рублёвым раундам, фишки в оборот не идут."""
    from casino_wallet import table_has_scope_columns

    clauses: dict[str, str] = {}
    for name, table, alias in (
        ("g_scope", "casino_games", "g"),
        ("jp_scope", "casino_jackpot_rounds", "r"),
        ("fr_scope", "casino_fixed_room_rounds", "r"),
        ("v2_scope", "casino_v2_tables", "t"),
    ):
        ready = await table_has_scope_columns(conn, table)
        clauses[name] = (
            f"\n              AND COALESCE({alias}.wallet_kind, 'rub') = 'rub'" if ready else ""
        )
    return union_sql.format(**clauses)


def current_week_start(day: date | None = None) -> date:
    current_day = day or datetime.now(CASINO_TIMEZONE).date()
    return current_day - timedelta(days=current_day.weekday())


async def weekly_wager_rub(
    conn,
    telegram_id: int,
    *,
    week_start: date | None = None,
) -> Decimal:
    week_start = week_start or current_week_start()
    union_sql = await _rub_only(conn, _WAGER_UNION_WEEK)
    row = await conn.fetchrow(
        f"""
        {_WEEK_CTE}
        SELECT COALESCE(SUM(wager_rub), 0)::numeric AS wager_rub
        FROM (
            {union_sql}
        ) wagers
        """,
        telegram_id,
        week_start,
        list(CASHBACK_GAME_TYPES),
    )
    return money(row["wager_rub"] if row else 0)


async def lifetime_wager_rub(conn, telegram_id: int) -> Decimal:
    union_sql = await _rub_only(conn, _WAGER_UNION_ALL)
    row = await conn.fetchrow(
        f"""
        SELECT COALESCE(SUM(wager_rub), 0)::numeric AS wager_rub
        FROM (
            {union_sql}
        ) wagers
        """,
        telegram_id,
        list(CASHBACK_GAME_TYPES),
    )
    return money(row["wager_rub"] if row else 0)


async def weekly_wager_by_game(
    conn,
    telegram_id: int,
    *,
    week_start: date | None = None,
) -> dict[str, Decimal]:
    """Finished weekly stake per game_type. Missing games omitted."""
    week_start = week_start or current_week_start()
    union_sql = await _rub_only(conn, _WAGER_UNION_WEEK)
    rows = await conn.fetch(
        f"""
        {_WEEK_CTE}
        SELECT game_type, COALESCE(SUM(wager_rub), 0)::numeric AS wager_rub
        FROM (
            {union_sql}
        ) wagers
        GROUP BY game_type
        """,
        telegram_id,
        week_start,
        list(CASHBACK_GAME_TYPES),
    )
    out: dict[str, Decimal] = {}
    for row in rows:
        amount = money(row["wager_rub"] or 0)
        if amount > 0:
            out[str(row["game_type"])] = amount
    return out
