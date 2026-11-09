"""Дневная разбивка расходов для графика Dashboard."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta

logger = logging.getLogger("stats_daily_costs")

from payroll_base import (
    fetch_accruals_for_orders,
    order_completed_in_shift,
    order_payroll_base_rub,
)
from runtime_settings import admin_weekly_salary_rub
from economics_snapshot import order_economics
from payout_requisite_stats import fetch_requisite_cost_daily


def _empty_cost_day() -> dict:
    return {
        "cost_cashback": 0.0,
        "cost_referral": 0.0,
        "cost_partner": 0.0,
        "cost_review": 0.0,
        "cost_wallet_payout": 0.0,
        "cost_focus_lucky": 0.0,
        "cost_card": 0.0,
        "cost_payroll": 0.0,
        "cost_admin": 0.0,
        "cost_swap": 0.0,
        "cost_usdt": 0.0,
        "cost_manual": 0.0,
        "cost_payout_requisites": 0.0,
        "cost_total": 0.0,
    }


def _recalc_total(d: dict) -> None:
    d["cost_total"] = round(
        d["cost_cashback"]
        + d["cost_referral"]
        + d["cost_partner"]
        + d["cost_review"]
        + d["cost_wallet_payout"]
        + d.get("cost_focus_lucky", 0.0)
        + d["cost_card"]
        + d["cost_payroll"]
        + d["cost_admin"]
        + d["cost_swap"]
        + d["cost_usdt"]
        + d.get("cost_manual", 0.0)
        + d.get("cost_payout_requisites", 0.0),
        2,
    )


def daily_cost_overhead(costs: dict) -> float:
    """Расходы дня поверх маржи по сделкам (комиссия карт уже в profit)."""
    return round(
        float(costs.get("cost_cashback", 0) or 0)
        + float(costs.get("cost_referral", 0) or 0)
        + float(costs.get("cost_partner", 0) or 0)
        + float(costs.get("cost_review", 0) or 0)
        + float(costs.get("cost_wallet_payout", 0) or 0)
        + float(costs.get("cost_focus_lucky", 0) or 0)
        + float(costs.get("cost_swap", 0) or 0)
        + float(costs.get("cost_payroll", 0) or 0)
        + float(costs.get("cost_admin", 0) or 0)
        + float(costs.get("cost_usdt", 0) or 0)
        + float(costs.get("cost_manual", 0) or 0)
        + float(costs.get("cost_payout_requisites", 0) or 0),
        2,
    )


def _admin_salary_for_period(d_from: date, d_to: date, weekly_rub: float) -> float:
    days = (d_to - d_from).days + 1
    return round(weekly_rub * days / 7.0, 2)


async def fetch_daily_costs(
    conn,
    d_from: date,
    d_to: date,
    order_rows,
) -> dict[str, dict]:
    daily: dict[str, dict] = defaultdict(_empty_cost_day)

    ledger_queries = [
        (
            "cost_cashback",
            """
            SELECT created_at::date AS day, COALESCE(SUM(amount_rub), 0)::float AS amount
            FROM user_cashback_ledger
            WHERE type = 'accrual' AND created_at::date BETWEEN $1 AND $2
            GROUP BY 1
            """,
        ),
        (
            "cost_referral",
            """
            SELECT created_at::date AS day, COALESCE(SUM(amount_rub), 0)::float AS amount
            FROM user_referral_ledger
            WHERE type = 'accrual' AND created_at::date BETWEEN $1 AND $2
            GROUP BY 1
            """,
        ),
        (
            "cost_partner",
            """
            SELECT created_at::date AS day, COALESCE(SUM(amount_rub), 0)::float AS amount
            FROM partner_ledger
            WHERE type = 'accrual' AND created_at::date BETWEEN $1 AND $2
            GROUP BY 1
            """,
        ),
        (
            "cost_review",
            """
            SELECT created_at::date AS day, COALESCE(SUM(amount_rub), 0)::float AS amount
            FROM review_bonus_claims
            WHERE created_at::date BETWEEN $1 AND $2
            GROUP BY 1
            """,
        ),
        (
            "cost_wallet_payout",
            """
            SELECT created_at::date AS day, COALESCE(SUM(amount_rub), 0)::float AS amount
            FROM operator_wallet_payouts
            WHERE created_at::date BETWEEN $1 AND $2
              AND raffle_winner_id IS NULL
            GROUP BY 1
            """,
        ),
        (
            "cost_swap",
            """
            SELECT created_at::date AS day, COALESCE(SUM(amount_rub), 0)::float AS amount
            FROM swap_commission_entries
            WHERE created_at::date BETWEEN $1 AND $2
            GROUP BY 1
            """,
        ),
    ]

    for field, sql in ledger_queries:
        rows = await conn.fetch(sql, d_from, d_to)
        for r in rows:
            day = r["day"].isoformat()
            daily[day][field] += float(r["amount"] or 0)

    try:
        raffle_rows = await conn.fetch(
            """
            SELECT paid_at::date AS day, COALESCE(SUM(prize_rub), 0)::float AS amount
            FROM raffle_winners
            WHERE status = 'paid'
              AND paid_at::date BETWEEN $1 AND $2
            GROUP BY 1
            """,
            d_from,
            d_to,
        )
        for r in raffle_rows:
            day = r["day"].isoformat()
            daily[day]["cost_focus_lucky"] += float(r["amount"] or 0)
    except Exception:
        logger.debug("raffle_winners missing or unreadable", exc_info=True)

    for r in order_rows:
        if (r["direction"] or "").lower() != "buy":
            continue
        day = r["created_at"].date().isoformat()
        daily[day]["cost_card"] += order_economics(dict(r), clamp=False)["merchant_fee_rub"]

    operator_accounts = await conn.fetch(
        "SELECT id, percent FROM operator_accounts WHERE is_active"
    )
    op_pct = {int(r["id"]): float(r["percent"]) for r in operator_accounts}

    operator_orders = await conn.fetch(
        """
        SELECT order_id, operator_id, direction, crypto, fiat_amount, crypto_amount, rate,
               cashback_applied_rub, card_fee_pct, economics_snapshot,
               created_at, payout_confirmed_at, updated_at
        FROM orders
        WHERE operator_id IS NOT NULL
          AND status IN ('PAID', 'COMPLETED')
          AND COALESCE(payout_confirmed_at, updated_at, created_at)::date BETWEEN $1 AND $2
        """,
        d_from,
        d_to,
    )
    operator_shifts = await conn.fetch(
        """
        SELECT operator_id, started_at, ended_at FROM operator_shifts
        WHERE started_at::date <= $2
          AND (ended_at IS NULL OR ended_at::date >= $1)
        """,
        d_from,
        d_to,
    )

    order_ids = [str(r["order_id"]) for r in operator_orders if r.get("order_id")]
    accruals = await fetch_accruals_for_orders(conn, order_ids)

    for r in operator_orders:
        o = dict(r)
        op_id = int(o["operator_id"])
        pct = op_pct.get(op_id, 0.0)
        if pct <= 0:
            continue
        for s in operator_shifts:
            if int(s["operator_id"]) != op_id:
                continue
            if not order_completed_in_shift(o, s["started_at"], s["ended_at"]):
                continue
            comp = o.get("payout_confirmed_at") or o.get("updated_at") or o.get("created_at")
            day = comp.date().isoformat()
            base = order_payroll_base_rub(o, accruals)
            daily[day]["cost_payroll"] += base * pct / 100.0
            break

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
    weekly_salary = admin_weekly_salary_rub()
    if daily_salary_total > 0:
        admin_total = round(daily_salary_total * ((d_to - d_from).days + 1), 2)
    else:
        admin_total = _admin_salary_for_period(d_from, d_to, weekly_salary)

    num_days = (d_to - d_from).days + 1
    per_day_admin = admin_total / num_days if num_days > 0 else 0.0
    cur = d_from
    while cur <= d_to:
        daily[cur.isoformat()]["cost_admin"] = per_day_admin
        cur += timedelta(days=1)

    usdt_rows = await conn.fetch(
        """
        SELECT created_at::date AS day, COALESCE(SUM(amount_usdt), 0)::float AS usdt
        FROM operator_usdt_issuances
        WHERE created_at::date BETWEEN $1 AND $2
        GROUP BY 1
        """,
        d_from,
        d_to,
    )
    if usdt_rows:
        from operator_balance_fiat import market_prices_rub

        market = await market_prices_rub()
        usdt_rate = float(market.get("usdt") or 0)
        if usdt_rate > 0:
            for r in usdt_rows:
                day = r["day"].isoformat()
                daily[day]["cost_usdt"] += float(r["usdt"] or 0) * usdt_rate

    # Ручные расходы админки (обязательные / рабочие / непредвиденные)
    try:
        manual_rows = await conn.fetch(
            """
            SELECT expense_date::date AS day, COALESCE(SUM(amount_rub), 0)::float AS amount
            FROM manual_expenses
            WHERE expense_date BETWEEN $1 AND $2
            GROUP BY 1
            """,
            d_from,
            d_to,
        )
        for r in manual_rows:
            day = r["day"].isoformat()
            daily[day]["cost_manual"] += float(r["amount"] or 0)
    except Exception:
        # Таблица может отсутствовать до миграции — не ломаем /stats
        logger.debug("manual_expenses missing or unreadable", exc_info=True)

    for day, amount in (await fetch_requisite_cost_daily(conn, d_from, d_to)).items():
        daily[day]["cost_payout_requisites"] += amount

    for d in daily.values():
        for k in (
            "cost_cashback",
            "cost_referral",
            "cost_partner",
            "cost_review",
            "cost_wallet_payout",
            "cost_focus_lucky",
            "cost_card",
            "cost_payroll",
            "cost_admin",
            "cost_swap",
            "cost_usdt",
            "cost_manual",
            "cost_payout_requisites",
        ):
            d[k] = round(d.get(k, 0.0), 2)
        _recalc_total(d)

    return dict(daily)
