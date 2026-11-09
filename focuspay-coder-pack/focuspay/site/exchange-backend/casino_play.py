"""Web house-play quote, stake bounds copy, and public bets tape."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Mapping, Sequence

from casino_finance import CasinoSettings, calculate_house_settlement, game_stake_bounds, load_casino_settings, money
from casino_house_cards import HOUSE_CARD_GAME_TYPES
from casino_roulette import (
    DEFAULT_ROULETTE_BET,
    ROULETTE_GAME_TYPE,
    apply_roulette_stake_window,
    bet_spec,
    is_valid_pocket,
    load_roulette_quote_profile,
    pocket_color,
    public_bet_table,
)

HIGH_STAKE_RUB = Decimal("5000")
TAPE_TABS = ("mine", "all", "high")
HOUSE_PLAY_GAME_TYPES = ("cub", *HOUSE_CARD_GAME_TYPES, ROULETTE_GAME_TYPE)
MIN_HOUSE_BOTS_FOR_SCALED_ODDS = 2
MAX_HOUSE_BOTS_FOR_SCALED_ODDS = 6


def house_bots_cub_odds(house_bot_count: int) -> tuple[Decimal, Decimal] | None:
    """Table 2–6 vs house: N bots → ×(N+1) and win chance 1/(N+1). 0–1 bots keep cub policy."""
    n = int(house_bot_count or 0)
    if n < MIN_HOUSE_BOTS_FOR_SCALED_ODDS or n > MAX_HOUSE_BOTS_FOR_SCALED_ODDS:
        return None
    multiplier = Decimal(n + 1)
    return multiplier, Decimal(1) / multiplier


def stake_bound_error(stake: Decimal, min_bet: Decimal, max_bet: Decimal) -> str | None:
    amount = money(stake)
    lo = money(min_bet)
    hi = money(max_bet)
    if amount < lo:
        return f"Ставка ниже минимума {lo} ₽"
    if amount > hi:
        return f"Ставка выше максимума {hi} ₽"
    return None


def build_play_quote(
    settings: CasinoSettings,
    *,
    stake_rub: Decimal,
    payout_multiplier: Decimal,
    commission_rate: Decimal,
    min_bet: Decimal,
    max_bet: Decimal,
    enabled: bool,
    win_probability: Decimal | None = None,
    game_type: str = "cub",
) -> dict[str, object]:
    stake = money(stake_rub)
    multiplier = Decimal(str(payout_multiplier))
    bound = stake_bound_error(stake, money(min_bet), money(max_bet))
    gross = money(stake * multiplier)
    settlement = calculate_house_settlement(
        stake,
        multiplier,
        commission_rate,
        commission_cap_rub=settings.commission_cap_rub,
        commission_min_rub=settings.commission_min_rub,
    )
    return {
        "game_type": game_type,
        "enabled": bool(enabled),
        "stake_rub": float(stake),
        "min_bet_rub": float(money(min_bet)),
        "max_bet_rub": float(money(max_bet)),
        "payout_multiplier": float(multiplier),
        "win_probability": float(win_probability) if win_probability is not None else None,
        "commission_percent": float(commission_rate),
        "gross_payout_rub": float(gross),
        "commission_rub": float(settlement.commission),
        "win_on_win_rub": float(settlement.payout),
        "bound_error": bound,
    }


def tape_is_high(bet_rub: Decimal) -> bool:
    return money(bet_rub) >= HIGH_STAKE_RUB


def tape_row_result(row: Mapping[str, object]) -> dict[str, object] | None:
    """Wheel pocket of a finished roulette round, when the query selected `outcome`."""
    if str(row.get("game_type") or "") != ROULETTE_GAME_TYPE:
        return None
    outcome = row.get("outcome")
    if isinstance(outcome, str):
        try:
            outcome = json.loads(outcome)
        except json.JSONDecodeError:
            return None
    if not isinstance(outcome, Mapping) or not is_valid_pocket(outcome.get("pocket")):
        return None
    pocket = int(outcome["pocket"])
    return {
        "pocket": pocket,
        "color": pocket_color(pocket),
        "bet": str(outcome.get("bet") or ""),
    }


def build_tape_row(
    row: Mapping[str, object],
    *,
    viewer_id: int | None,
) -> dict[str, object]:
    creator = row.get("creator_id")
    mine = viewer_id is not None and creator is not None and int(creator) == int(viewer_id)
    finished = row.get("finished_at")
    bet = money(row.get("bet_rub") or 0)
    payout = money(row.get("payout_rub") or 0)
    won = bool(row.get("winner_id")) and creator is not None and int(row.get("winner_id") or 0) == int(creator)
    built = {
        "game_id": str(row.get("game_id") or ""),
        "game_type": str(row.get("game_type") or ""),
        "stake_rub": float(bet),
        "payout_rub": float(payout),
        "won": won,
        "is_mine": mine,
        "player_label": "Вы" if mine else "Игрок",
        "finished_at": finished.isoformat() if hasattr(finished, "isoformat") else str(finished or ""),
    }
    result = tape_row_result(row)
    if result is not None:
        built["result"] = result
    return built


def filter_tape_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    tab: str,
    viewer_id: int | None,
) -> list[dict[str, object]]:
    wanted = tab if tab in TAPE_TABS else "all"
    out: list[dict[str, object]] = []
    for row in rows:
        creator = row.get("creator_id")
        mine = viewer_id is not None and creator is not None and int(creator) == int(viewer_id)
        if wanted == "mine" and not mine:
            continue
        if wanted == "high" and not tape_is_high(Decimal(str(row.get("bet_rub") or 0))):
            continue
        out.append(build_tape_row(row, viewer_id=viewer_id))
    return out


async def load_cub_play_quote(
    conn,
    *,
    stake_rub: Decimal,
    viewer_id: int | None,
    house_bot_count: int = 0,
) -> dict[str, object]:
    from casino_wagering import commission_rate_for_player

    settings = await load_casino_settings(conn)
    enabled = bool(settings.enabled_games.get("cub", False))
    policy = await conn.fetchrow(
        """
        SELECT payout_multiplier, win_probability
        FROM casino_house_policies
        WHERE game_type = 'cub' AND is_active = TRUE
        LIMIT 1
        """
    )
    profile = await conn.fetchrow(
        """
        SELECT rp.min_bet_rub, rp.max_bet_rub, ha.balance_rub
        FROM casino_robot_profiles rp
        JOIN casino_house_accounts ha ON ha.id = rp.account_id
        WHERE rp.mode = 'house_robot' AND rp.is_active = TRUE
          AND ha.is_active = TRUE
          AND rp.allowed_games ? 'cub'
        ORDER BY rp.id
        LIMIT 1
        """
    )
    multiplier = Decimal(str(policy["payout_multiplier"])) if policy else Decimal("2")
    win_probability = Decimal(str(policy["win_probability"])) if policy else None
    scaled = house_bots_cub_odds(house_bot_count)
    if scaled:
        multiplier, win_probability = scaled
    bankroll = money(profile["balance_rub"]) if profile else Decimal("0")
    min_bet, max_bet = game_stake_bounds(
        settings,
        "cub",
        payout_multiplier=multiplier,
        bankroll_rub=bankroll,
    )
    if profile:
        min_bet = max(min_bet, money(profile["min_bet_rub"]))
        max_bet = min(max_bet, money(profile["max_bet_rub"]))
    if not policy or not profile:
        enabled = False
    rate = settings.commission_rate_wagering_complete
    if viewer_id:
        rate = await commission_rate_for_player(conn, viewer_id)
    return build_play_quote(
        settings,
        stake_rub=stake_rub,
        payout_multiplier=multiplier,
        commission_rate=rate,
        min_bet=min_bet,
        max_bet=max_bet,
        enabled=enabled,
        win_probability=win_probability,
        game_type="cub",
    )


async def load_card_house_play_quote(
    conn,
    *,
    game_type: str,
    stake_rub: Decimal,
    viewer_id: int | None,
) -> dict[str, object]:
    from casino_wagering import commission_rate_for_player

    if game_type not in HOUSE_CARD_GAME_TYPES:
        raise ValueError("not a house card game")
    settings = await load_casino_settings(conn)
    enabled = bool(settings.enabled_games.get(game_type, False))
    policy = await conn.fetchrow(
        """
        SELECT payout_multiplier
        FROM casino_house_policies
        WHERE game_type = $1 AND is_active = TRUE
        LIMIT 1
        """,
        game_type,
    )
    if not policy:
        policy = await conn.fetchrow(
            """
            SELECT payout_multiplier
            FROM casino_house_policies
            WHERE game_type = 'cub' AND is_active = TRUE
            LIMIT 1
            """
        )
    profile = await conn.fetchrow(
        """
        SELECT rp.min_bet_rub, rp.max_bet_rub, ha.balance_rub
        FROM casino_robot_profiles rp
        JOIN casino_house_accounts ha ON ha.id = rp.account_id
        WHERE rp.mode = 'house_robot' AND rp.is_active = TRUE
          AND ha.is_active = TRUE
          AND (rp.allowed_games ? $1 OR rp.allowed_games ? 'cub')
        ORDER BY CASE WHEN rp.allowed_games ? $1 THEN 0 ELSE 1 END, rp.id
        LIMIT 1
        """,
        game_type,
    )
    multiplier = Decimal(str(policy["payout_multiplier"])) if policy else Decimal("2")
    bankroll = money(profile["balance_rub"]) if profile else Decimal("0")
    min_bet, max_bet = game_stake_bounds(
        settings,
        game_type,
        payout_multiplier=multiplier,
        bankroll_rub=bankroll,
    )
    if profile:
        min_bet = max(min_bet, money(profile["min_bet_rub"]))
        max_bet = min(max_bet, money(profile["max_bet_rub"]))
    if not policy or not profile:
        enabled = False
    rate = settings.commission_rate_wagering_complete
    if viewer_id:
        rate = await commission_rate_for_player(conn, viewer_id)
    return build_play_quote(
        settings,
        stake_rub=stake_rub,
        payout_multiplier=multiplier,
        commission_rate=rate,
        min_bet=min_bet,
        max_bet=max_bet,
        enabled=enabled,
        win_probability=None,
        game_type=game_type,
    )


async def load_roulette_play_quote(
    conn,
    *,
    stake_rub: Decimal,
    viewer_id: int | None,
    bet: str = DEFAULT_ROULETTE_BET,
) -> dict[str, object]:
    """Bounds and payout for one bet type. Zero reserves ×36, so its max stake is lower."""
    from casino_wagering import commission_rate_for_player

    spec = bet_spec(bet)
    settings = await load_casino_settings(conn)
    enabled = bool(settings.enabled_games.get(ROULETTE_GAME_TYPE, False))
    profile = await load_roulette_quote_profile(conn)
    min_bet, max_bet = apply_roulette_stake_window(settings, spec.payout_multiplier, profile)
    if not profile:
        enabled = False
    rate = settings.commission_rate_wagering_complete
    if viewer_id:
        rate = await commission_rate_for_player(conn, viewer_id)
    quote = build_play_quote(
        settings,
        stake_rub=stake_rub,
        payout_multiplier=spec.payout_multiplier,
        commission_rate=rate,
        min_bet=min_bet,
        max_bet=max_bet,
        enabled=enabled,
        win_probability=spec.win_probability,
        game_type=ROULETTE_GAME_TYPE,
    )
    quote["bet"] = spec.key
    quote["odds_ru"] = spec.odds_ru
    quote["profit_ratio"] = float(spec.profit_ratio)
    quote["bets"] = public_bet_table()
    return quote


async def load_house_play_quote(
    conn,
    *,
    game_type: str,
    stake_rub: Decimal,
    viewer_id: int | None,
    house_bot_count: int = 0,
    roulette_bet: str = DEFAULT_ROULETTE_BET,
) -> dict[str, object]:
    if game_type == "cub":
        return await load_cub_play_quote(
            conn, stake_rub=stake_rub, viewer_id=viewer_id, house_bot_count=house_bot_count
        )
    if game_type == ROULETTE_GAME_TYPE:
        return await load_roulette_play_quote(
            conn, stake_rub=stake_rub, viewer_id=viewer_id, bet=roulette_bet
        )
    return await load_card_house_play_quote(
        conn, game_type=game_type, stake_rub=stake_rub, viewer_id=viewer_id
    )
