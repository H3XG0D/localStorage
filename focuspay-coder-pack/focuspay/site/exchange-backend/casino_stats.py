"""Normalized casino round stats: handle, GGR, NGR, hold, RTP.

GGR is always player handle minus player payouts. Bot stakes are not turnover.
Rake on bot-backed tables is already inside house P&L — do not add them.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from casino_clans import list_top as clans_list_top
from casino_finance import money
from casino_risk import corridor_half_width_pp, pvp_theoretical_rtp, risk_tone
from finance_pnl import fetch_casino_owner_profit, fetch_casino_owner_profit_daily

PVP_LIKE = frozenset({"pvp_dice", "baccara", "blackjack", "cub"})
POT_RAKE_TYPES = frozenset({"jackpot", "fixed_room"})
DEFAULT_RAKE_PCT = Decimal("5")
SHARE_TABLE_LIMIT = 40

_SOURCE_PLAYER_SQL = """
CASE
    WHEN g.id IS NULL THEN NULL
    WHEN g.opponent_id IS NULL THEN g.creator_id
    WHEN g.winner_id = g.creator_id THEN g.opponent_id
    WHEN g.winner_id = g.opponent_id THEN g.creator_id
    ELSE g.creator_id
END
"""

_ROUNDS_SQL = """
SELECT
    day,
    surface,
    game_type,
    round_key,
    player_count,
    bot_count,
    handle_rub,
    house_stake_rub,
    player_payout_rub,
    rake_rub
FROM (
    SELECT
        COALESCE(g.finished_at, g.created_at)::date AS day,
        'legacy'::text AS surface,
        g.game_type::text AS game_type,
        g.game_id::text AS round_key,
        CASE
            WHEN g.counterparty_kind IN ('house_robot', 'pvp_robot') OR g.game_type = 'raffle' THEN 1
            ELSE 2
        END::int AS player_count,
        CASE WHEN g.counterparty_kind IN ('house_robot', 'pvp_robot') THEN 1 ELSE 0 END::int AS bot_count,
        CASE
            WHEN g.counterparty_kind IN ('house_robot', 'pvp_robot') OR g.game_type = 'raffle' THEN g.bet_rub
            ELSE g.bet_rub * 2
        END AS handle_rub,
        CASE WHEN g.counterparty_kind IN ('house_robot', 'pvp_robot') THEN g.bet_rub ELSE 0 END AS house_stake_rub,
        COALESCE(g.payout_rub, 0) AS player_payout_rub,
        COALESCE(g.commission_rub, 0) AS rake_rub
    FROM casino_games g
    WHERE g.status = 'finished'

    UNION ALL

    SELECT
        COALESCE(t.settled_at, s.created_at)::date AS day,
        'v2'::text AS surface,
        CASE WHEN t.game_type = 'pvp_emoji' THEN 'pvp_dice' ELSE t.game_type::text END AS game_type,
        t.table_id::text AS round_key,
        players.n AS player_count,
        bots.n AS bot_count,
        t.stake_rub * players.n AS handle_rub,
        t.stake_rub * bots.n AS house_stake_rub,
        COALESCE(player_paid.amount, CASE WHEN bots.n = 0 THEN s.payout_rub ELSE 0 END) AS player_payout_rub,
        COALESCE(s.commission_rub, 0) AS rake_rub
    FROM casino_v2_settlements s
    JOIN casino_v2_tables t ON t.id = s.table_id
    CROSS JOIN LATERAL (
        SELECT COUNT(*)::int AS n
        FROM casino_v2_table_seats p
        WHERE p.table_id = t.id AND p.participant_kind = 'player'
    ) players
    CROSS JOIN LATERAL (
        SELECT COUNT(*)::int AS n
        FROM casino_v2_table_seats b
        WHERE b.table_id = t.id AND b.participant_kind = 'bot'
    ) bots
    LEFT JOIN LATERAL (
        SELECT SUM((elem->>'amount_rub')::numeric) AS amount
        FROM jsonb_array_elements(COALESCE(s.payload->'payouts', '[]'::jsonb)) AS elem
        JOIN casino_v2_table_seats st
          ON st.table_id = t.id
         AND st.seat_no = (elem->>'seat_no')::int
        WHERE st.participant_kind = 'player'
    ) player_paid ON TRUE

    UNION ALL

    SELECT
        r.settled_at::date AS day,
        'jackpot'::text AS surface,
        'jackpot'::text AS game_type,
        r.round_id::text AS round_key,
        COALESCE((
            SELECT COUNT(DISTINCT b.user_id)::int
            FROM casino_jackpot_bets b
            WHERE b.round_pk = r.id
        ), 0) AS player_count,
        0 AS bot_count,
        COALESCE((
            SELECT SUM(b.amount_rub) FROM casino_jackpot_bets b WHERE b.round_pk = r.id
        ), r.pot_rub) AS handle_rub,
        0 AS house_stake_rub,
        COALESCE(r.payout_rub, 0) AS player_payout_rub,
        COALESCE(r.rake_rub, 0) AS rake_rub
    FROM casino_jackpot_rounds r
    WHERE r.status = 'settled' AND r.settled_at IS NOT NULL

    UNION ALL

    SELECT
        r.settled_at::date AS day,
        'rooms'::text AS surface,
        'fixed_room'::text AS game_type,
        r.room_id::text AS round_key,
        players.n AS player_count,
        bots.n AS bot_count,
        r.stake_rub * players.n AS handle_rub,
        r.stake_rub * bots.n AS house_stake_rub,
        CASE WHEN winner_human.ok THEN COALESCE(r.payout_rub, 0) ELSE 0 END AS player_payout_rub,
        COALESCE(r.rake_rub, 0) AS rake_rub
    FROM casino_fixed_room_rounds r
    CROSS JOIN LATERAL (
        SELECT COUNT(*)::int AS n
        FROM casino_fixed_room_seats s
        WHERE s.room_pk = r.id AND s.participant_kind = 'player'
    ) players
    CROSS JOIN LATERAL (
        SELECT COUNT(*)::int AS n
        FROM casino_fixed_room_seats s
        WHERE s.room_pk = r.id AND s.participant_kind = 'bot'
    ) bots
    CROSS JOIN LATERAL (
        SELECT EXISTS (
            SELECT 1 FROM casino_fixed_room_seats s
            WHERE s.room_pk = r.id
              AND s.participant_kind = 'player'
              AND s.user_id = r.winner_id
        ) AS ok
    ) winner_human
    WHERE r.status = 'settled' AND r.settled_at IS NOT NULL
) rounds
WHERE ($1::date IS NULL OR day BETWEEN $1 AND $2)
"""

_PLAYER_EVENTS_SQL = """
SELECT day, player_id, handle_rub, payout_rub, round_key
FROM (
    SELECT
        COALESCE(g.finished_at, g.created_at)::date AS day,
        g.creator_id AS player_id,
        g.bet_rub AS handle_rub,
        CASE WHEN g.winner_id = g.creator_id THEN COALESCE(g.payout_rub, 0) ELSE 0 END AS payout_rub,
        g.game_id::text AS round_key
    FROM casino_games g
    WHERE g.status = 'finished'

    UNION ALL

    SELECT
        COALESCE(g.finished_at, g.created_at)::date AS day,
        g.opponent_id AS player_id,
        g.bet_rub AS handle_rub,
        CASE WHEN g.winner_id = g.opponent_id THEN COALESCE(g.payout_rub, 0) ELSE 0 END AS payout_rub,
        g.game_id::text AS round_key
    FROM casino_games g
    WHERE g.status = 'finished'
      AND g.opponent_id IS NOT NULL
      AND g.counterparty_kind = 'player'

    UNION ALL

    SELECT
        COALESCE(t.settled_at, s.created_at)::date AS day,
        st.telegram_id AS player_id,
        t.stake_rub AS handle_rub,
        COALESCE((
            SELECT SUM((elem->>'amount_rub')::numeric)
            FROM jsonb_array_elements(COALESCE(s.payload->'payouts', '[]'::jsonb)) AS elem
            WHERE (elem->>'seat_no')::int = st.seat_no
        ), 0) AS payout_rub,
        t.table_id::text AS round_key
    FROM casino_v2_settlements s
    JOIN casino_v2_tables t ON t.id = s.table_id
    JOIN casino_v2_table_seats st
      ON st.table_id = t.id AND st.participant_kind = 'player' AND st.telegram_id IS NOT NULL

    UNION ALL

    SELECT
        r.settled_at::date AS day,
        b.user_id AS player_id,
        b.amount_rub AS handle_rub,
        CASE WHEN b.user_id = r.winner_id THEN COALESCE(r.payout_rub, 0) ELSE 0 END AS payout_rub,
        r.round_id::text AS round_key
    FROM casino_jackpot_bets b
    JOIN casino_jackpot_rounds r ON r.id = b.round_pk
    WHERE r.status = 'settled' AND r.settled_at IS NOT NULL

    UNION ALL

    SELECT
        r.settled_at::date AS day,
        s.user_id AS player_id,
        r.stake_rub AS handle_rub,
        CASE WHEN s.user_id = r.winner_id THEN COALESCE(r.payout_rub, 0) ELSE 0 END AS payout_rub,
        r.room_id::text AS round_key
    FROM casino_fixed_room_seats s
    JOIN casino_fixed_room_rounds r ON r.id = s.room_pk
    WHERE r.status = 'settled'
      AND r.settled_at IS NOT NULL
      AND s.participant_kind = 'player'
      AND s.user_id IS NOT NULL
) events
WHERE player_id IS NOT NULL
  AND ($1::date IS NULL OR day BETWEEN $1 AND $2)
"""

_FIRST_SEEN_SQL = """
SELECT player_id, MIN(day) AS first_day
FROM (
    SELECT COALESCE(g.finished_at, g.created_at)::date AS day, g.creator_id AS player_id
    FROM casino_games g WHERE g.status = 'finished'
    UNION ALL
    SELECT COALESCE(g.finished_at, g.created_at)::date, g.opponent_id
    FROM casino_games g
    WHERE g.status = 'finished' AND g.opponent_id IS NOT NULL AND g.counterparty_kind = 'player'
    UNION ALL
    SELECT COALESCE(t.settled_at, s.created_at)::date, st.telegram_id
    FROM casino_v2_settlements s
    JOIN casino_v2_tables t ON t.id = s.table_id
    JOIN casino_v2_table_seats st ON st.table_id = t.id AND st.participant_kind = 'player'
    UNION ALL
    SELECT r.settled_at::date, b.user_id
    FROM casino_jackpot_bets b
    JOIN casino_jackpot_rounds r ON r.id = b.round_pk
    WHERE r.status = 'settled' AND r.settled_at IS NOT NULL
    UNION ALL
    SELECT r.settled_at::date, s.user_id
    FROM casino_fixed_room_seats s
    JOIN casino_fixed_room_rounds r ON r.id = s.room_pk
    WHERE r.status = 'settled' AND s.participant_kind = 'player' AND s.user_id IS NOT NULL
) firsts
WHERE player_id IS NOT NULL
GROUP BY player_id
"""

_TOP_PLAYERS_SQL = """
SELECT
    e.player_id,
    bu.username,
    bu.first_name,
    COUNT(DISTINCT e.round_key)::int AS rounds,
    COALESCE(SUM(e.handle_rub), 0) AS handle_rub,
    COALESCE(SUM(e.payout_rub), 0) AS payout_rub
FROM (
    """ + _PLAYER_EVENTS_SQL + """
) e
LEFT JOIN bot_users bu ON bu.user_id = e.player_id
GROUP BY e.player_id, bu.username, bu.first_name
ORDER BY handle_rub DESC
LIMIT 10
"""

_COSTS_SQL = """
SELECT
    COALESCE((
        SELECT SUM(cashback_rub) FROM casino_player_cashback
        WHERE status = 'accrued'
          AND ($1::date IS NULL OR accrued_at::date BETWEEN $1 AND $2)
    ), 0) AS cashback_rub,
    COALESCE((
        SELECT SUM(bonus_rub) FROM casino_level_bonus_grants
        WHERE ($1::date IS NULL OR granted_at::date BETWEEN $1 AND $2)
    ), 0) AS bonus_rub,
    COALESCE((
        SELECT SUM(amount_rub) FROM casino_commission_ledger
        WHERE recipient_type = 'creator'
          AND status IN ('accrued', 'paid')
          AND ($1::date IS NULL OR created_at::date BETWEEN $1 AND $2)
    ), 0) AS creator_share_rub,
    COALESCE((
        SELECT SUM(amount_rub) FROM casino_commission_ledger
        WHERE recipient_type IN ('referrer_l1', 'referrer_l2')
          AND status IN ('accrued', 'paid')
          AND ($1::date IS NULL OR created_at::date BETWEEN $1 AND $2)
    ), 0) AS referral_share_rub
"""

_REFERRAL_DIST_SQL = """
SELECT
    CASE WHEN c.recipient_type = 'referrer_l2' THEN 'l2' ELSE 'l1' END AS level,
    c.recipient_id,
    recv.username AS recipient_username,
    recv.first_name AS recipient_first_name,
    (""" + _SOURCE_PLAYER_SQL + """) AS source_player_id,
    src.username AS source_username,
    src.first_name AS source_first_name,
    COUNT(*)::int AS games,
    COALESCE(SUM(c.amount_rub), 0) AS amount_rub
FROM casino_commission_ledger c
LEFT JOIN casino_games g ON g.id = c.game_id
LEFT JOIN bot_users recv ON recv.user_id = c.recipient_id
LEFT JOIN bot_users src ON src.user_id = (""" + _SOURCE_PLAYER_SQL + """)
WHERE c.recipient_type IN ('referrer_l1', 'referrer_l2')
  AND c.status IN ('accrued', 'paid')
  AND ($1::date IS NULL OR c.created_at::date BETWEEN $1 AND $2)
GROUP BY 1, 2, 3, 4, 5, 6, 7
ORDER BY amount_rub DESC
"""

_CREATOR_DIST_SQL = """
SELECT
    c.creator_account_id,
    wu.telegram_user_id AS recipient_id,
    COALESCE(wu.username, wu.display_name) AS recipient_username,
    NULL::text AS recipient_first_name,
    (""" + _SOURCE_PLAYER_SQL + """) AS source_player_id,
    src.username AS source_username,
    src.first_name AS source_first_name,
    COUNT(*)::int AS games,
    COALESCE(SUM(c.amount_rub), 0) AS amount_rub
FROM casino_commission_ledger c
LEFT JOIN casino_games g ON g.id = c.game_id
LEFT JOIN casino_creator_accounts acc ON acc.id = c.creator_account_id
LEFT JOIN web_users wu ON wu.id = acc.web_user_id
LEFT JOIN bot_users src ON src.user_id = (""" + _SOURCE_PLAYER_SQL + """)
WHERE c.recipient_type = 'creator'
  AND c.status IN ('accrued', 'paid')
  AND ($1::date IS NULL OR c.created_at::date BETWEEN $1 AND $2)
GROUP BY 1, 2, 3, 4, 5, 6, 7
ORDER BY amount_rub DESC
"""

_CASHBACK_DIST_SQL = """
SELECT
    cb.telegram_id AS recipient_id,
    bu.username AS recipient_username,
    bu.first_name AS recipient_first_name,
    COUNT(*)::int AS games,
    COALESCE(SUM(cb.cashback_rub), 0) AS amount_rub
FROM casino_player_cashback cb
LEFT JOIN bot_users bu ON bu.user_id = cb.telegram_id
WHERE cb.status = 'accrued'
  AND ($1::date IS NULL OR cb.accrued_at::date BETWEEN $1 AND $2)
GROUP BY 1, 2, 3
ORDER BY amount_rub DESC
"""

_BONUS_DIST_SQL = """
SELECT
    b.telegram_id AS recipient_id,
    bu.username AS recipient_username,
    bu.first_name AS recipient_first_name,
    COUNT(*)::int AS games,
    COALESCE(SUM(b.bonus_rub), 0) AS amount_rub
FROM casino_level_bonus_grants b
LEFT JOIN bot_users bu ON bu.user_id = b.telegram_id
WHERE ($1::date IS NULL OR b.granted_at::date BETWEEN $1 AND $2)
GROUP BY 1, 2, 3
ORDER BY amount_rub DESC
"""

_CASHIER_SQL = """
SELECT
    COALESCE((
        SELECT SUM(amount_rub) FROM casino_deposit_credits
        WHERE status IN ('credited', 'legacy_reconciled')
          AND ($1::date IS NULL OR credited_at::date BETWEEN $1 AND $2)
    ), 0) + COALESCE((
        SELECT SUM(amount_rub) FROM casino_crypto_credits
        WHERE status = 'credited'
          AND ($1::date IS NULL OR created_at::date BETWEEN $1 AND $2)
    ), 0) AS deposited_rub,
    COALESCE((
        SELECT COUNT(*) FROM casino_deposit_credits
        WHERE status IN ('credited', 'legacy_reconciled')
          AND ($1::date IS NULL OR credited_at::date BETWEEN $1 AND $2)
    ), 0) + COALESCE((
        SELECT COUNT(*) FROM casino_crypto_credits
        WHERE status = 'credited'
          AND ($1::date IS NULL OR created_at::date BETWEEN $1 AND $2)
    ), 0) AS deposit_count,
    COALESCE((
        SELECT SUM(amount_rub) FROM user_referral_withdrawals
        WHERE COALESCE(source, 'balance') = 'casino'
          AND status = 'paid'
          AND ($1::date IS NULL OR COALESCE(processed_at, created_at)::date BETWEEN $1 AND $2)
    ), 0) AS withdrawn_rub,
    COALESCE((
        SELECT SUM(amount_rub) FROM user_referral_withdrawals
        WHERE COALESCE(source, 'balance') = 'casino'
          AND status = 'pending'
    ), 0) AS pending_withdraw_rub
"""


def empty_casino_stats(*, d_from: date | None = None, d_to: date | None = None) -> dict:
    daily = []
    if d_from and d_to and d_from <= d_to:
        cursor = d_from
        while cursor <= d_to:
            daily.append(
                {"date": cursor.isoformat(), "rounds": 0, "handle_rub": 0.0, "ggr_rub": 0.0, "rake_rub": 0.0, "owner_profit_rub": 0.0}
            )
            cursor += timedelta(days=1)
    return {
        "period": {"from": d_from.isoformat() if d_from else None, "to": d_to.isoformat() if d_to else None},
        "volume": {
            "handle_rub": 0.0,
            "player_payout_rub": 0.0,
            "ggr_rub": 0.0,
            "rake_rub": 0.0,
            "hold_pct": None,
            "rtp_pct": None,
            "rounds": 0,
            "avg_bet_rub": None,
            "bot_backed_stake_rub": 0.0,
        },
        "ggr_breakdown": {
            "pvp_rake_rub": 0.0,
            "jackpot_rake_rub": 0.0,
            "rooms_rake_rub": 0.0,
            "house_vs_bots_rub": 0.0,
        },
        "costs": {
            "cashback_rub": 0.0,
            "bonus_rub": 0.0,
            "creator_share_rub": 0.0,
            "referral_share_rub": 0.0,
            "total_rub": 0.0,
        },
        "ngr_rub": 0.0,
        "owner": {
            "commission_profit_rub": 0.0,
            "house_game_profit_rub": 0.0,
            "owner_profit_rub": 0.0,
        },
        "reconciliation": {"ggr_rub": 0.0, "owner_profit_rub": 0.0, "diff_rub": 0.0},
        "by_type": [],
        "daily": daily,
        "players": {"active": 0, "new": 0, "avg_handle_rub": None, "top": []},
        "cashier": {
            "deposited_rub": 0.0,
            "deposit_count": 0,
            "withdrawn_rub": 0.0,
            "pending_withdraw_rub": 0.0,
        },
        "bankroll": {"balance_rub": 0.0, "reserved_rub": 0.0, "available_rub": 0.0},
        "top_clans": [],
        "distributions": {
            "referrals": empty_share_table(),
            "creators": empty_share_table(),
            "cashback": empty_share_table(),
            "bonuses": empty_share_table(),
        },
    }


def empty_share_table() -> dict:
    return {"total_rub": 0.0, "shown_rub": 0.0, "hidden_count": 0, "hidden_rub": 0.0, "rows": []}


def _int_or_none(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _person_name(*parts: object) -> str | None:
    for part in parts:
        text = str(part or "").strip()
        if text:
            return text
    return None


def clip_share_table(rows: list | None, *, total_rub: float | None = None, limit: int = SHARE_TABLE_LIMIT) -> dict:
    """Keep the heaviest rows. shown_rub + hidden_rub always equals total_rub."""
    normalized: list[dict] = []
    for row in rows or []:
        mapping = dict(row)
        amount = _f(mapping.get("amount_rub"))
        if abs(amount) < 0.0001:
            continue
        normalized.append(
            {
                "recipient_id": _int_or_none(mapping.get("recipient_id")),
                "recipient_username": _person_name(mapping.get("recipient_username"), mapping.get("recipient_first_name")),
                "creator_account_id": _int_or_none(mapping.get("creator_account_id")),
                "source_player_id": _int_or_none(mapping.get("source_player_id")),
                "source_username": _person_name(mapping.get("source_username"), mapping.get("source_first_name")),
                "level": mapping.get("level") or None,
                "games": int(mapping.get("games") or 0),
                "amount_rub": amount,
            }
        )
    normalized.sort(key=lambda item: item["amount_rub"], reverse=True)
    shown = normalized[:limit]
    rest = normalized[limit:]
    shown_rub = round(sum(item["amount_rub"] for item in shown), 2)
    rest_rub = round(sum(item["amount_rub"] for item in rest), 2)
    row_total = round(shown_rub + rest_rub, 2)
    total = round(total_rub, 2) if total_rub is not None else row_total
    return {
        "total_rub": total,
        "shown_rub": shown_rub,
        "hidden_count": len(rest),
        "hidden_rub": round(total - shown_rub, 2),
        "rows": shown,
    }


def _f(value) -> float:
    if value is None:
        return 0.0
    return float(money(value))


def _pct(numerator: float, denominator: float) -> float | None:
    if abs(denominator) < 1e-9:
        return None
    return round(100.0 * numerator / denominator, 2)


def _theoretical_rtp(game_type: str) -> float | None:
    if game_type in PVP_LIKE:
        return float(pvp_theoretical_rtp(DEFAULT_RAKE_PCT))
    if game_type in POT_RAKE_TYPES:
        return float((Decimal("100") - DEFAULT_RAKE_PCT).quantize(Decimal("0.01")))
    return None


def _rtp_tone(actual: float | None, theoretical: float | None, rounds: int) -> str | None:
    if actual is None or theoretical is None:
        return None
    delta = Decimal(str(actual)) - Decimal(str(theoretical))
    threshold = corridor_half_width_pp(rounds)
    return risk_tone(delta, threshold)


def assemble_casino_stats(
    *,
    round_rows: list,
    player_rows: list,
    first_seen_rows: list | None = None,
    costs_row=None,
    cashier_row=None,
    bankroll_row=None,
    owner: dict | None = None,
    owner_daily: dict[str, float] | None = None,
    top_clans: list | None = None,
    period_player_ids: list[int] | None = None,
    referral_rows: list | None = None,
    creator_rows: list | None = None,
    cashback_rows: list | None = None,
    bonus_rows: list | None = None,
    d_from: date | None = None,
    d_to: date | None = None,
) -> dict:
    """Pure aggregation. GGR of each round is handle − player payouts."""
    out = empty_casino_stats(d_from=d_from, d_to=d_to)
    rounds_norm: list[dict] = []
    for row in round_rows or []:
        mapping = dict(row)
        handle = _f(mapping.get("handle_rub"))
        payout = _f(mapping.get("player_payout_rub"))
        ggr = round(handle - payout, 2)
        bot_count = int(mapping.get("bot_count") or 0)
        player_count = int(mapping.get("player_count") or 0)
        surface = str(mapping.get("surface") or "")
        game_type = str(mapping.get("game_type") or "")
        day = mapping.get("day")
        day_key = day.isoformat() if hasattr(day, "isoformat") else str(day or "")
        rounds_norm.append(
            {
                "day": day_key,
                "surface": surface,
                "game_type": game_type,
                "round_key": str(mapping.get("round_key") or ""),
                "player_count": player_count,
                "bot_count": bot_count,
                "handle_rub": handle,
                "house_stake_rub": _f(mapping.get("house_stake_rub")),
                "player_payout_rub": payout,
                "rake_rub": _f(mapping.get("rake_rub")),
                "ggr_rub": ggr,
            }
        )

    handle = round(sum(item["handle_rub"] for item in rounds_norm), 2)
    payouts = round(sum(item["player_payout_rub"] for item in rounds_norm), 2)
    ggr = round(sum(item["ggr_rub"] for item in rounds_norm), 2)
    rake = round(sum(item["rake_rub"] for item in rounds_norm), 2)
    house_stake = round(sum(item["house_stake_rub"] for item in rounds_norm), 2)
    player_seats = sum(item["player_count"] for item in rounds_norm)
    round_count = len(rounds_norm)

    pvp_rake = round(
        sum(
            item["ggr_rub"]
            for item in rounds_norm
            if item["bot_count"] == 0 and item["surface"] in {"legacy", "v2"}
        ),
        2,
    )
    jackpot_rake = round(sum(item["ggr_rub"] for item in rounds_norm if item["surface"] == "jackpot"), 2)
    rooms_rake = round(
        sum(item["ggr_rub"] for item in rounds_norm if item["surface"] == "rooms" and item["bot_count"] == 0),
        2,
    )
    house_vs_bots = round(sum(item["ggr_rub"] for item in rounds_norm if item["bot_count"] > 0), 2)

    out["volume"] = {
        "handle_rub": handle,
        "player_payout_rub": payouts,
        "ggr_rub": ggr,
        "rake_rub": rake,
        "hold_pct": _pct(ggr, handle),
        "rtp_pct": _pct(payouts, handle),
        "rounds": round_count,
        "avg_bet_rub": round(handle / player_seats, 2) if player_seats else None,
        "bot_backed_stake_rub": house_stake,
    }
    out["ggr_breakdown"] = {
        "pvp_rake_rub": pvp_rake,
        "jackpot_rake_rub": jackpot_rake,
        "rooms_rake_rub": rooms_rake,
        "house_vs_bots_rub": house_vs_bots,
    }

    costs = dict(costs_row or {})
    cashback = _f(costs.get("cashback_rub"))
    bonus = _f(costs.get("bonus_rub"))
    creator = _f(costs.get("creator_share_rub"))
    referral = _f(costs.get("referral_share_rub"))
    costs_total = round(cashback + bonus + creator + referral, 2)
    out["costs"] = {
        "cashback_rub": cashback,
        "bonus_rub": bonus,
        "creator_share_rub": creator,
        "referral_share_rub": referral,
        "total_rub": costs_total,
    }
    out["ngr_rub"] = round(ggr - costs_total, 2)

    owner_pack = owner or {
        "commission_profit_rub": 0.0,
        "house_game_profit_rub": 0.0,
        "owner_profit_rub": 0.0,
    }
    out["owner"] = {
        "commission_profit_rub": round(float(owner_pack.get("commission_profit_rub") or 0), 2),
        "house_game_profit_rub": round(float(owner_pack.get("house_game_profit_rub") or 0), 2),
        "owner_profit_rub": round(float(owner_pack.get("owner_profit_rub") or 0), 2),
    }
    owner_profit = out["owner"]["owner_profit_rub"]
    out["reconciliation"] = {
        "ggr_rub": ggr,
        "owner_profit_rub": owner_profit,
        "diff_rub": round(ggr - owner_profit, 2),
    }

    by_type: dict[str, dict] = {}
    for item in rounds_norm:
        bucket = by_type.setdefault(
            item["game_type"],
            {"game_type": item["game_type"], "rounds": 0, "handle_rub": 0.0, "player_payout_rub": 0.0, "ggr_rub": 0.0, "rake_rub": 0.0},
        )
        bucket["rounds"] += 1
        bucket["handle_rub"] = round(bucket["handle_rub"] + item["handle_rub"], 2)
        bucket["player_payout_rub"] = round(bucket["player_payout_rub"] + item["player_payout_rub"], 2)
        bucket["ggr_rub"] = round(bucket["ggr_rub"] + item["ggr_rub"], 2)
        bucket["rake_rub"] = round(bucket["rake_rub"] + item["rake_rub"], 2)
    typed = []
    for bucket in by_type.values():
        theoretical = _theoretical_rtp(bucket["game_type"])
        actual = _pct(bucket["player_payout_rub"], bucket["handle_rub"])
        typed.append(
            {
                **bucket,
                "hold_pct": _pct(bucket["ggr_rub"], bucket["handle_rub"]),
                "rtp_pct": actual,
                "theoretical_rtp_pct": theoretical,
                "rtp_tone": _rtp_tone(actual, theoretical, bucket["rounds"]),
            }
        )
    typed.sort(key=lambda row: row["handle_rub"], reverse=True)
    out["by_type"] = typed

    daily_map: dict[str, dict] = {}
    for item in rounds_norm:
        day_key = item["day"]
        bucket = daily_map.setdefault(
            day_key,
            {"date": day_key, "rounds": 0, "handle_rub": 0.0, "ggr_rub": 0.0, "rake_rub": 0.0, "owner_profit_rub": 0.0},
        )
        bucket["rounds"] += 1
        bucket["handle_rub"] = round(bucket["handle_rub"] + item["handle_rub"], 2)
        bucket["ggr_rub"] = round(bucket["ggr_rub"] + item["ggr_rub"], 2)
        bucket["rake_rub"] = round(bucket["rake_rub"] + item["rake_rub"], 2)
    owner_daily = owner_daily or {}
    for day_key, profit in owner_daily.items():
        bucket = daily_map.setdefault(
            day_key,
            {"date": day_key, "rounds": 0, "handle_rub": 0.0, "ggr_rub": 0.0, "rake_rub": 0.0, "owner_profit_rub": 0.0},
        )
        bucket["owner_profit_rub"] = round(float(profit or 0), 2)
    if d_from and d_to and d_from <= d_to:
        cursor = d_from
        filled = []
        while cursor <= d_to:
            key = cursor.isoformat()
            filled.append(
                daily_map.get(
                    key,
                    {"date": key, "rounds": 0, "handle_rub": 0.0, "ggr_rub": 0.0, "rake_rub": 0.0, "owner_profit_rub": 0.0},
                )
            )
            cursor += timedelta(days=1)
        out["daily"] = filled
    else:
        out["daily"] = [daily_map[key] for key in sorted(daily_map)]

    top = []
    for row in player_rows or []:
        mapping = dict(row)
        player_id = int(mapping.get("player_id") or mapping.get("telegram_id") or 0)
        if not player_id:
            continue
        handle_p = _f(mapping.get("handle_rub") if mapping.get("handle_rub") is not None else mapping.get("total_bet"))
        payout_p = _f(mapping.get("payout_rub"))
        top.append(
            {
                "telegram_id": player_id,
                "username": mapping.get("username") or mapping.get("first_name"),
                "rounds": int(mapping.get("rounds") or mapping.get("games_count") or 0),
                "handle_rub": handle_p,
                "payout_rub": payout_p,
                "net_rub": round(payout_p - handle_p, 2),
            }
        )
    if period_player_ids is None:
        active_ids = {int(row["telegram_id"]) for row in top}
    else:
        active_ids = {int(pid) for pid in period_player_ids if pid}
    first_day = {}
    for row in first_seen_rows or []:
        mapping = dict(row)
        pid = int(mapping.get("player_id") or 0)
        day = mapping.get("first_day")
        if pid and day is not None:
            first_day[pid] = day.isoformat() if hasattr(day, "isoformat") else str(day)
    if d_from and d_to:
        new_count = sum(
            1
            for pid in active_ids
            if first_day.get(pid) and d_from.isoformat() <= first_day[pid] <= d_to.isoformat()
        )
    else:
        new_count = len(active_ids)
    out["players"] = {
        "active": len(active_ids),
        "new": new_count,
        "avg_handle_rub": round(handle / len(active_ids), 2) if active_ids else None,
        "top": top,
    }

    cashier = dict(cashier_row or {})
    out["cashier"] = {
        "deposited_rub": _f(cashier.get("deposited_rub")),
        "deposit_count": int(cashier.get("deposit_count") or 0),
        "withdrawn_rub": _f(cashier.get("withdrawn_rub")),
        "pending_withdraw_rub": _f(cashier.get("pending_withdraw_rub")),
    }
    bank = dict(bankroll_row or {})
    balance = _f(bank.get("balance_rub"))
    reserved = _f(bank.get("reserved_rub"))
    out["bankroll"] = {
        "balance_rub": balance,
        "reserved_rub": reserved,
        "available_rub": round(balance - reserved, 2),
    }
    out["top_clans"] = list(top_clans or [])
    out["distributions"] = {
        "referrals": clip_share_table(referral_rows, total_rub=referral),
        "creators": clip_share_table(creator_rows, total_rub=creator),
        "cashback": clip_share_table(cashback_rows, total_rub=cashback),
        "bonuses": clip_share_table(bonus_rows, total_rub=bonus),
    }
    return out


def dashboard_from_stats(lifetime: dict, today: dict) -> dict:
    games_by_type = {
        str(row["game_type"]): int(row["rounds"])
        for row in lifetime.get("by_type") or []
        if int(row.get("rounds") or 0) > 0
    }
    top_players = [
        {
            "telegram_id": row["telegram_id"],
            "username": row.get("username"),
            "games_count": row.get("rounds") or 0,
            "total_bet": row.get("handle_rub") or 0,
        }
        for row in (lifetime.get("players") or {}).get("top") or []
    ]
    owner = lifetime.get("owner") or {}
    volume = lifetime.get("volume") or {}
    today_volume = today.get("volume") or {}
    return {
        "total_games": int(volume.get("rounds") or 0),
        "total_turnover_rub": float(volume.get("handle_rub") or 0),
        "total_commission_rub": float(volume.get("rake_rub") or 0),
        "owner_profit_rub": float(owner.get("owner_profit_rub") or 0),
        "commission_profit_rub": float(owner.get("commission_profit_rub") or 0),
        "house_game_profit_rub": float(owner.get("house_game_profit_rub") or 0),
        "active_players_count": int((lifetime.get("players") or {}).get("active") or 0),
        "games_today": int(today_volume.get("rounds") or 0),
        "turnover_today_rub": float(today_volume.get("handle_rub") or 0),
        "commission_today_rub": float(today_volume.get("rake_rub") or 0),
        "games_by_type": games_by_type,
        "top_players": top_players,
        "top_clans": list(lifetime.get("top_clans") or []),
    }


def chart_from_stats(stats: dict) -> list[dict]:
    points = []
    for row in stats.get("daily") or []:
        points.append(
            {
                "date": row["date"],
                "games_count": int(row.get("rounds") or 0),
                "turnover_rub": float(row.get("handle_rub") or 0),
                "commission_rub": float(row.get("rake_rub") or 0),
                "owner_profit_rub": float(row.get("owner_profit_rub") or 0),
                "ggr_rub": float(row.get("ggr_rub") or 0),
                "commission_profit_rub": 0.0,
                "house_game_profit_rub": float(row.get("ggr_rub") or 0),
            }
        )
    return points


async def _optional_fetchrow(conn, sql: str, *args):
    try:
        return await conn.fetchrow(sql, *args)
    except Exception:
        return None


async def _optional_fetch(conn, sql: str, *args):
    try:
        return await conn.fetch(sql, *args)
    except Exception:
        return []


async def fetch_casino_stats(conn, d_from: date | None = None, d_to: date | None = None) -> dict:
    """Period-aware casino stats. None, None = all time."""
    dated = d_from is not None and d_to is not None
    if dated and (d_from is None or d_to is None or d_from > d_to):
        return empty_casino_stats(d_from=d_from, d_to=d_to)

    round_rows = await conn.fetch(_ROUNDS_SQL, d_from, d_to)
    player_rows = await conn.fetch(_TOP_PLAYERS_SQL, d_from, d_to)
    period_id_rows = await conn.fetch(
        f"SELECT DISTINCT player_id FROM ({_PLAYER_EVENTS_SQL}) e",
        d_from,
        d_to,
    )
    first_seen_rows = await conn.fetch(_FIRST_SEEN_SQL)
    costs_row = await _optional_fetchrow(conn, _COSTS_SQL, d_from, d_to)
    referral_rows = await _optional_fetch(conn, _REFERRAL_DIST_SQL, d_from, d_to)
    creator_rows = await _optional_fetch(conn, _CREATOR_DIST_SQL, d_from, d_to)
    cashback_rows = await _optional_fetch(conn, _CASHBACK_DIST_SQL, d_from, d_to)
    bonus_rows = await _optional_fetch(conn, _BONUS_DIST_SQL, d_from, d_to)
    cashier_row = await _optional_fetchrow(conn, _CASHIER_SQL, d_from, d_to)
    bankroll_row = await _optional_fetchrow(
        conn,
        """
        SELECT balance_rub, reserved_rub
        FROM casino_house_accounts
        WHERE account_key = 'main'
        LIMIT 1
        """,
    )
    owner = await fetch_casino_owner_profit(conn, d_from, d_to) if dated else await fetch_casino_owner_profit(conn)
    owner_daily: dict[str, float] = {}
    if dated:
        owner_daily = await fetch_casino_owner_profit_daily(conn, d_from, d_to)
    try:
        clan_top = await clans_list_top(conn, limit=10)
        top_clans = list(clan_top.get("clans") or [])
    except Exception:
        top_clans = []
    return assemble_casino_stats(
        round_rows=list(round_rows or []),
        player_rows=list(player_rows or []),
        first_seen_rows=list(first_seen_rows or []),
        costs_row=costs_row,
        referral_rows=list(referral_rows or []),
        creator_rows=list(creator_rows or []),
        cashback_rows=list(cashback_rows or []),
        bonus_rows=list(bonus_rows or []),
        cashier_row=cashier_row,
        bankroll_row=bankroll_row,
        owner=owner,
        owner_daily=owner_daily,
        top_clans=top_clans,
        period_player_ids=[int(row["player_id"]) for row in period_id_rows or [] if row["player_id"]],
        d_from=d_from,
        d_to=d_to,
    )
