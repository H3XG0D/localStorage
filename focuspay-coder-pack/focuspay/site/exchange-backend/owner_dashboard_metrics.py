"""Owner business dashboard metrics: periods, PnL deltas, audience growth.

Canonical definitions (see docs/Reviews/2026-08-12-owner-dashboard-freeze.md):
- timezone: Europe/Moscow
- week starts Monday
- month = last 30 calendar days (inclusive), not calendar MTD
- net_income = compute_pnl.payroll.owner_residual
- gross_commissions = compute_pnl.total.net_profit (service margin, NOT turnover)
- orders = PAID+COMPLETED deal count from PnL by_type (excl. external)
- refunds = unavailable until a real refund source exists
- owner_finance_ledger: empty until confirmed entries are written (no backfill)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

MSK = ZoneInfo("Europe/Moscow")
PeriodKey = Literal["today", "yesterday", "week", "month", "year"]
PERIOD_KEYS: tuple[PeriodKey, ...] = ("today", "yesterday", "week", "month", "year")

# Daily owner_residual series is expensive (full PnL per day); only short periods.
_MAX_DAILY_SERIES_DAYS = 7


def today_moscow() -> date:
    return datetime.now(MSK).date()


@dataclass(frozen=True)
class PeriodWindow:
    key: PeriodKey
    label_ru: str
    current_from: date
    current_to: date
    previous_from: date
    previous_to: date
    timezone: str = "Europe/Moscow"
    week_starts_on: str = "monday"


def resolve_period_window(period: str, *, today: date | None = None) -> PeriodWindow:
    """Calendar boundaries in Europe/Moscow; previous = equivalent length."""
    key = (period or "today").strip().lower()
    if key not in PERIOD_KEYS:
        raise ValueError(f"Unsupported period: {period}")
    today = today or today_moscow()

    if key == "today":
        y = today - timedelta(days=1)
        return PeriodWindow(
            key="today",
            label_ru="сегодня",
            current_from=today,
            current_to=today,
            previous_from=y,
            previous_to=y,
        )
    if key == "yesterday":
        y = today - timedelta(days=1)
        p = today - timedelta(days=2)
        return PeriodWindow(
            key="yesterday",
            label_ru="вчера",
            current_from=y,
            current_to=y,
            previous_from=p,
            previous_to=p,
        )
    if key == "week":
        monday = today - timedelta(days=today.weekday())  # Mon=0
        into = (today - monday).days
        prev_monday = monday - timedelta(days=7)
        return PeriodWindow(
            key="week",
            label_ru="неделя",
            current_from=monday,
            current_to=today,
            previous_from=prev_monday,
            previous_to=prev_monday + timedelta(days=into),
        )
    if key == "month":
        # Rolling 30 calendar days, inclusive — same as the admin «Месяц» preset.
        current_from = today - timedelta(days=29)
        previous_to = current_from - timedelta(days=1)
        previous_from = previous_to - timedelta(days=29)
        return PeriodWindow(
            key="month",
            label_ru="месяц",
            current_from=current_from,
            current_to=today,
            previous_from=previous_from,
            previous_to=previous_to,
        )
    # year
    first = date(today.year, 1, 1)
    prev_first = date(today.year - 1, 1, 1)
    try:
        prev_end = today.replace(year=today.year - 1)
    except ValueError:
        prev_end = date(today.year - 1, 2, 28)
    return PeriodWindow(
        key="year",
        label_ru="год",
        current_from=first,
        current_to=today,
        previous_from=prev_first,
        previous_to=prev_end,
    )


def _delta(current: float, previous: float) -> dict[str, Any]:
    abs_change = round(current - previous, 2)
    if abs(previous) < 1e-9:
        pct: float | None = None
    else:
        pct = round((current - previous) / abs(previous) * 100.0, 2)
    return {
        "current": round(current, 2),
        "previous": round(previous, 2),
        "abs_change": abs_change,
        "pct_change": pct,
    }


def _int_delta(current: int, previous: int) -> dict[str, Any]:
    abs_change = current - previous
    if previous == 0:
        pct: float | None = None
    else:
        pct = round((current - previous) / abs(previous) * 100.0, 2)
    return {
        "current": current,
        "previous": previous,
        "abs_change": abs_change,
        "pct_change": pct,
    }


def _orders_from_pnl(pnl: dict) -> int:
    total = 0
    for row in pnl.get("by_type") or []:
        if (row.get("type") or "") in ("external", "casino"):
            continue
        total += int(row.get("orders") or 0)
    return total


def _money_from_pnl(pnl: dict) -> dict[str, Any]:
    total = pnl.get("total") or {}
    payroll = pnl.get("payroll") or {}
    costs = pnl.get("costs") or {}
    manuals = pnl.get("manual_expenses") or {}
    return {
        "gross_commissions_rub": float(total.get("net_profit") or 0),
        "net_income_rub": float(payroll.get("owner_residual") or 0),
        "turnover_rub": float(total.get("fiat_volume") or 0),
        "profit_after_costs_rub": float(total.get("profit_after_costs") or 0),
        "orders": _orders_from_pnl(pnl),
        "costs_total_rub": float(costs.get("total") or 0),
        "manual_expenses_rub": float(manuals.get("total") or 0),
        "operators_payroll_rub": float(payroll.get("operators_total") or 0),
        "admin_salary_rub": float(payroll.get("admin_salary") or 0),
    }


def _expense_lines_from_pnl(pnl: dict) -> tuple[float, list[dict[str, Any]]]:
    """Canonical day costs = waterfall rows with kind=expense (same as /x8/stats)."""
    lines: list[dict[str, Any]] = []
    total = 0.0
    for row in pnl.get("waterfall") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("kind") or "") != "expense":
            continue
        try:
            amount = abs(float(row.get("amount") or 0))
        except (TypeError, ValueError):
            continue
        if amount < 0.01:
            continue
        key = str(row.get("key") or "expense")
        label = str(row.get("label") or key).strip() or key
        lines.append({"key": key, "label": label, "amount_rub": round(amount, 2)})
        total += amount
    return round(total, 2), lines


_MSK_DATE = "((%s AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Moscow')::date"


async def _count_bot_new(conn, d_from: date, d_to: date) -> int:
    col = _MSK_DATE % "first_seen_at"
    return int(
        await conn.fetchval(
            f"""
            SELECT COUNT(*)::int FROM bot_users
            WHERE {col} BETWEEN $1 AND $2
            """,  # nosec B608
            d_from,
            d_to,
        )
        or 0
    )


async def _count_web_new(conn, d_from: date, d_to: date) -> int:
    col = _MSK_DATE % "created_at"
    try:
        return int(
            await conn.fetchval(
                f"""
                SELECT COUNT(*)::int FROM web_users
                WHERE COALESCE(is_admin, FALSE) IS NOT TRUE
                  AND {col} BETWEEN $1 AND $2
                """,  # nosec B608
                d_from,
                d_to,
            )
            or 0
        )
    except Exception:
        logger.exception("web_users count failed")
        return 0


async def _count_new_partners(conn, d_from: date, d_to: date) -> int:
    col = _MSK_DATE % "created_at"
    try:
        return int(
            await conn.fetchval(
                f"""
                SELECT COUNT(*)::int FROM partner_accounts
                WHERE is_active = TRUE
                  AND {col} BETWEEN $1 AND $2
                """,  # nosec B608
                d_from,
                d_to,
            )
            or 0
        )
    except Exception:
        logger.exception("partner_accounts count failed")
        return 0


async def _audience_for_range(d_from: date, d_to: date) -> dict[str, int]:
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        bot_new = await _count_bot_new(conn, d_from, d_to)
        web_new = await _count_web_new(conn, d_from, d_to)
        partners = await _count_new_partners(conn, d_from, d_to)
    return {
        "bot_new": bot_new,
        "web_new": web_new,
        "new_users": bot_new + web_new,
        "new_partners": partners,
    }


async def _ledger_snapshot(d_from: date, d_to: date) -> dict[str, Any]:
    """Minimal owner ledger. Never invent historical rows."""
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = 'owner_finance_ledger'
                )
                """
            )
            if not exists:
                return {
                    "data_status": "unavailable",
                    "reason": "table_missing",
                    "entries": [],
                    "by_type": [],
                }
            rows = await conn.fetch(
                """
                SELECT id, occurred_at, entry_type, amount, currency, source,
                       reference, status, note
                FROM owner_finance_ledger
                WHERE status = 'confirmed'
                  AND ((occurred_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Moscow')::date
                      BETWEEN $1 AND $2
                ORDER BY occurred_at DESC, id DESC
                LIMIT 200
                """,
                d_from,
                d_to,
            )
        except Exception:
            logger.exception("owner_finance_ledger query failed")
            return {
                "data_status": "unavailable",
                "reason": "query_failed",
                "entries": [],
                "by_type": [],
            }

    if not rows:
        return {
            "data_status": "empty",
            "reason": "no_confirmed_entries",
            "entries": [],
            "by_type": [],
        }

    entries = []
    by_type: dict[str, float] = {}
    for r in rows:
        amt = float(r["amount"] or 0)
        et = str(r["entry_type"] or "unknown")
        by_type[et] = round(by_type.get(et, 0.0) + amt, 2)
        occurred = r["occurred_at"]
        entries.append(
            {
                "id": int(r["id"]),
                "occurred_at": occurred.isoformat() if hasattr(occurred, "isoformat") else str(occurred),
                "entry_type": et,
                "amount": amt,
                "currency": str(r["currency"] or "RUB"),
                "source": r["source"],
                "reference": r["reference"],
                "status": str(r["status"] or "confirmed"),
                "note": r["note"],
            }
        )
    return {
        "data_status": "available",
        "reason": None,
        "entries": entries,
        "by_type": [{"type": k, "amount_rub": v} for k, v in sorted(by_type.items())],
    }


async def _income_by_day(window: PeriodWindow) -> dict[str, Any]:
    from finance_pnl import compute_pnl

    days = (window.current_to - window.current_from).days + 1
    if days > _MAX_DAILY_SERIES_DAYS:
        return {
            "data_status": "unavailable",
            "reason": "period_too_long_for_daily_pnl",
            "metric": "net_income_rub",
            "points": [],
        }
    points = []
    cur = window.current_from
    while cur <= window.current_to:
        pnl = await compute_pnl(cur, cur)
        money = _money_from_pnl(pnl)
        expenses_total, expense_lines = _expense_lines_from_pnl(pnl)
        points.append(
            {
                "date": cur.isoformat(),
                "net_income_rub": money["net_income_rub"],
                "gross_commissions_rub": money["gross_commissions_rub"],
                "orders": money["orders"],
                "expenses_total_rub": expenses_total,
                "expense_lines": expense_lines,
            }
        )
        cur += timedelta(days=1)
    return {
        "data_status": "available",
        "reason": None,
        "metric": "net_income_rub",
        "currency": "RUB",
        "source": "compute_pnl",
        "points": points,
    }


async def build_owner_dashboard(period: str, *, today: date | None = None) -> dict[str, Any]:
    from finance_pnl import compute_pnl

    window = resolve_period_window(period, today=today)
    cur_pnl = await compute_pnl(window.current_from, window.current_to)
    prev_pnl = await compute_pnl(window.previous_from, window.previous_to)
    cur_m = _money_from_pnl(cur_pnl)
    prev_m = _money_from_pnl(prev_pnl)
    cur_aud = await _audience_for_range(window.current_from, window.current_to)
    prev_aud = await _audience_for_range(window.previous_from, window.previous_to)
    ledger = await _ledger_snapshot(window.current_from, window.current_to)
    income_by_day = await _income_by_day(window)

    return {
        "timezone": window.timezone,
        "week_starts_on": window.week_starts_on,
        "currency": "RUB",
        "definitions": {
            "net_income": "compute_pnl.payroll.owner_residual",
            "gross_commissions": "compute_pnl.total.net_profit (service margin before accruals; not turnover)",
            "orders": "PAID+COMPLETED order count from PnL by_type excluding external",
            "turnover_note": "turnover_rub is fiat volume, not income",
            "expenses": "sum of |waterfall.amount| where kind=expense (same lines as /x8/stats)",
            "refunds": "unavailable — no confirmed refund ledger",
            "period_bounds": "Europe/Moscow; week = Monday→today (WoT); month = last 30 days",
        },
        "period": {
            "key": window.key,
            "label": window.label_ru,
            "current": {
                "from": window.current_from.isoformat(),
                "to": window.current_to.isoformat(),
            },
            "previous": {
                "from": window.previous_from.isoformat(),
                "to": window.previous_to.isoformat(),
            },
        },
        "data_source": {
            "finance": "compute_pnl",
            "status": "available",
            "fetched_at": datetime.now(MSK).isoformat(),
        },
        "metrics": {
            "net_income": {
                **_delta(cur_m["net_income_rub"], prev_m["net_income_rub"]),
                "currency": "RUB",
                "unit": "money",
            },
            "gross_commissions": {
                **_delta(cur_m["gross_commissions_rub"], prev_m["gross_commissions_rub"]),
                "currency": "RUB",
                "unit": "money",
            },
            "orders": {
                **_int_delta(cur_m["orders"], prev_m["orders"]),
                "unit": "count",
            },
            "new_users": {
                **_int_delta(cur_aud["new_users"], prev_aud["new_users"]),
                "unit": "count",
                "breakdown": {
                    "bot_new": cur_aud["bot_new"],
                    "web_new": cur_aud["web_new"],
                    "previous_bot_new": prev_aud["bot_new"],
                    "previous_web_new": prev_aud["web_new"],
                },
            },
            "new_partners": {
                **_int_delta(cur_aud["new_partners"], prev_aud["new_partners"]),
                "unit": "count",
            },
            "turnover_rub": {
                **_delta(cur_m["turnover_rub"], prev_m["turnover_rub"]),
                "currency": "RUB",
                "unit": "money",
                "is_income": False,
            },
        },
        "refunds": {
            "data_status": "unavailable",
            "reason": "no_confirmed_refund_source",
            "amount_rub": None,
        },
        "ledger": ledger,
        "income_by_day": income_by_day,
        "pnl_by_day": income_by_day,
        "raw_costs_current": {
            "costs_total_rub": cur_m["costs_total_rub"],
            "manual_expenses_rub": cur_m["manual_expenses_rub"],
            "operators_payroll_rub": cur_m["operators_payroll_rub"],
            "admin_salary_rub": cur_m["admin_salary_rub"],
            "profit_after_costs_rub": cur_m["profit_after_costs_rub"],
        },
    }
