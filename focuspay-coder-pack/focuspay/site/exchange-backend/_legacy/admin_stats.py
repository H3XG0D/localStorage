from datetime import date, datetime, timedelta
from typing import Optional
from collections import defaultdict

from fastapi import APIRouter, Depends, Query

from auth import get_current_admin, get_current_finance_viewer
from finance_access import can_view_finance_admin
from config import settings
from db import get_pool
from partner_commission import get_campaign_balance
from service_profit import order_service_profit, CARD_FEE_DEFAULT
from stats_daily_costs import daily_cost_overhead, fetch_daily_costs

router = APIRouter()

_STATS_DEFAULT_DAYS = 30


def _default_stats_range(today: date) -> tuple[date, date]:
    return today - timedelta(days=_STATS_DEFAULT_DAYS - 1), today


@router.get("/stats")
async def get_stats(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    _admin=Depends(get_current_admin),
):
    today = date.today()
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
                   card_fee_pct, cashback_applied_rub
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
        if can_finance:
            cost_daily = await fetch_daily_costs(conn, d_from, d_to, rows)

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
            fee = float(r["card_fee_pct"]) if r["card_fee_pct"] is not None else None
            profit = order_service_profit(
                "buy",
                r["crypto"],
                r["fiat_amount"],
                r["crypto_amount"],
                r["rate"],
                cashback_applied_rub=float(r.get("cashback_applied_rub") or 0),
                card_fee_pct=fee,
            )
            daily[day]["buy_fiat"] += r["fiat_amount"]
        else:
            by_crypto_sell[crypto_key]["count"] += 1
            by_crypto_sell[crypto_key]["crypto_volume"] += r["crypto_amount"]
            by_crypto_sell[crypto_key]["fiat_volume"] += r["fiat_amount"]
            by_crypto_sell[crypto_key]["rates"].append(r["rate"])
            total_fiat_sell += r["fiat_amount"]
            profit = order_service_profit(
                "sell", r["crypto"], r["fiat_amount"], r["crypto_amount"], r["rate"]
            )
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
            item["cost_card"] = costs.get("cost_card", 0.0)
            item["cost_payroll"] = costs.get("cost_payroll", 0.0)
            item["cost_admin"] = costs.get("cost_admin", 0.0)
            item["cost_swap"] = costs.get("cost_swap", 0.0)
            item["cost_total"] = costs.get("cost_total", 0.0)
            overhead = daily_cost_overhead(costs)
            item["cost_overhead"] = overhead
            item["profit_net"] = round(v["profit"] - overhead, 2)
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

    return {
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "can_view_finance": can_finance,
        "summary": summary,
        "by_crypto_buy": _finalise(by_crypto_buy),
        "by_crypto_sell": _finalise(by_crypto_sell),
        "chart": chart,
    }


@router.get("/stats/promo")
async def get_promo_stats(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    _admin=Depends(get_current_admin),
):
    today = date.today()
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
                       o.cashback_applied_rub, o.card_fee_pct, o.direction
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
                fee = (
                    float(o["card_fee_pct"])
                    if o["card_fee_pct"] is not None
                    else CARD_FEE_DEFAULT
                )
                profit += order_service_profit(
                    o["direction"] or "buy",
                    o["crypto"] or "",
                    float(o["fiat_amount"] or 0),
                    float(o["crypto_amount"] or 0),
                    float(o["rate"] or 0),
                    cashback_applied_rub=float(o["cashback_applied_rub"] or 0),
                    card_fee_pct=fee,
                )
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

    today = date.today()
    try:
        d_from = date.fromisoformat(date_from) if date_from else today
        d_to = date.fromisoformat(date_to) if date_to else today
    except ValueError:
        d_from = d_to = today

    return await compute_pnl(d_from, d_to)
