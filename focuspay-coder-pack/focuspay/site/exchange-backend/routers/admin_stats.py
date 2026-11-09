import asyncio
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from collections import defaultdict
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_admin, get_current_finance_viewer
from finance_access import can_view_finance_admin
from config import settings
from db import get_pool
from partner_commission import get_campaign_balance
from admin_salary import today_moscow, salary_month_stats
from economics_snapshot import order_economics
from stats_daily_costs import daily_cost_overhead, fetch_daily_costs
from payout_requisite_stats import card_fee_auto_pct, fetch_requisite_pool_stats
from external_exchange_stats import fetch_period_daily, fetch_period_summary
from operator_balance_fiat import market_prices_rub
from finance_pnl import fetch_casino_owner_profit_daily

router = APIRouter()

_STATS_DEFAULT_DAYS = 30


def _default_stats_range(today: date) -> tuple[date, date]:
    return today - timedelta(days=_STATS_DEFAULT_DAYS - 1), today


_TRAFFIC_TZ = ZoneInfo("Europe/Moscow")
_TRAFFIC_AMOUNT_BUCKETS = (
    ("0-1", 0, 1_000),
    ("1-2", 1_000, 2_000),
    ("2-3", 2_000, 3_000),
    ("3-5", 3_000, 5_000),
    ("5-10", 5_000, 10_000),
    ("10-25", 10_000, 25_000),
    ("25-50", 25_000, 50_000),
    ("50-100", 50_000, 100_000),
    ("100+", 100_000, None),
)
_TRAFFIC_PAID_STATUSES = {"PAID", "COMPLETED"}


def _traffic_bounds_utc_naive(d_from: date, d_to: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d_from, time.min, tzinfo=_TRAFFIC_TZ)
    end = datetime.combine(d_to + timedelta(days=1), time.min, tzinfo=_TRAFFIC_TZ)
    return (
        start.astimezone(timezone.utc).replace(tzinfo=None),
        end.astimezone(timezone.utc).replace(tzinfo=None),
    )


def _traffic_bucket_key(amount: float) -> str:
    for key, minimum, maximum in _TRAFFIC_AMOUNT_BUCKETS:
        if amount >= minimum and (maximum is None or amount < maximum):
            return key
    return "0-1"


def build_traffic_stats(rows) -> dict:
    """Aggregate complete orders result set for the Traffic analytics tab."""
    hours = [{"hour": hour, "orders": 0, "fiat_sum": 0.0, "paid_orders": 0, "paid_fiat_sum": 0.0} for hour in range(24)]
    buckets = {key: {"key": key, "orders": 0, "fiat_sum": 0.0} for key, _, _ in _TRAFFIC_AMOUNT_BUCKETS}
    statuses: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    total_orders = 0
    total_fiat = 0.0
    paid_orders = 0
    paid_fiat = 0.0

    for row in rows:
        status = str(row["status"] or "—").upper()
        source = str(row["order_source"] or "").strip() or "manual"
        amount = float(row["fiat_amount"] or 0)
        created_at = row["created_at"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        hour = created_at.astimezone(_TRAFFIC_TZ).hour
        paid = status in _TRAFFIC_PAID_STATUSES

        total_orders += 1
        total_fiat += amount
        hours[hour]["orders"] += 1
        hours[hour]["fiat_sum"] += amount
        bucket = buckets[_traffic_bucket_key(amount)]
        bucket["orders"] += 1
        bucket["fiat_sum"] += amount
        status_row = statuses.setdefault(status, {"status": status, "orders": 0, "fiat_sum": 0.0})
        status_row["orders"] += 1
        status_row["fiat_sum"] += amount
        source_row = sources.setdefault(source, {"source": source, "orders": 0, "fiat_sum": 0.0})
        source_row["orders"] += 1
        source_row["fiat_sum"] += amount
        if paid:
            paid_orders += 1
            paid_fiat += amount
            hours[hour]["paid_orders"] += 1
            hours[hour]["paid_fiat_sum"] += amount

    def rounded(values: dict) -> dict:
        return {key: round(value, 2) if key.endswith("sum") else value for key, value in values.items()}

    return {
        "summary": {
            "orders": total_orders,
            "fiat_sum": round(total_fiat, 2),
            "paid_orders": paid_orders,
            "paid_fiat_sum": round(paid_fiat, 2),
        },
        "by_hour": [rounded(hour) for hour in hours],
        "amount_buckets": [rounded(buckets[key]) for key, _, _ in _TRAFFIC_AMOUNT_BUCKETS],
        "by_status": [rounded(row) for row in sorted(statuses.values(), key=lambda item: (-item["orders"], item["status"]))],
        "by_source": [rounded(row) for row in sorted(sources.values(), key=lambda item: (-item["orders"], item["source"]))],
    }


@router.get("/stats")
async def get_stats(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    _admin=Depends(get_current_admin),
):
    today = today_moscow()
    try:
        if date_from and date_to:
            d_from = date.fromisoformat(date_from)
            d_to = date.fromisoformat(date_to)
        else:
            d_from, d_to = _default_stats_range(today)
    except ValueError:
        d_from, d_to = _default_stats_range(today)

    can_finance = can_view_finance_admin(_admin)

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT crypto, direction, crypto_amount, fiat_amount, rate, created_at, status,
                   card_fee_pct, cashback_applied_rub, economics_snapshot
            FROM orders
            WHERE status IN ('PAID', 'COMPLETED')
              AND created_at::date BETWEEN $1 AND $2
            ORDER BY created_at DESC
            """,
            d_from,
            d_to,
        )

        # Active/pending counts
        active = await conn.fetchval(
            "SELECT COUNT(*)::int FROM orders WHERE status IN ('CREATED','AWAITING_CHECK','PENDING')"
        )
        total_orders_period = await conn.fetchval(
            "SELECT COUNT(*)::int FROM orders WHERE created_at::date BETWEEN $1 AND $2",
            d_from,
            d_to,
        )

        cost_daily: dict = {}
        external_daily: dict = {}
        casino_daily: dict = {}
        external_summary: dict = {}
        requisite_pool: dict = {}
        if can_finance:
            requisite_pool = await fetch_requisite_pool_stats(
                conn, d_from, d_to, card_fee_pct=card_fee_auto_pct()
            )
            cost_daily = await fetch_daily_costs(conn, d_from, d_to, rows)
            external_daily = await fetch_period_daily(conn, d_from, d_to)
            casino_daily = await fetch_casino_owner_profit_daily(conn, d_from, d_to)
            market = await market_prices_rub()
            external_summary = await fetch_period_summary(
                conn,
                d_from,
                d_to,
                usdt_rub_rate=float(market.get("usdt") or 0),
            )

    # ── Aggregate ─────────────────────────────────────────────────────────────
    by_crypto_buy: dict = defaultdict(lambda: {"count": 0, "crypto_volume": 0.0, "fiat_volume": 0.0, "rates": []})
    by_crypto_sell: dict = defaultdict(lambda: {"count": 0, "crypto_volume": 0.0, "fiat_volume": 0.0, "rates": []})
    total_fiat_buy = 0.0
    total_fiat_sell = 0.0
    estimated_profit = 0.0
    daily: dict = defaultdict(
        lambda: {"buy_fiat": 0.0, "sell_fiat": 0.0, "count": 0, "profit": 0.0}
    )

    for r in rows:
        crypto_key = r["crypto"].split("_")[0].lower()
        day = r["created_at"].date().isoformat()
        if r["direction"] == "buy":
            by_crypto_buy[crypto_key]["count"] += 1
            by_crypto_buy[crypto_key]["crypto_volume"] += r["crypto_amount"]
            by_crypto_buy[crypto_key]["fiat_volume"] += r["fiat_amount"]
            by_crypto_buy[crypto_key]["rates"].append(r["rate"])
            total_fiat_buy += r["fiat_amount"]
            profit = order_economics(dict(r), clamp=False)["service_profit_rub"]
            daily[day]["buy_fiat"] += r["fiat_amount"]
        else:
            by_crypto_sell[crypto_key]["count"] += 1
            by_crypto_sell[crypto_key]["crypto_volume"] += r["crypto_amount"]
            by_crypto_sell[crypto_key]["fiat_volume"] += r["fiat_amount"]
            by_crypto_sell[crypto_key]["rates"].append(r["rate"])
            total_fiat_sell += r["fiat_amount"]
            profit = order_economics(dict(r), clamp=False)["service_profit_rub"]
            daily[day]["sell_fiat"] += r["fiat_amount"]
        daily[day]["count"] += 1
        if can_finance:
            estimated_profit += profit
            daily[day]["profit"] += profit

    def _finalise(d: dict) -> list:
        out = []
        for k, v in d.items():
            avg_rate = sum(v["rates"]) / len(v["rates"]) if v["rates"] else 0
            out.append({
                "crypto": k.upper(),
                "count": v["count"],
                "crypto_volume": round(v["crypto_volume"], 8),
                "fiat_volume": round(v["fiat_volume"], 2),
                "avg_rate": round(avg_rate, 2),
            })
        return sorted(out, key=lambda x: x["fiat_volume"], reverse=True)

    def _days_in_range() -> list[str]:
        out: list[str] = []
        cur = d_from
        while cur <= d_to:
            out.append(cur.isoformat())
            cur += timedelta(days=1)
        return out

    chart = []
    for day in _days_in_range():
        v = daily.get(
            day,
            {"buy_fiat": 0.0, "sell_fiat": 0.0, "count": 0, "profit": 0.0},
        )
        costs = cost_daily.get(day, {}) if can_finance else {}
        ext = external_daily.get(day, {}) if can_finance else {}
        item = {
            "date": day,
            "buy_fiat": round(v["buy_fiat"], 2),
            "sell_fiat": round(v["sell_fiat"], 2),
            "count": v["count"],
        }
        if can_finance:
            item["profit"] = round(v["profit"], 2)
            item["cost_cashback"] = costs.get("cost_cashback", 0.0)
            item["cost_referral"] = costs.get("cost_referral", 0.0)
            item["cost_partner"] = costs.get("cost_partner", 0.0)
            item["cost_review"] = costs.get("cost_review", 0.0)
            item["cost_wallet_payout"] = costs.get("cost_wallet_payout", 0.0)
            item["cost_focus_lucky"] = costs.get("cost_focus_lucky", 0.0)
            item["cost_card"] = costs.get("cost_card", 0.0)
            item["cost_payroll"] = costs.get("cost_payroll", 0.0)
            item["cost_admin"] = costs.get("cost_admin", 0.0)
            item["cost_swap"] = costs.get("cost_swap", 0.0)
            item["cost_usdt"] = costs.get("cost_usdt", 0.0)
            item["cost_manual"] = costs.get("cost_manual", 0.0)
            item["cost_payout_requisites"] = costs.get("cost_payout_requisites", 0.0)
            item["cost_total"] = costs.get("cost_total", 0.0)
            overhead = daily_cost_overhead(costs)
            item["cost_overhead"] = overhead
            item["profit_net"] = round(v["profit"] - overhead, 2)
            ext_profit_usd = float(ext.get("profit_usd") or 0)
            ext_rate = float(external_summary.get("usdt_rub_rate") or 0)
            ext_profit_rub = round(ext_profit_usd * ext_rate, 2) if ext_rate > 0 else 0.0
            item["external_profit_usd"] = round(ext_profit_usd, 2)
            item["external_profit_rub"] = ext_profit_rub
            item["external_turnover_rub"] = float(ext.get("turnover_rub") or 0)
            casino_profit_rub = float(casino_daily.get(day, 0.0) or 0)
            item["casino_profit_rub"] = casino_profit_rub
            item["profit_net_total"] = round(
                item["profit_net"] + ext_profit_rub + casino_profit_rub, 2
            )
        chart.append(item)

    summary = {
        "total_orders_paid": len(rows),
        "total_orders_period": total_orders_period,
        "active_orders": active,
        "total_fiat_buy": round(total_fiat_buy, 2),
        "total_fiat_sell": round(total_fiat_sell, 2),
    }
    if can_finance:
        summary["estimated_profit"] = round(estimated_profit, 2)
        summary["external"] = external_summary
        summary["estimated_profit_with_external"] = round(
            estimated_profit + float(external_summary.get("house_profit_rub") or 0),
            2,
        )
        summary["payout_requisites"] = requisite_pool

    return {
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "can_view_finance": can_finance,
        "summary": summary,
        "by_crypto_buy": _finalise(by_crypto_buy),
        "by_crypto_sell": _finalise(by_crypto_sell),
        "chart": chart,
    }


@router.get("/traffic-stats")
async def get_traffic_stats(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    _admin=Depends(get_current_admin),
):
    today = today_moscow()
    try:
        if date_from and date_to:
            d_from = date.fromisoformat(date_from)
            d_to = date.fromisoformat(date_to)
        else:
            d_from, d_to = _default_stats_range(today)
    except ValueError:
        d_from, d_to = _default_stats_range(today)

    if d_from > d_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")

    start_utc, end_utc = _traffic_bounds_utc_naive(d_from, d_to)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT status, fiat_amount, created_at, order_source
            FROM orders
            WHERE created_at >= $1
              AND created_at < $2
            """,
            start_utc,
            end_utc,
        )

    return {
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "timezone": "Europe/Moscow",
        **build_traffic_stats(rows),
    }


@router.get("/stats/promo")
async def get_promo_stats(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    _admin=Depends(get_current_admin),
):
    today = today_moscow()
    try:
        d_from = date.fromisoformat(date_from) if date_from else today
        d_to = date.fromisoformat(date_to) if date_to else today
    except ValueError:
        d_from = d_to = today

    can_finance = can_view_finance_admin(_admin)

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                pc.id,
                pc.code,
                pc.name,
                pc.bonus_percent,
                pc.ad_spend_rub,
                pc.partner_commission_percent,
                pc.is_active,
                COUNT(DISTINCT pa.user_id)::int         AS attracted_users,
                COUNT(o.id)::int                        AS paid_orders_count,
                COALESCE(SUM(o.fiat_amount), 0)::float  AS paid_fiat_sum
            FROM promo_campaigns pc
            LEFT JOIN promo_attributions pa ON pa.promo_code = pc.code
            LEFT JOIN orders o
              ON o.user_id = pa.user_id
             AND o.status IN ('PAID','COMPLETED')
             AND o.created_at::date BETWEEN $1 AND $2
            GROUP BY pc.id
            ORDER BY paid_fiat_sum DESC
            """,
            d_from,
            d_to,
        )

    result = []
    async with pool.acquire() as conn:
        for r in rows:
            paid_fiat = float(r["paid_fiat_sum"])
            order_rows = await conn.fetch(
                """
                SELECT o.fiat_amount, o.crypto_amount, o.rate, o.crypto,
                       o.cashback_applied_rub, o.card_fee_pct, o.economics_snapshot, o.direction
                FROM orders o
                JOIN promo_attributions pa ON pa.user_id = o.user_id AND pa.promo_code = $1
                WHERE o.status IN ('PAID', 'COMPLETED')
                  AND o.created_at::date BETWEEN $2 AND $3
                """,
                r["code"],
                d_from,
                d_to,
            )
            profit = 0.0
            for o in order_rows:
                profit += order_economics(dict(o))["service_profit_rub"]
            bonus_cost = paid_fiat * float(r["bonus_percent"]) / 100
            ad_spend = float(r["ad_spend_rub"])
            roi = ((profit - bonus_cost - ad_spend) / ad_spend * 100) if ad_spend > 0 else None

            balance = await get_campaign_balance(conn, r["id"])
            accrued = await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)::float FROM partner_ledger
                WHERE campaign_id = $1 AND type = 'accrual'
                """,
                r["id"],
            )
            paid_out = await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)::float FROM partner_ledger
                WHERE campaign_id = $1 AND type = 'payout'
                """,
                r["id"],
            )
            net_after_ad = balance - ad_spend

            item = {
                "id": r["id"],
                "code": r["code"],
                "name": r["name"],
                "bonus_percent": float(r["bonus_percent"]),
                "partner_commission_percent": float(r.get("partner_commission_percent") or 10),
                "ad_spend_rub": ad_spend,
                "is_active": r["is_active"],
                "attracted_users": r["attracted_users"],
                "paid_orders_count": r["paid_orders_count"],
                "paid_fiat_sum": round(paid_fiat, 2),
                "bonus_cost": round(bonus_cost, 2),
                "partner_balance_rub": round(balance, 2),
                "total_accrued": round(float(accrued or 0), 2),
                "total_paid_out": round(abs(float(paid_out or 0)), 2),
            }
            if can_finance:
                item["estimated_profit"] = round(profit, 2)
                item["roi_percent"] = round(roi, 1) if roi is not None else None
                item["net_after_ad_spend"] = round(net_after_ad, 2)
            result.append(item)

    return {
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "can_view_finance": can_finance,
        "campaigns": result,
    }


@router.get("/stats/pnl")
async def get_pnl(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    _admin=Depends(get_current_finance_viewer),
):
    from finance_pnl import compute_pnl

    today = today_moscow()
    try:
        d_from = date.fromisoformat(date_from) if date_from else today
        d_to = date.fromisoformat(date_to) if date_to else today
    except ValueError:
        d_from = d_to = today

    return await compute_pnl(d_from, d_to)


@router.get("/finance-overview")
async def get_finance_overview(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    _admin=Depends(get_current_finance_viewer),
):
    from finance_pnl import compute_pnl
    from collections import defaultdict

    # --- Period parsing (МСК) ---
    today = today_moscow()
    try:
        d_from = today if not date_from else date.fromisoformat(date_from)
        d_to = today if not date_to else date.fromisoformat(date_to)
    except ValueError:
        d_from = d_to = today

    if d_to < d_from:
        raise HTTPException(status_code=400, detail="Invalid date range")

    # --- Previous equal-length period for deltas ---
    period_days = (d_to - d_from).days + 1
    prev_to = d_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=period_days - 1)

    # Income windows (МСК) — считаем параллельно с периодом KPI
    week_from = today - timedelta(days=6)
    month_from = date(today.year, today.month, 1)

    pnl, pnl_prev, pnl_today, pnl_week, pnl_month = await asyncio.gather(
        compute_pnl(d_from, d_to),
        compute_pnl(prev_from, prev_to),
        compute_pnl(today, today),
        compute_pnl(week_from, today),
        compute_pnl(month_from, today),
    )

    def _pct_delta(curr: float, prev: float) -> float | None:
        if abs(prev) < 1e-9:
            if abs(curr) < 1e-9:
                return None
            return 100.0 if curr > 0 else -100.0
        return ((curr - prev) / abs(prev)) * 100.0

    def _get_step_amount(p: dict, key: str) -> float:
        for s in p.get("waterfall") or []:
            if s.get("key") == key:
                return float(s.get("amount") or 0)
        return 0.0

    def _deal_count(p: dict) -> int:
        total = 0
        for row in p.get("by_type") or []:
            total += int(row.get("orders") or 0)
        return total

    turnover = float(pnl["total"]["fiat_volume"])
    turnover_prev = float(pnl_prev["total"]["fiat_volume"])

    deals_count = _deal_count(pnl)
    deals_count_prev = _deal_count(pnl_prev)

    service_profit = _get_step_amount(pnl, "service_profit")
    service_profit_prev = _get_step_amount(pnl_prev, "service_profit")

    net_profit = float(pnl["total"]["net_profit"])
    net_profit_prev = float(pnl_prev["total"]["net_profit"])
    net_profit_label = "Прибыль сервиса + внештат + казино"

    profit_after_costs = float(pnl["total"]["profit_after_costs"])
    profit_after_costs_prev = float(pnl_prev["total"]["profit_after_costs"])

    residual = float(pnl["payroll"]["owner_residual"])
    residual_prev = float(pnl_prev["payroll"]["owner_residual"])

    kpi = [
        {
            "label": "Оборот",
            "value": turnover,
            "sub": "оплаченные сделки",
            "deltaPct": _pct_delta(turnover, turnover_prev),
        },
        {
            "label": "Количество оплаченных сделок",
            "value": float(deals_count),
            "sub": "оплаченные сделки",
            "deltaPct": _pct_delta(float(deals_count), float(deals_count_prev)),
        },
        {
            "label": "Прибыль сервиса (до начислений)",
            "value": service_profit,
            "sub": "цепочка прибыли",
            "deltaPct": _pct_delta(service_profit, service_profit_prev),
        },
        {
            "label": net_profit_label,
            "value": net_profit,
            "sub": "total net_profit",
            "deltaPct": _pct_delta(net_profit, net_profit_prev),
        },
        {
            "label": "Прибыль после начислений",
            "value": profit_after_costs,
            "sub": "profit_after_costs",
            "deltaPct": _pct_delta(profit_after_costs, profit_after_costs_prev),
        },
        {
            "label": "Финальный остаток",
            "value": residual,
            "sub": "owner_residual",
            "deltaPct": _pct_delta(residual, residual_prev),
        },
    ]

    # --- Income blocks: today/week/month (МСК) ---
    def _income_map(p: dict) -> dict:
        service = _get_step_amount(p, "service_profit")
        external_profit = float((p.get("external") or {}).get("house_profit_rub") or 0)
        casino_profit_row = float((p.get("casino") or {}).get("owner_profit_rub") or 0)
        return {
            "turnover": float(p["total"]["fiat_volume"]),
            "spread": float(p["total"]["spread_revenue"]),
            "card_fee_income": float(p["total"]["card_fee_cost"]),
            "service_profit": service,
            "external_profit": external_profit,
            "casino_profit": casino_profit_row,
            # net_profit = маржа сделок+внештат+казино до начислений
            "total_profit": float(p["total"]["net_profit"]),
            "profit_after_costs": float(p["total"]["profit_after_costs"]),
            "owner_residual": float((p.get("payroll") or {}).get("owner_residual") or 0),
        }

    income = {
        "today": _income_map(pnl_today),
        "week": _income_map(pnl_week),
        "month": _income_map(pnl_month),
    }

    # --- Manual expenses: list = calendar month; totals = selected period (from pnl) ---
    pool = await get_pool()
    async with pool.acquire() as conn:
        month_expense_rows = await conn.fetch(
            """
            SELECT
                id,
                category,
                amount_rub,
                title,
                comment,
                expense_date,
                created_at,
                updated_at
            FROM manual_expenses
            WHERE expense_date BETWEEN $1 AND $2
            ORDER BY expense_date DESC, created_at DESC
            LIMIT 500
            """,
            month_from,
            today,
        )

        def _serialize_exp(r) -> dict:
            d = dict(r)
            amt = d.get("amount_rub")
            d["amount_rub"] = float(amt) if amt is not None else 0.0
            for k in ("expense_date", "created_at", "updated_at"):
                v = d.get(k)
                if v is not None and hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            return d

        expenses_by_cat: dict[str, list[dict]] = {
            "mandatory": [],
            "work": [],
            "unexpected": [],
        }
        for r in month_expense_rows:
            item = _serialize_exp(r)
            cat = item["category"]
            if cat in expenses_by_cat:
                expenses_by_cat[cat].append(item)

        # Итоги за выбранный период — из compute_pnl (тот же источник, что waterfall)
        me = pnl.get("manual_expenses") or {}
        expenses_totals = {
            "mandatory": float(me.get("mandatory") or 0),
            "work": float(me.get("work") or 0),
            "unexpected": float(me.get("unexpected") or 0),
            "total": float(me.get("total") or 0),
        }

        # --- Salaries for current calendar month ---
        month_stats = await salary_month_stats(conn, year=today.year, month=today.month)

        # --- Daily profit chart (как /stats + cost_manual в overhead) ---
        order_rows = await conn.fetch(
            """
            SELECT crypto, direction, crypto_amount, fiat_amount, rate, created_at, status,
                   card_fee_pct, cashback_applied_rub, economics_snapshot
            FROM orders
            WHERE status IN ('PAID', 'COMPLETED')
              AND created_at::date BETWEEN $1 AND $2
            ORDER BY created_at DESC
            """,
            d_from,
            d_to,
        )

        cost_daily = await fetch_daily_costs(conn, d_from, d_to, order_rows)
        external_daily = await fetch_period_daily(conn, d_from, d_to)
        casino_daily = await fetch_casino_owner_profit_daily(conn, d_from, d_to)
        market = await market_prices_rub()
        external_summary = await fetch_period_summary(
            conn,
            d_from,
            d_to,
            usdt_rub_rate=float(market.get("usdt") or 0),
        )

        daily: dict[str, dict] = defaultdict(
            lambda: {"buy_fiat": 0.0, "sell_fiat": 0.0, "count": 0, "profit": 0.0}
        )

        for r in order_rows:
            day = r["created_at"].date().isoformat()
            direction = (r["direction"] or "").lower()
            fiat = float(r["fiat_amount"] or 0)
            cb = float(r.get("cashback_applied_rub") or 0)

            if direction == "buy":
                profit = order_economics(dict(r), clamp=False)["service_profit_rub"]
                daily[day]["buy_fiat"] += fiat
                daily[day]["profit"] += profit
            else:
                profit = order_economics(dict(r), clamp=False)["service_profit_rub"]
                daily[day]["sell_fiat"] += fiat
                daily[day]["profit"] += profit

            daily[day]["count"] += 1

        chart: list[dict] = []
        cur = d_from
        usdt_rate = float(external_summary.get("usdt_rub_rate") or 0)
        while cur <= d_to:
            day = cur.isoformat()
            v = daily.get(
                day, {"buy_fiat": 0.0, "sell_fiat": 0.0, "count": 0, "profit": 0.0}
            )
            costs = cost_daily.get(day, {})
            ext = external_daily.get(day, {})

            # overhead уже включает cost_manual (как на дашборде после фикса)
            overhead = daily_cost_overhead(costs)

            ext_profit_usd = float(ext.get("profit_usd") or 0)
            ext_profit_rub = (
                round(ext_profit_usd * usdt_rate, 2) if usdt_rate > 0 else 0.0
            )

            profit_net = round(float(v["profit"]) - overhead, 2)
            casino_profit_rub = float(casino_daily.get(day, 0.0) or 0)
            profit_net_total = round(profit_net + ext_profit_rub + casino_profit_rub, 2)

            item = {
                "date": day,
                "buy_fiat": round(v["buy_fiat"], 2),
                "sell_fiat": round(v["sell_fiat"], 2),
                "count": int(v["count"] or 0),
                "profit": round(float(v["profit"]), 2),
                "profit_net": profit_net,
                "external_profit_rub": ext_profit_rub,
                "casino_profit_rub": casino_profit_rub,
                "profit_net_total": profit_net_total,
            }
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
                "cost_total",
                "cost_overhead",
            ):
                if k in costs:
                    item[k] = costs.get(k)
            item["cost_overhead"] = overhead
            chart.append(item)
            cur = cur + timedelta(days=1)

    return {
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "previous_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
        "kpi": kpi,
        "income": income,
        "expenses": {
            "by_category": expenses_by_cat,
            "totals": expenses_totals,
            "list_period": {"from": month_from.isoformat(), "to": today.isoformat()},
        },
        "salaries": month_stats,
        "pnl": pnl,
        "chart": chart,
    }
