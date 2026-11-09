"""Public casino player profile for the website (user JWT)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException

from casino_chat import public_actors
from casino_player_cosmetics import load_notify_open_tables
from casino_finance import money
from casino_level_bonus import bonus_for_threshold, load_level_reach_bonuses
from casino_tier_config import (
    load_tier_config,
    next_cashback_tier,
    resolve_cashback_percent,
    resolve_commission_volume_tier,
)
from casino_payout_rail import payout_rail_progress, serialize_payout_rail
from casino_wagering import (
    commission_profile_for_player,
    serialize_wagering_progress,
    wagering_progress,
)
from casino_weekly_wager import current_week_start, lifetime_wager_rub, weekly_wager_by_game, weekly_wager_rub

GAME_LABELS = {
    "pvp_dice": "Кубики",
    "baccara": "Баккара",
    "blackjack": "Блэкджек",
    "cub": "Кубик против казино",
    "roulette": "Рулетка",
    "holdem": "Техасский холдем",
    "jackpot": "Джекпот",
    "fixed_room": "Комнаты",
    "clan_war": "Клан vs клан",
    "raffle": "FocusLucky",
}


def _text_money(value: Decimal | int | float | str | None) -> str:
    return str(money(value or 0))


def _iso_date(value: object) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


async def player_exists(conn, player_id: int) -> bool:
    row = await conn.fetchrow(
        """
        SELECT 1 AS ok
        WHERE EXISTS (SELECT 1 FROM bot_users WHERE user_id = $1)
           OR EXISTS (SELECT 1 FROM web_users WHERE telegram_user_id = $1)
           OR EXISTS (SELECT 1 FROM web_users WHERE client_user_id = $1)
           OR EXISTS (SELECT 1 FROM casino_player_cosmetics WHERE user_id = $1)
           OR EXISTS (SELECT 1 FROM casino_house_table_seats WHERE telegram_id = $1)
           OR EXISTS (
                SELECT 1 FROM casino_games
                WHERE creator_id = $1 OR opponent_id = $1
           )
           OR EXISTS (SELECT 1 FROM casino_jackpot_bets WHERE user_id = $1)
           OR EXISTS (SELECT 1 FROM casino_roulette_bets WHERE user_id = $1)
           OR EXISTS (SELECT 1 FROM casino_v2_table_seats WHERE telegram_id = $1)
        """,
        int(player_id),
    )
    return bool(row)


async def load_registered_at(conn, player_id: int) -> str | None:
    row = await conn.fetchrow(
        """
        SELECT bu.first_seen_at, wu.created_at
        FROM (SELECT $1::bigint AS uid) x
        LEFT JOIN bot_users bu ON bu.user_id = x.uid
        LEFT JOIN LATERAL (
            SELECT created_at FROM web_users
            WHERE telegram_user_id = x.uid OR client_user_id = x.uid
            LIMIT 1
        ) wu ON TRUE
        """,
        int(player_id),
    )
    if not row:
        return None
    return _iso_date(row["first_seen_at"]) or _iso_date(row["created_at"])


def _level_payload(
    *,
    index: int,
    min_wager: Decimal,
    cashback_percent: Decimal,
    commission_complete: Decimal,
    commission_active: Decimal,
    reach_bonus: Decimal,
    include_bonus: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "index": index,
        "min_wager_rub": _text_money(min_wager),
        "cashback_percent": _text_money(cashback_percent),
        "commission_complete_rate": _text_money(commission_complete),
        "commission_active_rate": _text_money(commission_active),
    }
    if include_bonus and reach_bonus > 0:
        payload["reach_bonus_rub"] = _text_money(reach_bonus)
    return payload


async def _own_available(conn, player_id: int):
    from user_unified_balance import unified_available

    return money(await unified_available(conn, player_id))


async def load_web_player_profile(conn, player_id: int, *, viewer_id: int) -> dict[str, object]:
    player_id = int(player_id)
    is_own = int(viewer_id) == player_id
    if not is_own and not await player_exists(conn, player_id):
        raise HTTPException(status_code=404, detail="Игрок не найден")
    actors = await public_actors(conn, [player_id])
    actor = actors.get(player_id) or {
        "user_id": player_id,
        "display_name": str(player_id),
        "initial": "?",
        "avatar_url": None,
    }
    if not actor.get("avatar_url"):
        from casino_default_avatar import default_avatar_url_for_user

        actor = {**actor, "avatar_url": default_avatar_url_for_user(player_id)}
    week_start = current_week_start()
    wager = await weekly_wager_rub(conn, player_id, week_start=week_start)
    lifetime = await lifetime_wager_rub(conn, player_id)
    by_game = await weekly_wager_by_game(conn, player_id, week_start=week_start)
    tier_config = await load_tier_config(conn)
    bonuses = await load_level_reach_bonuses(conn)
    cashback_percent = resolve_cashback_percent(tier_config.cashback_volume_tiers, wager)
    volume_tier = resolve_commission_volume_tier(tier_config.commission_volume_tiers, wager)
    current_index = 1
    current_min = Decimal("0.00")
    for index, tier in enumerate(tier_config.cashback_volume_tiers, start=1):
        if wager >= tier.min_wager_rub:
            current_index = index
            current_min = tier.min_wager_rub
    next_tier = next_cashback_tier(tier_config.cashback_volume_tiers, wager)
    next_payload = None
    if next_tier is not None:
        next_commission = resolve_commission_volume_tier(
            tier_config.commission_volume_tiers,
            next_tier.min_wager_rub,
        )
        remaining = money(next_tier.min_wager_rub - wager)
        if remaining < 0:
            remaining = Decimal("0.00")
        next_payload = {
            **_level_payload(
                index=current_index + 1,
                min_wager=next_tier.min_wager_rub,
                cashback_percent=next_tier.percent,
                commission_complete=next_commission.complete_rate,
                commission_active=next_commission.active_rate,
                reach_bonus=bonus_for_threshold(bonuses, next_tier.min_wager_rub),
                include_bonus=is_own,
            ),
            "remaining_wager_rub": _text_money(remaining),
        }
    wager_rows = [
        {
            "game_type": game_type,
            "label": GAME_LABELS.get(game_type, game_type),
            "wager_rub": _text_money(amount),
        }
        for game_type, amount in sorted(by_game.items(), key=lambda item: (-item[1], item[0]))
    ]
    payload: dict[str, object] = {
        "success": True,
        "is_own": is_own,
        "player": actor,
        "registered_at": await load_registered_at(conn, player_id),
        "week_start": week_start.isoformat(),
        "wager_rub": _text_money(wager),
        "lifetime_wager_rub": _text_money(lifetime),
        "wager_by_game": wager_rows,
        "level": _level_payload(
            index=current_index,
            min_wager=current_min,
            cashback_percent=cashback_percent,
            commission_complete=volume_tier.complete_rate,
            commission_active=volume_tier.active_rate,
            reach_bonus=bonus_for_threshold(bonuses, current_min),
            include_bonus=is_own,
        ),
        "next_level": next_payload,
    }
    if not is_own:
        return payload

    profile, rate = await commission_profile_for_player(conn, player_id)
    progress = await wagering_progress(conn, player_id)
    available = await _own_available(conn, player_id)
    payload["own"] = {
        "available_rub": _text_money(available),
        "notify_open_tables": await load_notify_open_tables(conn, player_id),
        "commission_profile": profile,
        "commission_rate": _text_money(rate),
        "cashback_percent": _text_money(cashback_percent),
        "wagering": serialize_wagering_progress(progress),
        "payout_rail": serialize_payout_rail(await payout_rail_progress(conn, player_id)),
    }
    return payload
