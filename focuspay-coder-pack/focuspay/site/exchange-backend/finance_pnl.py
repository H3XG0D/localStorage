"""Расчёт P&L и waterfall для админки."""
from __future__ import annotations

from datetime import date

from collections import defaultdict

import asyncpg

from db import get_pool
from runtime_settings import admin_weekly_salary_rub
from payroll_base import (
    fetch_accruals_for_orders,
    order_completed_in_shift,
    order_payroll_base_rub,
)
from economics_snapshot import order_economics
from operator_balance_fiat import market_prices_rub
from operator_usdt_issuance import usdt_issued_total_for_period
from external_exchange_stats import fetch_period_summary
from payout_requisite_stats import (
    card_fee_auto_pct,
    fetch_requisite_cost,
    fetch_requisite_pool_stats,
)


def _margin(net: float, fiat: float) -> float:
    return round(net / fiat * 100, 2) if fiat > 0 else 0.0


def _requisite_label(pool: dict) -> str:
    turnover = float(pool.get("turnover_rub") or 0)
    if turnover <= 0:
        return "Реквизитный пул"
    avg = float(pool.get("avg_cost_pct") or 0)
    return f"Реквизитный пул ({turnover:,.0f} ₽ под {avg:+.2f}%)".replace(",", " ")




def empty_casino_owner_profit() -> dict:
    return {
        "commission_profit_rub": 0.0,
        "house_game_profit_rub": 0.0,
        "owner_profit_rub": 0.0,
    }


def _casino_dated(column: str, dated: bool) -> str:
    if not dated:
        return ""
    return f"AND {column}::date BETWEEN $1 AND $2"


# House P&L of one settled room: rake + bot-won payout − consumed bot stakes.
_ROOM_HOUSE_DELTA_SQL = """
(
    r.rake_rub
    + CASE WHEN EXISTS (
        SELECT 1 FROM casino_fixed_room_seats s
        WHERE s.room_pk = r.id
          AND s.participant_kind = 'bot'
          AND -(s.seat_no + 1) = r.winner_id
      ) THEN r.payout_rub ELSE 0 END
    - r.stake_rub * (
        SELECT COUNT(*) FROM casino_fixed_room_seats s2
        WHERE s2.room_pk = r.id AND s2.participant_kind = 'bot'
    )
)
"""


def _casino_owner_profit_sql(*, dated: bool) -> str:
    """Owner casino P&L: legacy ledgers + v2/jackpot/rooms, without double-count."""
    d_created = _casino_dated("created_at", dated)
    d_v2s = _casino_dated("s.created_at", dated)
    d_jp = _casino_dated("settled_at", dated)
    d_room = _casino_dated("r.settled_at", dated)
    return f"""
        SELECT
            COALESCE((
                SELECT SUM(amount_rub) FROM casino_commission_ledger
                WHERE recipient_type = 'owner'
                  {d_created}
            ), 0) AS commission_profit,
            COALESCE((
                SELECT SUM(amount_rub) FROM casino_house_ledger
                WHERE entry_type = 'game_settlement'
                  {d_created}
            ), 0)
            + COALESCE((
                SELECT SUM(amount_rub) FROM casino_v2_house_ledger
                WHERE entry_type = 'game_settlement'
                  {d_created}
            ), 0)
            + COALESCE((
                SELECT SUM(s.commission_rub) FROM casino_v2_settlements s
                WHERE NOT EXISTS (
                    SELECT 1 FROM casino_v2_house_ledger h WHERE h.table_id = s.table_id
                )
                  {d_v2s}
            ), 0)
            + COALESCE((
                SELECT SUM(rake_rub) FROM casino_jackpot_rounds
                WHERE status = 'settled'
                  AND NOT EXISTS (
                    SELECT 1 FROM casino_house_ledger h
                    WHERE h.entry_key = 'jackpot-rake-' || round_id
                  )
                  {d_jp}
            ), 0)
            + COALESCE((
                SELECT SUM({_ROOM_HOUSE_DELTA_SQL})
                FROM casino_fixed_room_rounds r
                WHERE r.status = 'settled'
                  AND NOT EXISTS (
                    SELECT 1 FROM casino_house_ledger h
                    WHERE h.entry_key = 'room-rake-' || r.room_id
                  )
                  {d_room}
            ), 0) AS house_game_profit
    """


def _pack_casino_owner_profit(row) -> dict:
    if not row:
        return empty_casino_owner_profit()
    commission = float(row["commission_profit"] or 0)
    house = float(row["house_game_profit"] or 0)
    return {
        "commission_profit_rub": round(commission, 2),
        "house_game_profit_rub": round(house, 2),
        "owner_profit_rub": round(commission + house, 2),
    }


async def fetch_casino_owner_profit(conn, d_from: date | None = None, d_to: date | None = None) -> dict:
    """Owner casino P&L: commission + house game settlements of live games.

    Same formula as CasinoDashboard owner_profit_rub. Funding/adjustment are
    capital, not profit. V2 bot tables are in casino_v2_house_ledger (rake is
    already inside player_stakes − player_payouts); all-human v2 rake is either
    that ledger or historical commission with no ledger row. Jackpot/rooms use
    casino_house_ledger when present, else the round tables.
    """
    dated = d_from is not None and d_to is not None
    sql = _casino_owner_profit_sql(dated=dated)
    row = await conn.fetchrow(sql, d_from, d_to) if dated else await conn.fetchrow(sql)
    return _pack_casino_owner_profit(row)


async def fetch_focus_lucky_prize_cost(conn, d_from: date, d_to: date) -> float:
    """Paid FocusLucky prizes for the period. 0 if raffle_winners is absent."""
    try:
        exists = await conn.fetchval("SELECT to_regclass('public.raffle_winners')")
        if not exists:
            return 0.0
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(prize_rub), 0)
            FROM raffle_winners
            WHERE status = 'paid'
              AND paid_at::date BETWEEN $1 AND $2
            """,
            d_from,
            d_to,
        )
        return float(val or 0)
    except Exception:
        return 0.0


def empty_tournament_owner_profit() -> dict:
    return {
        "fees_rub": 0.0,
        "entry_fees_rub": 0.0,
        "rebuy_fees_rub": 0.0,
        "prizes_rub": 0.0,
        "refunds_rub": 0.0,
        "owner_profit_rub": 0.0,
    }


async def fetch_tournament_owner_profit(conn, d_from: date, d_to: date) -> dict:
    """Tournament owner P&L for the period: buy-ins + rebuys − prizes − refunds.

    Rebuy and entry fees reduce the net cost of prize payouts — that is the whole
    point of charging for a rebuy stack.
    """
    try:
        exists = await conn.fetchval("SELECT to_regclass('public.casino_tournament_cash_events')")
        if not exists:
            return empty_tournament_owner_profit()
        row = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(amount_rub) FILTER (WHERE kind = 'entry'), 0)::float AS entry_fees,
                COALESCE(SUM(amount_rub) FILTER (WHERE kind = 'rebuy'), 0)::float AS rebuy_fees,
                COALESCE(SUM(amount_rub) FILTER (WHERE kind = 'prize'), 0)::float AS prizes,
                COALESCE(SUM(amount_rub) FILTER (WHERE kind = 'refund'), 0)::float AS refunds
            FROM casino_tournament_cash_events
            WHERE created_at::date BETWEEN $1 AND $2
            """,
            d_from,
            d_to,
        )
    except Exception:
        return empty_tournament_owner_profit()
    if not row:
        return empty_tournament_owner_profit()
    entry_fees = round(float(row["entry_fees"] or 0), 2)
    rebuy_fees = round(float(row["rebuy_fees"] or 0), 2)
    prizes = round(float(row["prizes"] or 0), 2)
    refunds = round(float(row["refunds"] or 0), 2)
    fees = round(entry_fees + rebuy_fees, 2)
    return {
        "fees_rub": fees,
        "entry_fees_rub": entry_fees,
        "rebuy_fees_rub": rebuy_fees,
        "prizes_rub": prizes,
        "refunds_rub": refunds,
        "owner_profit_rub": round(fees - prizes - refunds, 2),
    }


def _empty_vpn_revenue() -> dict:
    return {
        "purchases": 0,
        "revenue_rub": 0.0,
        "referral_rub": 0.0,
        "cashback_rub": 0.0,
        "owner_profit_rub": 0.0,
    }


async def _vpn_ledger_cost(conn, table: str, d_from: date, d_to: date) -> float:
    """VPN cashback or referral accrued in the period (order_id vpn:{purchase})."""
    if table not in ("user_cashback_ledger", "user_referral_ledger"):
        raise ValueError(f"unexpected ledger {table}")
    try:
        val = await conn.fetchval(
            f"""
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM {table}
            WHERE type = 'accrual'
              AND order_id LIKE 'vpn:%'
              AND created_at::date BETWEEN $1 AND $2
            """,
            d_from,
            d_to,
        )
    except asyncpg.UndefinedTableError:
        return 0.0
    return round(float(val or 0), 2)


async def fetch_vpn_revenue(conn, d_from: date, d_to: date) -> dict:
    """VPN subscriptions and extra-device seats paid from the unified balance (vpn_purchases, status paid).

    Revenue is recognised on paid_at: the hold became a spend and CP granted days.
    owner_profit_rub is that revenue minus VPN cashback and the referrer ladder
    accrued on the same purchases (order_id vpn:…).
    """
    try:
        row = await conn.fetchrow(
            """
            SELECT COUNT(*)::int AS purchases, COALESCE(SUM(price_rub), 0)::float AS revenue
            FROM vpn_purchases
            WHERE status = 'paid' AND kind IN ('paid', 'device')
              AND paid_at::date BETWEEN $1 AND $2
            """,
            d_from,
            d_to,
        )
    except asyncpg.UndefinedTableError:
        return _empty_vpn_revenue()
    if not row:
        return _empty_vpn_revenue()
    revenue = round(float(row["revenue"] or 0), 2)
    referral = await _vpn_ledger_cost(conn, "user_referral_ledger", d_from, d_to)
    cashback = await _vpn_ledger_cost(conn, "user_cashback_ledger", d_from, d_to)
    return {
        "purchases": int(row["purchases"] or 0),
        "revenue_rub": revenue,
        "referral_rub": referral,
        "cashback_rub": cashback,
        "owner_profit_rub": round(revenue - referral - cashback, 2),
    }


async def fetch_casino_owner_profit_daily(conn, d_from: date, d_to: date) -> dict[str, float]:
    """Date ISO → owner casino profit (same sources as fetch_casino_owner_profit)."""
    rows = await conn.fetch(
        f"""
        SELECT day, COALESCE(SUM(amount_rub), 0)::float AS profit
        FROM (
            SELECT created_at::date AS day, amount_rub
            FROM casino_commission_ledger
            WHERE recipient_type = 'owner'
              AND created_at::date BETWEEN $1 AND $2
            UNION ALL
            SELECT created_at::date, amount_rub
            FROM casino_house_ledger
            WHERE entry_type = 'game_settlement'
              AND created_at::date BETWEEN $1 AND $2
            UNION ALL
            SELECT created_at::date, amount_rub
            FROM casino_v2_house_ledger
            WHERE entry_type = 'game_settlement'
              AND created_at::date BETWEEN $1 AND $2
            UNION ALL
            SELECT s.created_at::date, s.commission_rub
            FROM casino_v2_settlements s
            WHERE NOT EXISTS (
                SELECT 1 FROM casino_v2_house_ledger h WHERE h.table_id = s.table_id
            )
              AND s.created_at::date BETWEEN $1 AND $2
            UNION ALL
            SELECT settled_at::date, rake_rub
            FROM casino_jackpot_rounds
            WHERE status = 'settled'
              AND settled_at IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM casino_house_ledger h
                WHERE h.entry_key = 'jackpot-rake-' || round_id
              )
              AND settled_at::date BETWEEN $1 AND $2
            UNION ALL
            SELECT r.settled_at::date, {_ROOM_HOUSE_DELTA_SQL}
            FROM casino_fixed_room_rounds r
            WHERE r.status = 'settled'
              AND r.settled_at IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM casino_house_ledger h
                WHERE h.entry_key = 'room-rake-' || r.room_id
              )
              AND r.settled_at::date BETWEEN $1 AND $2
        ) t
        GROUP BY day
        """,
        d_from,
        d_to,
    )
    out: dict[str, float] = {}
    for r in rows:
        day = r["day"]
        key = day.isoformat() if hasattr(day, "isoformat") else str(day)
        out[key] = round(float(r["profit"] or 0), 2)
    return out


def _admin_salary_for_period(d_from: date, d_to: date, weekly_rub: float) -> float:
    days = (d_to - d_from).days + 1
    return round(weekly_rub * days / 7.0, 2)


async def _capital_turnover(conn, d_from: date, fiat_volume: float) -> dict:
    """Рассчитать оборачиваемость по последнему подтверждённому снимку капитала."""
    # Найти ближайший capital snapshot до начала периода
    row = await conn.fetchrow(
        """
        SELECT amount, occurred_at
        FROM owner_finance_ledger
        WHERE entry_type = 'capital_snapshot'
          AND status = 'confirmed'
          AND occurred_at::date <= $1
        ORDER BY occurred_at DESC
        LIMIT 1
        """,
        d_from,
    )

    if not row:
        return {
            "available": False,
            "note": "No capital snapshot found before period start",
        }

    capital_rub = float(row["amount"])
    snapshot_date = row["occurred_at"]
    turnover = round(fiat_volume / capital_rub, 2) if capital_rub > 0 else 0.0

    return {
        "available": True,
        "capital_rub": capital_rub,
        "snapshot_date": snapshot_date.isoformat(),
        "fiat_volume": fiat_volume,
        "turnover": turnover,
        "note": f"Capital snapshot from {snapshot_date.date()}",
    }


async def compute_pnl(d_from: date, d_to: date) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        order_rows = await conn.fetch(
            """
            SELECT order_id, direction, merchant_order_id, fiat_amount, cashback_applied_rub,
                   card_fee_pct, economics_snapshot, crypto, crypto_amount, rate, operator_id, created_at
            FROM orders
            WHERE status IN ('PAID', 'COMPLETED')
              AND created_at::date BETWEEN $1 AND $2
            """,
            d_from,
            d_to,
        )

        manual_mandatory_cost = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)::float
                FROM manual_expenses
                WHERE category = 'mandatory'
                  AND expense_date BETWEEN $1 AND $2
                """,
                d_from,
                d_to,
            )
            or 0
        )
        manual_work_cost = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)::float
                FROM manual_expenses
                WHERE category = 'work'
                  AND expense_date BETWEEN $1 AND $2
                """,
                d_from,
                d_to,
            )
            or 0
        )
        manual_unexpected_cost = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)::float
                FROM manual_expenses
                WHERE category = 'unexpected'
                  AND expense_date BETWEEN $1 AND $2
                """,
                d_from,
                d_to,
            )
            or 0
        )
        manual_expenses_total = (
            manual_mandatory_cost + manual_work_cost + manual_unexpected_cost
        )

        cashback_cost = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)
                FROM user_cashback_ledger
                WHERE type = 'accrual' AND created_at::date BETWEEN $1 AND $2
                """,
                d_from,
                d_to,
            )
            or 0
        )
        referral_cost = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)
                FROM user_referral_ledger
                WHERE type = 'accrual' AND created_at::date BETWEEN $1 AND $2
                """,
                d_from,
                d_to,
            )
            or 0
        )
        partner_cost = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)
                FROM partner_ledger
                WHERE type = 'accrual' AND created_at::date BETWEEN $1 AND $2
                """,
                d_from,
                d_to,
            )
            or 0
        )
        review_bonus_cost = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)
                FROM review_bonus_claims
                WHERE created_at::date BETWEEN $1 AND $2
                """,
                d_from,
                d_to,
            )
            or 0
        )
        wallet_payout_cost = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)
                FROM operator_wallet_payouts
                WHERE created_at::date BETWEEN $1 AND $2
                  AND raffle_winner_id IS NULL
                """,
                d_from,
                d_to,
            )
            or 0
        )
        focus_lucky_cost = await fetch_focus_lucky_prize_cost(conn, d_from, d_to)
        exchange_discount_cost = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(exchange_discount_applied_rub), 0)
                FROM orders
                WHERE status IN ('PAID', 'COMPLETED')
                  AND exchange_discount_applied_rub > 0
                  AND created_at::date BETWEEN $1 AND $2
                """,
                d_from,
                d_to,
            )
            or 0
        )
        swap_commission_cost = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)
                FROM swap_commission_entries
                WHERE created_at::date BETWEEN $1 AND $2
                """,
                d_from,
                d_to,
            )
            or 0
        )

        operator_accounts = await conn.fetch(
            """
            SELECT id, display_name, percent FROM operator_accounts WHERE is_active
            """
        )
        daily_salary_total = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(daily_salary_rub), 0)::float
                FROM admin_salary_recipients
                WHERE is_active = TRUE
                """
            )
            or 0
        )
        operator_orders = await conn.fetch(
            """
            SELECT order_id, operator_id, direction, crypto, fiat_amount, crypto_amount, rate,
                   cashback_applied_rub, card_fee_pct, economics_snapshot,
                   created_at, payout_confirmed_at, updated_at
            FROM orders
            WHERE operator_id IS NOT NULL
              AND status IN ('PAID', 'COMPLETED')
              AND COALESCE(payroll_model, 'legacy') <> 'role_split'
              AND COALESCE(payout_confirmed_at, updated_at, created_at)::date
                  BETWEEN $1 AND $2
            """,
            d_from,
            d_to,
        )
        split_payroll_rows = await conn.fetch(
            """
            SELECT operator_id, COALESCE(SUM(amount_rub), 0)::float AS amount
            FROM operator_payroll_ledger
            WHERE type = 'accrual' AND payroll_split_line_id IS NOT NULL
              AND created_at::date BETWEEN $1 AND $2
              AND operator_id IS NOT NULL
            GROUP BY operator_id
            """,
            d_from,
            d_to,
        )
        split_payroll_by_id = {
            int(row["operator_id"]): float(row["amount"] or 0)
            for row in split_payroll_rows
        }
        hourly_payroll_rows = await conn.fetch(
            """
            SELECT l.operator_id,
                   oa.display_name,
                   oa.percent,
                   COALESCE(SUM(l.amount_rub), 0)::float AS amount
            FROM operator_payroll_ledger l
            LEFT JOIN operator_accounts oa ON oa.id = l.operator_id
            WHERE l.type = 'hourly'
              AND l.created_at::date BETWEEN $1 AND $2
              AND l.operator_id IS NOT NULL
            GROUP BY l.operator_id, oa.display_name, oa.percent
            """,
            d_from,
            d_to,
        )
        hourly_by_id = {int(row["operator_id"]): row for row in hourly_payroll_rows}
        operator_shifts = await conn.fetch(
            """
            SELECT operator_id, started_at, ended_at FROM operator_shifts
            WHERE started_at::date <= $2
              AND (ended_at IS NULL OR ended_at::date >= $1)
            """,
            d_from,
            d_to,
        )

        order_ids = [str(r["order_id"]) for r in order_rows if r.get("order_id")]
        accruals = await fetch_accruals_for_orders(conn, order_ids)
        usdt_amount = await usdt_issued_total_for_period(conn, d_from, d_to)
        market = await market_prices_rub()
        usdt_rub_rate = float(market.get("usdt") or 0)
        external = await fetch_period_summary(
            conn, d_from, d_to, usdt_rub_rate=usdt_rub_rate
        )
        casino = await fetch_casino_owner_profit(conn, d_from, d_to)
        vpn = await fetch_vpn_revenue(conn, d_from, d_to)
        tournaments = await fetch_tournament_owner_profit(conn, d_from, d_to)
        requisite_cost = await fetch_requisite_cost(conn, d_from, d_to)
        requisite_pool = await fetch_requisite_pool_stats(
            conn, d_from, d_to, card_fee_pct=card_fee_auto_pct()
        )

    buckets: dict[str, dict] = {
        "auto_buy": {
            "orders": 0,
            "fiat_volume": 0.0,
            "spread_revenue": 0.0,
            "card_fee_cost": 0.0,
            "net_profit": 0.0,
        },
        "manual_buy": {
            "orders": 0,
            "fiat_volume": 0.0,
            "spread_revenue": 0.0,
            "card_fee_cost": 0.0,
            "net_profit": 0.0,
        },
        "sell": {
            "orders": 0,
            "fiat_volume": 0.0,
            "spread_revenue": 0.0,
            "card_fee_cost": 0.0,
            "net_profit": 0.0,
        },
    }

    total_spread = 0.0
    total_card_fee = 0.0

    for r in order_rows:
        fiat = float(r["fiat_amount"] or 0)
        direction = (r["direction"] or "").lower()
        economics = order_economics(dict(r), clamp=False)
        profit = economics["service_profit_rub"]
        spread = economics["gross_margin_rub"]
        card_cost = economics["merchant_fee_rub"]

        if direction == "buy":
            key = "auto_buy" if r["merchant_order_id"] else "manual_buy"
        else:
            key = "sell"

        buckets[key]["orders"] += 1
        buckets[key]["fiat_volume"] += fiat
        buckets[key]["spread_revenue"] += spread
        buckets[key]["card_fee_cost"] += card_cost
        buckets[key]["net_profit"] += profit
        total_spread += spread
        total_card_fee += card_cost

    total_fiat = sum(b["fiat_volume"] for b in buckets.values())
    external_profit_rub = float(external.get("house_profit_rub") or 0)
    external_turnover_rub = float(external.get("turnover_base_rub") or 0)
    casino_profit_rub = float((casino or empty_casino_owner_profit()).get("owner_profit_rub") or 0)
    total_fiat_with_external = total_fiat + external_turnover_rub
    vpn_revenue_rub = float(vpn["revenue_rub"])
    tournament_fees_rub = float((tournaments or empty_tournament_owner_profit()).get("fees_rub") or 0)
    tournament_prizes_rub = float((tournaments or empty_tournament_owner_profit()).get("prizes_rub") or 0)
    tournament_refunds_rub = float((tournaments or empty_tournament_owner_profit()).get("refunds_rub") or 0)
    tournament_cost_rub = round(tournament_prizes_rub + tournament_refunds_rub, 2)
    tournament_profit_rub = float(
        (tournaments or empty_tournament_owner_profit()).get("owner_profit_rub") or 0
    )
    total_net = (
        sum(b["net_profit"] for b in buckets.values())
        + external_profit_rub
        + casino_profit_rub
        + vpn_revenue_rub
        + tournament_profit_rub
    )
    # Скидка на обмен НЕ вычитается отдельно: она уже снизила сумму к оплате
    # (payin) и, значит, уже сидит в спреде/чистой марже сделки (total_net).
    # exchange_discount_cost оставляем только как справочную цифру в costs.
    accrual_total = (
        cashback_cost
        + referral_cost
        + partner_cost
        + review_bonus_cost
        + wallet_payout_cost
        + focus_lucky_cost
        + swap_commission_cost
        + requisite_cost
    )
    profit_after_costs = total_net - accrual_total

    payroll_pool = 0.0
    for r in order_rows:
        payroll_pool += order_payroll_base_rub(dict(r), accruals)

    op_base_by_id: dict[int, float] = defaultdict(float)
    for r in operator_orders:
        o = dict(r)
        op_id = int(o["operator_id"])
        for s in operator_shifts:
            if int(s["operator_id"]) == op_id and order_completed_in_shift(
                o, s["started_at"], s["ended_at"]
            ):
                op_base_by_id[op_id] += order_payroll_base_rub(o, accruals)
                break

    by_type = []
    for key, b in buckets.items():
        by_type.append(
            {
                "type": key,
                "orders": b["orders"],
                "fiat_volume": round(b["fiat_volume"], 2),
                "spread_revenue": round(b["spread_revenue"], 2),
                "card_fee_cost": round(b["card_fee_cost"], 2),
                "net_profit": round(b["net_profit"], 2),
                "margin_pct": _margin(b["net_profit"], b["fiat_volume"]),
            }
        )

    by_type.append(
        {
            "type": "external",
            "orders": int(external.get("deal_count") or 0) + int(external.get("payout_count") or 0),
            "fiat_volume": round(external_turnover_rub, 2),
            "spread_revenue": 0.0,
            "card_fee_cost": 0.0,
            "net_profit": round(external_profit_rub, 2),
            "margin_pct": _margin(external_profit_rub, external_turnover_rub),
        }
    )
    by_type.append(
        {
            "type": "casino",
            "orders": 0,
            "fiat_volume": 0.0,
            "spread_revenue": 0.0,
            "card_fee_cost": 0.0,
            "net_profit": round(casino_profit_rub, 2),
            "margin_pct": 0.0,
        }
    )
    by_type.append(
        {
            "type": "vpn",
            "orders": int(vpn["purchases"]),
            "fiat_volume": 0.0,
            "spread_revenue": 0.0,
            "card_fee_cost": 0.0,
            "net_profit": round(vpn_revenue_rub, 2),
            "margin_pct": 0.0,
        }
    )

    from runtime_settings import get_settings_sync

    rs = get_settings_sync()
    auto_spread = int(float(rs["buy_spread_auto_pct"]))
    manual_spread = int(float(rs["buy_spread_manual_pct"]))
    card_auto = int(float(rs["card_fee_auto_pct"]))
    card_manual = int(float(rs["card_fee_manual_pct"]))

    waterfall = [
        {
            "key": "fiat_volume",
            "label": "Оборот (оплаченные сделки)",
            "amount": round(total_fiat, 2),
            "kind": "neutral",
        },
        {
            "key": "spread_revenue",
            "label": f"Спред в цене (авто {auto_spread}% / ручные {manual_spread}% с BUY)",
            "amount": round(total_spread, 2),
            "kind": "income",
        },
        {
            "key": "card_fee",
            "label": f"Провайдер карт ({card_auto}% / {card_manual}%)",
            "amount": round(-total_card_fee, 2),
            "kind": "expense",
        },
        {
            "key": "service_profit",
            "label": "Прибыль сервиса (до начислений)",
            "amount": round(
                total_net
                - external_profit_rub
                - casino_profit_rub
                - vpn_revenue_rub
                - tournament_profit_rub,
                2,
            ),
            "kind": "subtotal",
        },
    ]
    has_external = external_profit_rub != 0 or int(external.get("deal_count") or 0) > 0
    has_casino = abs(casino_profit_rub) > 0.009
    has_vpn = vpn_revenue_rub > 0.009
    has_tournaments = abs(tournament_fees_rub) > 0.009 or abs(tournament_cost_rub) > 0.009
    if has_external:
        ext_usd = float(external.get("house_profit_usd") or 0)
        ext_label = (
            f"Внештат обмены ({int(external.get('deal_count') or 0)} сд."
            f" · ${ext_usd:,.2f})".replace(",", " ")
        )
        waterfall.append(
            {
                "key": "external_profit",
                "label": ext_label,
                "amount": round(external_profit_rub, 2),
                "kind": "income",
            }
        )
    waterfall.append(
        {
            "key": "casino_profit",
            "label": "Казино: комиссия + дом",
            "amount": round(casino_profit_rub, 2),
            "kind": "income",
        }
    )
    if has_vpn:
        waterfall.append(
            {
                "key": "vpn_revenue",
                "label": f"VPN: продажи с баланса ({int(vpn['purchases'])} шт.)",
                "amount": round(vpn_revenue_rub, 2),
                "kind": "income",
            }
        )
    if has_tournaments:
        rebuy = float((tournaments or empty_tournament_owner_profit()).get("rebuy_fees_rub") or 0)
        fee_label = "Турниры: взносы и докупки"
        if rebuy > 0.009:
            fee_label = f"Турниры: взносы и докупки (докупки {rebuy:,.0f} ₽)".replace(",", " ")
        waterfall.append(
            {
                "key": "tournament_fees",
                "label": fee_label,
                "amount": round(tournament_fees_rub, 2),
                "kind": "income",
            }
        )
        if tournament_cost_rub > 0.009:
            waterfall.append(
                {
                    "key": "tournament_prizes",
                    "label": "Турниры: призы и возвраты",
                    "amount": round(-tournament_cost_rub, 2),
                    "kind": "expense",
                }
            )
    if has_external or has_casino or has_vpn or has_tournaments:
        extras = []
        if has_external:
            extras.append("внештат")
        if has_casino:
            extras.append("казино")
        if has_vpn:
            extras.append("VPN")
        if has_tournaments:
            extras.append("турниры")
        waterfall.append(
            {
                "key": "service_profit_total",
                "label": "Прибыль сервиса + " + " + ".join(extras),
                "amount": round(total_net, 2),
                "kind": "subtotal",
            }
        )
    waterfall.extend(
        [
        {
            "key": "cashback",
            "label": "Кешбэк пользователям",
            "amount": round(-cashback_cost, 2),
            "kind": "expense",
        },
        {
            # Информационно: скидка уже снижает спред/маржу сделки, отдельно
            # из суммы НЕ вычитается (иначе двойной учёт). kind=neutral.
            "key": "exchange_discount",
            "label": "Скидки на обмен (уже в марже)",
            "amount": round(exchange_discount_cost, 2),
            "kind": "neutral",
        },
        {
            "key": "referral",
            "label": "Реферальные",
            "amount": round(-referral_cost, 2),
            "kind": "expense",
        },
        {
            "key": "partner",
            "label": "Партнёрские",
            "amount": round(-partner_cost, 2),
            "kind": "expense",
        },
        {
            "key": "review_bonus",
            "label": "Бонусы за отзывы (50/100 ₽)",
            "amount": round(-review_bonus_cost, 2),
            "kind": "expense",
        },
        {
            "key": "wallet_payout",
            "label": "Выплаты на кошельки",
            "amount": round(-wallet_payout_cost, 2),
            "kind": "expense",
        },
        {
            "key": "focus_lucky",
            "label": "FocusLucky",
            "amount": round(-focus_lucky_cost, 2),
            "kind": "expense",
        },
        {
            "key": "swap_commission",
            "label": "Комиссии со свапов",
            "amount": round(-swap_commission_cost, 2),
            "kind": "expense",
        },
        {
            "key": "payout_requisites",
            "label": _requisite_label(requisite_pool),
            "amount": round(-requisite_cost, 2),
            "kind": "income" if requisite_cost < 0 else "expense",
        },
        {
            "key": "profit_after_accruals",
            "label": "Прибыль после начислений (вкл. партнёров)",
            "amount": round(profit_after_costs, 2),
            "kind": "subtotal",
        },
        {
            "key": "payroll_base",
            "label": "База зарплат (после кешбэка и реф.)",
            "amount": round(payroll_pool, 2),
            "kind": "subtotal",
        },
        ]
    )

    # 1) Операторы: % от базы по сделкам, подтверждённым в смене (payout_confirmed_at)
    operator_payroll_items = []
    operator_payroll_total = 0.0
    for op_row in operator_accounts:
        pct = float(op_row["percent"] or 0)
        base = float(op_base_by_id.get(op_row["id"], 0))
        legacy_amount = round(base * pct / 100.0, 2) if base > 0 else 0.0
        split_amount = round(split_payroll_by_id.get(int(op_row["id"]), 0), 2)
        hourly_row = hourly_by_id.pop(int(op_row["id"]), None)
        hourly_amount = round(float((hourly_row or {}).get("amount") or 0), 2)
        amount = round(legacy_amount + split_amount + hourly_amount, 2)
        name = op_row["display_name"] or f"Оператор #{op_row['id']}"
        operator_payroll_items.append(
            {
                "id": op_row["id"],
                "name": name,
                "percent": pct,
                "base": round(base, 2),
                "legacy_amount": legacy_amount,
                "role_split_amount": split_amount,
                "hourly_amount": hourly_amount,
                "amount": amount,
            }
        )
        operator_payroll_total += amount
        label = f"Оператор: {name} ({pct:g}%)"
        if hourly_amount:
            label = f"{label} + часы"
        waterfall.append(
            {
                "key": f"operator_{op_row['id']}",
                "label": label,
                "amount": round(-amount, 2),
                "kind": "expense",
            }
        )

    for oid, hourly_row in hourly_by_id.items():
        hourly_amount = round(float(hourly_row["amount"] or 0), 2)
        if hourly_amount == 0:
            continue
        name = hourly_row["display_name"] or f"Оператор #{oid}"
        operator_payroll_items.append(
            {
                "id": oid,
                "name": name,
                "percent": float(hourly_row["percent"] or 0),
                "base": 0.0,
                "legacy_amount": 0.0,
                "role_split_amount": 0.0,
                "hourly_amount": hourly_amount,
                "amount": hourly_amount,
            }
        )
        operator_payroll_total += hourly_amount
        waterfall.append(
            {
                "key": f"operator_{oid}",
                "label": f"Оператор: {name} (часы)",
                "amount": round(-hourly_amount, 2),
                "kind": "expense",
            }
        )

    # 2) Админ: фиксированная зарплата за период (₽/день × дни × получатели)
    weekly_salary = admin_weekly_salary_rub()
    if daily_salary_total > 0:
        daily_rate = daily_salary_total
        weekly_salary = daily_rate * 7
    else:
        daily_rate = weekly_salary / 7.0
    admin_salary = _admin_salary_for_period(d_from, d_to, weekly_salary)
    salary_label_rate = daily_rate if daily_salary_total > 0 else weekly_salary
    salary_label = (
        f"Зарплата админа ({salary_label_rate:,.0f} ₽/день)".replace(",", " ")
        if daily_salary_total > 0
        else f"Зарплата админа ({weekly_salary:,.0f} ₽/нед)".replace(",", " ")
    )
    waterfall.append(
        {
            "key": "admin_salary",
            "label": salary_label,
            "amount": round(-admin_salary, 2),
            "kind": "expense",
        },
    )

    usdt_cost_rub = round(usdt_amount * usdt_rub_rate, 2) if usdt_amount > 0 else 0.0
    if usdt_cost_rub > 0:
        usdt_label = f"USDT операторам ({usdt_amount:g} USDT)"
        waterfall.append(
            {
                "key": "usdt_issued",
                "label": usdt_label,
                "amount": round(-usdt_cost_rub, 2),
                "kind": "expense",
            },
        )

    owner_residual = round(
        profit_after_costs
        - operator_payroll_total
        - admin_salary
        - usdt_cost_rub
        - manual_expenses_total,
        2,
    )

    if manual_mandatory_cost > 0.009:
        waterfall.append(
            {
                "key": "manual_expense_mandatory",
                "label": "Обязательные расходы",
                "amount": round(-manual_mandatory_cost, 2),
                "kind": "expense",
            }
        )
    if manual_work_cost > 0.009:
        waterfall.append(
            {
                "key": "manual_expense_work",
                "label": "Рабочие расходы",
                "amount": round(-manual_work_cost, 2),
                "kind": "expense",
            }
        )
    if manual_unexpected_cost > 0.009:
        waterfall.append(
            {
                "key": "manual_expense_unexpected",
                "label": "Непредвиденные расходы",
                "amount": round(-manual_unexpected_cost, 2),
                "kind": "expense",
            }
        )

    waterfall.append(
        {
            "key": "owner_residual",
            "label": "Финальный остаток",
            "amount": owner_residual,
            "kind": "total",
        }
    )

    # Capital turnover. Берём новое соединение: основное было освобождено после
    # загрузки исходных данных, а итоговый оборот известен только после агрегации.
    async with pool.acquire() as conn:
        capital_turnover = await _capital_turnover(conn, d_from, total_fiat_with_external)

    return {
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "by_type": by_type,
        "waterfall": waterfall,
        "manual_expenses": {
            "mandatory": round(manual_mandatory_cost, 2),
            "work": round(manual_work_cost, 2),
            "unexpected": round(manual_unexpected_cost, 2),
            "total": round(manual_expenses_total, 2),
        },
        "costs": {
            "cashback": round(cashback_cost, 2),
            "exchange_discount": round(exchange_discount_cost, 2),
            "referral": round(referral_cost, 2),
            "partner": round(partner_cost, 2),
            "review_bonus": round(review_bonus_cost, 2),
            "wallet_payout": round(wallet_payout_cost, 2),
            "focus_lucky": round(focus_lucky_cost, 2),
            "tournament_fees": round(tournament_fees_rub, 2),
            "tournament_prizes": round(tournament_cost_rub, 2),
            "tournament_net": round(tournament_profit_rub, 2),
            "swap_commission": round(swap_commission_cost, 2),
            "payout_requisites": round(requisite_cost, 2),
            "usdt_issued_usdt": round(usdt_amount, 8),
            "usdt_issued_rub": round(usdt_cost_rub, 2),
            "total": round(accrual_total, 2),
        },
        "payroll": {
            "base": round(payroll_pool, 2),
            "admin_weekly_salary_rub": round(weekly_salary, 2),
            "admin_daily_salary_rub": round(daily_rate, 2),
            "admin_salary": round(admin_salary, 2),
            "total": round(admin_salary, 2),
            "operators": operator_payroll_items,
            "operators_total": round(operator_payroll_total, 2),
            "owner_residual": owner_residual,
        },
        "total": {
            "fiat_volume": round(total_fiat, 2),
            "fiat_volume_with_external": round(total_fiat_with_external, 2),
            "spread_revenue": round(total_spread, 2),
            "card_fee_cost": round(total_card_fee, 2),
            "net_profit": round(total_net, 2),
            "profit_after_costs": round(profit_after_costs, 2),
            "net_margin_pct": _margin(total_net, total_fiat),
            "margin_after_costs_pct": _margin(profit_after_costs, total_fiat),
            "owner_margin_pct": _margin(owner_residual, total_fiat_with_external),
        },
        "external": external,
        "casino": casino or empty_casino_owner_profit(),
        "vpn": vpn,
        "tournaments": tournaments or empty_tournament_owner_profit(),
        "payout_requisites": requisite_pool,
        "capital_turnover": capital_turnover,
    }
