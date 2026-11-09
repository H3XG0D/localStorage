"""Staff (operator/admin) casino slice of a client profile.

One builder, two scopes. Operator never receives `risk` or house-net fields —
stripping happens here, not in the UI.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping

from fastapi import HTTPException

from casino_risk import (
    MONEY_STEP,
    WINDOW_SQL,
    _dec,
    actual_rtp,
    risk_tone,
    setting_amount,
    theoretical_for_game,
)

logger = logging.getLogger("casino_client_profile")

SCOPE_OPERATOR = "operator"
SCOPE_ADMIN = "admin"
DEFAULT_HISTORY_LIMIT = 20
DEFAULT_RISK_WINDOW = "7d"
DEFAULT_RTP_DEVIATION_PP = Decimal("15")


def normalize_scope(scope: str | None) -> str:
    value = str(scope or "").strip().lower()
    if value not in {SCOPE_OPERATOR, SCOPE_ADMIN}:
        raise ValueError("scope must be operator or admin")
    return value


def apply_scope(payload: dict[str, object], *, scope: str) -> dict[str, object]:
    """Drop admin-only fields before the payload leaves the backend."""
    scoped = dict(payload)
    scoped["scope"] = scope
    if scope != SCOPE_ADMIN:
        scoped.pop("risk", None)
        scoped.pop("house_net_rub", None)
    return scoped


def payout_player_snapshot(profile: Mapping[str, object]) -> dict[str, object]:
    """Compact chip used by the casino payouts queue."""
    player = profile.get("player") if isinstance(profile.get("player"), Mapping) else {}
    raffle = profile.get("raffle") if isinstance(profile.get("raffle"), Mapping) else {}
    games = profile.get("recent_games") if isinstance(profile.get("recent_games"), list) else []
    compact: list[dict[str, object]] = []
    for item in games[:5]:
        if not isinstance(item, Mapping):
            continue
        compact.append(
            {
                "game_type": item.get("game_type"),
                "label": item.get("label"),
                "result": item.get("result"),
                "result_label": item.get("result_label"),
                "stake_rub": item.get("stake_rub"),
                "settled_at": item.get("settled_at"),
            }
        )
    return {
        "user_id": profile.get("player_id") or player.get("user_id"),
        "display_name": player.get("display_name"),
        "avatar_url": player.get("avatar_url"),
        "available_rub": _float_money(profile.get("available_rub")),
        "wagering": profile.get("wagering") or {},
        "payout_rail": profile.get("payout_rail") or {},
        "raffle_campaign_id": raffle.get("campaign_id"),
        "raffle_tickets": int(raffle.get("tickets") or 0),
        "recent_games": compact,
    }


def _float_money(value: object) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _withdrawal_row(row: Mapping[str, object]) -> dict[str, object]:
    from user_referral_withdraw import player_status_fields

    payload: dict[str, object] = {
        "id": int(row["id"]),
        "amount_rub": _float_money(row.get("amount_rub")),
        "method": row.get("method"),
        "crypto": row.get("crypto"),
        "network": row.get("network"),
        "status": row.get("status"),
        "requisites": row.get("requisites"),
        "payout_tx_hash": row.get("payout_tx_hash"),
        "created_at": _iso(row.get("created_at")),
        "processed_at": _iso(row.get("processed_at")),
        "source": "casino",
    }
    payload.update(player_status_fields({**dict(row), "source": "casino"}))
    return payload


async def _load_raffle(conn, player_id: int) -> dict[str, object]:
    from casino_raffle import _watch_campaign, remaining_ticket_count, remaining_ticket_rows

    camp = await _watch_campaign(conn)
    if not camp:
        return {"campaign_id": None, "tickets": 0, "status": None}
    campaign_id = int(camp["id"])
    rows = await remaining_ticket_rows(conn, campaign_id, set())
    tickets = remaining_ticket_count([row for row in rows if int(row["user_id"]) == player_id])
    return {
        "campaign_id": campaign_id,
        "tickets": int(tickets),
        "status": camp.get("status"),
    }


async def _load_withdrawals(conn, player_id: int) -> list[dict[str, object]]:
    rows = await conn.fetch(
        """
        SELECT id, amount_rub, method, crypto, network, status,
               requisites, payout_tx_hash, created_at, processed_at, operator_id
        FROM user_referral_withdrawals
        WHERE referrer_user_id = $1
          AND COALESCE(source, 'balance') = 'casino'
        ORDER BY created_at DESC
        LIMIT 30
        """,
        int(player_id),
    )
    return [_withdrawal_row(dict(row)) for row in rows]


async def _player_risk(conn, player_id: int, *, window: str = DEFAULT_RISK_WINDOW) -> dict[str, object]:
    from casino_finance import money

    if window not in WINDOW_SQL:
        window = DEFAULT_RISK_WINDOW
    interval = WINDOW_SQL[window]
    settings_rows = await conn.fetch(
        """
        SELECT key, value FROM casino_settings
        WHERE key = ANY($1::text[])
        """,
        ["commission_rate_wagering_complete"],
    )
    settings = {str(row["key"]): row["value"] for row in settings_rows}
    commission = setting_amount(settings, "commission_rate_wagering_complete", "5")
    policy_rows = await conn.fetch(
        """
        SELECT game_type, win_probability, payout_multiplier
        FROM casino_house_policies
        WHERE is_active
        """
    )
    policies = {
        str(row["game_type"]): (_dec(row["win_probability"]), _dec(row["payout_multiplier"]))
        for row in policy_rows
        if row.get("game_type")
    }
    player_rows = await conn.fetch(
        f"""
        SELECT plays.game_type,
               COUNT(*)::int AS rounds,
               COALESCE(SUM(plays.wager_rub), 0) AS wager_rub,
               COALESCE(SUM(plays.returned_rub), 0) AS returned_rub
        FROM (
            SELECT game_type, bet_rub AS wager_rub,
                   CASE WHEN winner_id = creator_id THEN COALESCE(payout_rub, 0) ELSE 0 END AS returned_rub
            FROM casino_games
            WHERE status = 'finished'
              AND finished_at > now() - interval '{interval}'
              AND creator_id = $1
            UNION ALL
            SELECT game_type, bet_rub AS wager_rub,
                   CASE WHEN winner_id = opponent_id THEN COALESCE(payout_rub, 0) ELSE 0 END AS returned_rub
            FROM casino_games
            WHERE status = 'finished'
              AND finished_at > now() - interval '{interval}'
              AND opponent_id = $1
        ) plays
        GROUP BY plays.game_type
        """,
        int(player_id),
    )
    wager_total = Decimal("0")
    returned_total = Decimal("0")
    rounds_total = 0
    theo_weight = Decimal("0")
    for row in player_rows:
        wager = _dec(row.get("wager_rub"))
        returned = _dec(row.get("returned_rub"))
        rounds_total += int(row.get("rounds") or 0)
        wager_total += wager
        returned_total += returned
        theo = theoretical_for_game(
            str(row.get("game_type") or ""),
            commission_percent=commission,
            policies=policies,
        )
        if theo is not None and wager > 0:
            theo_weight += wager * theo
    player_rtp = actual_rtp(wager_total, returned_total)
    reference = None
    if wager_total > 0 and theo_weight > 0:
        reference = (theo_weight / wager_total).quantize(MONEY_STEP)
    net = money(returned_total - wager_total)
    house_net = money(wager_total - returned_total)
    delta = None
    tone = None
    if player_rtp is not None and reference is not None:
        delta = (player_rtp - reference).quantize(MONEY_STEP)
        tone = risk_tone(delta, DEFAULT_RTP_DEVIATION_PP)
    return {
        "window": window,
        "rounds": rounds_total,
        "wager_rub": float(money(wager_total)),
        "returned_rub": float(money(returned_total)),
        "net_rub": float(net),
        "house_net_rub": float(house_net),
        "player_rtp_pct": float(player_rtp) if player_rtp is not None else None,
        "game_rtp_pct": float(reference) if reference is not None else None,
        "delta_pp": float(delta) if delta is not None else None,
        "risk": tone,
    }


async def build_casino_client_profile(
    conn,
    player_id: int,
    *,
    scope: str,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    include_withdrawals: bool = True,
    raise_if_missing: bool = True,
) -> dict[str, object]:
    from casino_player_history import load_player_history
    from casino_player_profile import load_web_player_profile, player_exists

    uid = int(player_id)
    scoped = normalize_scope(scope)
    if raise_if_missing and not await player_exists(conn, uid):
        raise HTTPException(status_code=404, detail="Игрок не найден")

    web = await load_web_player_profile(conn, uid, viewer_id=uid)
    own = web.get("own") if isinstance(web.get("own"), Mapping) else {}
    history: dict[str, object] = {"items": [], "next_before": None}
    try:
        history = await load_player_history(
            conn,
            uid,
            viewer_id=uid,
            limit=max(1, int(history_limit)),
            skip_exists=True,
        )
    except Exception:
        logger.exception("casino client history failed player_id=%s", uid)
        history = {"items": [], "next_before": None}

    raffle: dict[str, object] = {"campaign_id": None, "tickets": 0, "status": None}
    try:
        raffle = await _load_raffle(conn, uid)
    except Exception:
        logger.exception("casino client raffle failed player_id=%s", uid)

    withdrawals: list[dict[str, object]] = []
    if include_withdrawals:
        try:
            withdrawals = await _load_withdrawals(conn, uid)
        except Exception:
            logger.exception("casino client withdrawals failed player_id=%s", uid)
            withdrawals = []

    items = history.get("items") if isinstance(history.get("items"), list) else []
    lifetime = _float_money(web.get("lifetime_wager_rub"))
    played = lifetime > 0 or bool(items) or bool(withdrawals)

    payload: dict[str, object] = {
        "success": True,
        "player_id": uid,
        "played": played,
        "player": web.get("player"),
        "registered_at": web.get("registered_at"),
        "week_start": web.get("week_start"),
        "wager_rub": web.get("wager_rub"),
        "lifetime_wager_rub": web.get("lifetime_wager_rub"),
        "wager_by_game": web.get("wager_by_game") or [],
        "level": web.get("level"),
        "next_level": web.get("next_level"),
        "available_rub": _float_money(own.get("available_rub")),
        "commission_profile": own.get("commission_profile"),
        "commission_rate": own.get("commission_rate"),
        "cashback_percent": own.get("cashback_percent"),
        "wagering": own.get("wagering") or {},
        "payout_rail": own.get("payout_rail") or {},
        "raffle": raffle,
        "recent_games": items,
        "history_next_before": history.get("next_before"),
        "withdrawals": withdrawals,
    }
    if scoped == SCOPE_ADMIN:
        try:
            payload["risk"] = await _player_risk(conn, uid)
        except Exception:
            logger.exception("casino client risk failed player_id=%s", uid)
            payload["risk"] = None
    return apply_scope(payload, scope=scoped)


async def load_casino_client_history(
    conn,
    player_id: int,
    *,
    before: str | None = None,
    game_type: str | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    from casino_player_history import load_player_history
    from casino_player_profile import player_exists

    uid = int(player_id)
    if not await player_exists(conn, uid):
        raise HTTPException(status_code=404, detail="Игрок не найден")
    packed = await load_player_history(
        conn,
        uid,
        viewer_id=uid,
        limit=limit or DEFAULT_HISTORY_LIMIT,
        before=before,
        game_type=game_type,
        skip_exists=True,
    )
    return {
        "success": True,
        "player_id": uid,
        "items": packed.get("items") or [],
        "next_before": packed.get("next_before"),
    }
