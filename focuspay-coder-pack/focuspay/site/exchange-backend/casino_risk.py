"""Risk snapshot for the admin casino risk dashboard.

Numbers here must be reconstructible from SQL. The verify KPI is SUM(bet_rub)
over created_at in the selected window with no status filter — same query the
reviewer runs by hand.
"""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from math import sqrt
from typing import Any, Mapping, Sequence

from casino_finance import HEAD_TO_HEAD_GAME_TYPES, KNOWN_GAME_TYPES, money

WINDOWS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
WINDOW_SQL = {
    "24h": "24 hours",
    "7d": "7 days",
    "30d": "30 days",
}
HUNDRED = Decimal("100")
MONEY_STEP = Decimal("0.01")


def _dec(value: object, default: str = "0") -> Decimal:
    if value is None or isinstance(value, bool):
        return Decimal(default)
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(default)
    if not result.is_finite():
        return Decimal(default)
    return result


def _json(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return value


def setting_amount(settings: Mapping[str, object], key: str, default: str = "0") -> Decimal:
    raw = _json(settings.get(key))
    if not isinstance(raw, dict):
        return Decimal(default)
    field = "percent" if "percent" in raw else "amount"
    return _dec(raw.get(field), default)


def pvp_theoretical_rtp(commission_percent: Decimal | int | float | str) -> Decimal:
    """Players return (2B − C% of B) / 2B = 100 − C/2."""
    commission = _dec(commission_percent)
    return (HUNDRED - commission / 2).quantize(MONEY_STEP)


def house_theoretical_rtp(
    win_probability: Decimal | int | float | str,
    payout_multiplier: Decimal | int | float | str,
) -> Decimal:
    """E[return]/stake = P(win) × multiplier, as percent."""
    rtp = _dec(win_probability) * _dec(payout_multiplier) * HUNDRED
    return rtp.quantize(MONEY_STEP)


def actual_rtp(wager_rub: Decimal | int | float | str, returned_rub: Decimal | int | float | str) -> Decimal | None:
    wager = _dec(wager_rub)
    if wager <= 0:
        return None
    return (HUNDRED * _dec(returned_rub) / wager).quantize(MONEY_STEP)


def corridor_half_width_pp(rounds: int) -> Decimal:
    """±100/√n percentage points. n=0 uses n=1 so the band stays honest: no rounds is wide."""
    n = max(int(rounds), 1)
    return (HUNDRED / Decimal(str(sqrt(n)))).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def exposure_pct(exposure_rub: Decimal | int | float | str, bank_rub: Decimal | int | float | str) -> Decimal | None:
    bank = _dec(bank_rub)
    if bank <= 0:
        return None
    return (HUNDRED * _dec(exposure_rub) / bank).quantize(MONEY_STEP)


def max_single_payout(bank_rub: Decimal | int | float | str, max_profit_pct: Decimal | int | float | str) -> Decimal:
    return money(_dec(bank_rub) * _dec(max_profit_pct) / HUNDRED)


def verify_sql(window: str) -> str:
    interval = WINDOW_SQL[window]
    return (
        "SELECT COALESCE(SUM(bet_rub), 0) FROM casino_games "
        f"WHERE created_at > now() - interval '{interval}'"
    )


def theoretical_for_game(
    game_type: str,
    *,
    commission_percent: Decimal,
    policies: Mapping[str, tuple[Decimal, Decimal]],
) -> Decimal | None:
    if game_type in HEAD_TO_HEAD_GAME_TYPES:
        return pvp_theoretical_rtp(commission_percent)
    policy = policies.get(game_type)
    if policy is None:
        return None
    return house_theoretical_rtp(policy[0], policy[1])


def risk_tone(delta_pp: Decimal, threshold_pp: Decimal) -> str:
    abs_delta = abs(delta_pp)
    if abs_delta >= threshold_pp:
        return "high"
    if abs_delta >= threshold_pp / 2:
        return "medium"
    return "low"


def build_risk_payload(
    *,
    window: str,
    deviation_pp: Decimal,
    settings: Mapping[str, object],
    house: Mapping[str, object] | None,
    open_pvp_banks_rub: Decimal,
    house_liability_rub: Decimal,
    verify_bet_rub: Decimal,
    game_rows: Sequence[Mapping[str, Any]],
    policy_rows: Sequence[Mapping[str, Any]],
    player_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if window not in WINDOWS:
        raise ValueError("window must be 24h, 7d, or 30d")
    threshold = _dec(deviation_pp)
    if threshold <= 0:
        raise ValueError("rtp_deviation_pp must be positive")

    commission = setting_amount(settings, "commission_rate_wagering_complete", "5")
    floor = setting_amount(settings, "bankroll_floor_rub", "0")
    profit_pct = setting_amount(settings, "max_profit_pct_per_round", "5")

    balance = _dec((house or {}).get("balance_rub"))
    reserved = _dec((house or {}).get("reserved_rub"))
    available = money(balance - reserved)
    target = money(floor * 2) if floor > 0 else available
    payout_mark = max_single_payout(available if available > 0 else balance, profit_pct)

    policies = {
        str(row["game_type"]): (_dec(row["win_probability"]), _dec(row["payout_multiplier"]))
        for row in policy_rows
        if row.get("game_type")
    }

    games_by_type = {row["game_type"]: row for row in game_rows}
    games: list[dict[str, Any]] = []
    for game_type in KNOWN_GAME_TYPES:
        row = games_by_type.get(game_type) or {}
        rounds = int(row.get("rounds") or 0)
        wager = _dec(row.get("wager_rub"))
        returned = _dec(row.get("returned_rub"))
        theoretical = theoretical_for_game(game_type, commission_percent=commission, policies=policies)
        actual = actual_rtp(wager, returned)
        half = corridor_half_width_pp(rounds)
        center = theoretical if theoretical is not None else (actual if actual is not None else HUNDRED)
        games.append(
            {
                "game_type": game_type,
                "rounds": rounds,
                "wager_rub": float(money(wager)),
                "returned_rub": float(money(returned)),
                "actual_rtp_pct": float(actual) if actual is not None else None,
                "theoretical_rtp_pct": float(theoretical) if theoretical is not None else None,
                "corridor_low_pct": float(max(Decimal("0"), center - half)),
                "corridor_high_pct": float(center + half),
            }
        )

    theo_by_game = {item["game_type"]: item["theoretical_rtp_pct"] for item in games}

    per_player: dict[int, dict[str, Any]] = {}
    for row in player_rows:
        telegram_id = int(row["telegram_id"])
        bucket = per_player.setdefault(
            telegram_id,
            {
                "telegram_id": telegram_id,
                "username": row.get("username"),
                "rounds": 0,
                "wager_rub": Decimal("0"),
                "returned_rub": Decimal("0"),
                "theo_weight": Decimal("0"),
            },
        )
        wager = _dec(row.get("wager_rub"))
        returned = _dec(row.get("returned_rub"))
        rounds = int(row.get("rounds") or 0)
        bucket["rounds"] += rounds
        bucket["wager_rub"] += wager
        bucket["returned_rub"] += returned
        game_theo = theo_by_game.get(str(row.get("game_type")))
        if game_theo is not None and wager > 0:
            bucket["theo_weight"] += wager * Decimal(str(game_theo))
        if row.get("username") and not bucket["username"]:
            bucket["username"] = row.get("username")

    leaders: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    for bucket in per_player.values():
        wager = bucket["wager_rub"]
        returned = bucket["returned_rub"]
        player_rtp = actual_rtp(wager, returned)
        reference = None
        if wager > 0 and bucket["theo_weight"] > 0:
            reference = (bucket["theo_weight"] / wager).quantize(MONEY_STEP)
        net = money(returned - wager)
        item = {
            "telegram_id": bucket["telegram_id"],
            "username": bucket["username"],
            "rounds": bucket["rounds"],
            "wager_rub": float(money(wager)),
            "returned_rub": float(money(returned)),
            "net_rub": float(net),
            "player_rtp_pct": float(player_rtp) if player_rtp is not None else None,
            "game_rtp_pct": float(reference) if reference is not None else None,
        }
        leaders.append(item)
        if player_rtp is None or reference is None:
            continue
        delta = (player_rtp - reference).quantize(MONEY_STEP)
        tone = risk_tone(delta, threshold)
        if tone == "low":
            continue
        anomalies.append({**item, "delta_pp": float(delta), "risk": tone})

    anomalies.sort(key=lambda row: (-abs(float(row["delta_pp"])), -int(row["rounds"])))
    winners = sorted((row for row in leaders if row["net_rub"] > 0), key=lambda row: row["net_rub"], reverse=True)[:10]
    losers = sorted((row for row in leaders if row["net_rub"] < 0), key=lambda row: row["net_rub"])[:10]

    total_exposure = money(open_pvp_banks_rub + house_liability_rub)
    pct = exposure_pct(total_exposure, available if available > 0 else balance)

    return {
        "window": window,
        "rtp_deviation_pp": float(threshold),
        "verify": {
            "label": "sum(bet_rub) за окно, без фильтра статуса",
            "value_rub": float(money(verify_bet_rub)),
            "sql": verify_sql(window),
        },
        "bankroll": {
            "balance_rub": float(money(balance)),
            "reserved_rub": float(money(reserved)),
            "available_rub": float(available),
            "floor_rub": float(money(floor)),
            "target_rub": float(target),
            "max_payout_rub": float(payout_mark),
            "max_profit_pct_per_round": float(profit_pct),
        },
        "exposure": {
            "open_pvp_banks_rub": float(money(open_pvp_banks_rub)),
            "house_liability_rub": float(money(house_liability_rub)),
            "total_rub": float(total_exposure),
            "pct_of_bank": float(pct) if pct is not None else None,
        },
        "games": games,
        "anomalies": anomalies,
        "winners": winners,
        "losers": losers,
        "commission_complete_percent": float(commission),
    }


async def fetch_risk_snapshot(conn, *, window: str, deviation_pp: float) -> dict[str, Any]:
    if window not in WINDOWS:
        raise ValueError("window must be 24h, 7d, or 30d")
    interval = WINDOW_SQL[window]
    settings_rows = await conn.fetch(
        """
        SELECT key, value FROM casino_settings
        WHERE key = ANY($1::text[])
        """,
        [
            "commission_rate_wagering_complete",
            "bankroll_floor_rub",
            "max_profit_pct_per_round",
        ],
    )
    settings = {str(row["key"]): row["value"] for row in settings_rows}

    house = await conn.fetchrow(
        """
        SELECT balance_rub, reserved_rub
        FROM casino_house_accounts
        WHERE account_key = 'main'
        """
    )

    verify = await conn.fetchrow(
        f"""
        SELECT COALESCE(SUM(bet_rub), 0) AS bet_rub
        FROM casino_games
        WHERE created_at > now() - interval '{interval}'
        """
    )

    open_pvp = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(
            CASE WHEN status = 'active' THEN bet_rub * 2 ELSE bet_rub END
        ), 0) AS amount_rub
        FROM casino_games
        WHERE status IN ('waiting', 'active')
          AND game_type = ANY($1::text[])
          AND counterparty_kind = 'player'
        """,
        list(HEAD_TO_HEAD_GAME_TYPES),
    )

    house_liability = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(amount_rub), 0) AS amount_rub
        FROM casino_house_reservations
        WHERE status = 'active'
        """
    )

    game_rows = await conn.fetch(
        f"""
        SELECT game_type,
               COUNT(*)::int AS rounds,
               COALESCE(SUM(wager_rub), 0) AS wager_rub,
               COALESCE(SUM(returned_rub), 0) AS returned_rub
        FROM (
            SELECT game_type, bet_rub AS wager_rub,
                   CASE WHEN winner_id = creator_id THEN COALESCE(payout_rub, 0) ELSE 0 END AS returned_rub
            FROM casino_games
            WHERE status = 'finished'
              AND finished_at > now() - interval '{interval}'
            UNION ALL
            SELECT game_type, bet_rub AS wager_rub,
                   CASE WHEN winner_id = opponent_id THEN COALESCE(payout_rub, 0) ELSE 0 END AS returned_rub
            FROM casino_games
            WHERE status = 'finished'
              AND finished_at > now() - interval '{interval}'
              AND opponent_id IS NOT NULL
        ) plays
        GROUP BY game_type
        """
    )

    policy_rows = await conn.fetch(
        """
        SELECT game_type, win_probability, payout_multiplier
        FROM casino_house_policies
        WHERE is_active
        """
    )

    player_rows = await conn.fetch(
        f"""
        SELECT plays.telegram_id, bu.username, plays.game_type,
               COUNT(*)::int AS rounds,
               COALESCE(SUM(plays.wager_rub), 0) AS wager_rub,
               COALESCE(SUM(plays.returned_rub), 0) AS returned_rub
        FROM (
            SELECT creator_id AS telegram_id, game_type, bet_rub AS wager_rub,
                   CASE WHEN winner_id = creator_id THEN COALESCE(payout_rub, 0) ELSE 0 END AS returned_rub
            FROM casino_games
            WHERE status = 'finished'
              AND finished_at > now() - interval '{interval}'
            UNION ALL
            SELECT opponent_id AS telegram_id, game_type, bet_rub AS wager_rub,
                   CASE WHEN winner_id = opponent_id THEN COALESCE(payout_rub, 0) ELSE 0 END AS returned_rub
            FROM casino_games
            WHERE status = 'finished'
              AND finished_at > now() - interval '{interval}'
              AND opponent_id IS NOT NULL
        ) plays
        LEFT JOIN bot_users bu ON bu.user_id = plays.telegram_id
        GROUP BY plays.telegram_id, bu.username, plays.game_type
        """
    )

    return build_risk_payload(
        window=window,
        deviation_pp=Decimal(str(deviation_pp)),
        settings=settings,
        house=dict(house) if house else None,
        open_pvp_banks_rub=_dec(open_pvp["amount_rub"] if open_pvp else 0),
        house_liability_rub=_dec(house_liability["amount_rub"] if house_liability else 0),
        verify_bet_rub=_dec(verify["bet_rub"] if verify else 0),
        game_rows=game_rows,
        policy_rows=policy_rows,
        player_rows=player_rows,
    )


def self_check() -> None:
    if pvp_theoretical_rtp("15") != Decimal("92.50"):
        raise RuntimeError("15% commission must be 92.50% player RTP")
    if pvp_theoretical_rtp("6") != Decimal("97.00"):
        raise RuntimeError("6% commission must be 97.00% player RTP")
    if house_theoretical_rtp("0.5", "2") != Decimal("100.00"):
        raise RuntimeError("fair 50/50 ×2 must be 100% RTP")
    if actual_rtp("1000", "850") != Decimal("85.00"):
        raise RuntimeError("850/1000 must be 85% RTP")
    if corridor_half_width_pp(100) != Decimal("10.00"):
        raise RuntimeError("n=100 corridor half-width must be 10pp")
    if exposure_pct("500", "10000") != Decimal("5.00"):
        raise RuntimeError("500/10000 must be 5%")
    if max_single_payout("10000", "5") != Decimal("500.00"):
        raise RuntimeError("5% of 10000 must be 500")
    sql = verify_sql("7d").lower()
    if "sum(bet_rub)" not in sql or "7 days" not in sql:
        raise RuntimeError("verify SQL must be SUM(bet_rub) over 7 days")


self_check()
