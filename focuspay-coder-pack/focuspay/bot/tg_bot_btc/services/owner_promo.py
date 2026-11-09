"""Краткая promo ROI строка для /pulse (логика как в /stats)."""
from __future__ import annotations

from services.db import get_promo_paid_orders_for_days, get_promo_stats_for_days
from services.economics_snapshot import order_economics


async def best_promo_roi_line(days: int = 1) -> str | None:
    promo_rows = await get_promo_stats_for_days(days)
    promo_orders = await get_promo_paid_orders_for_days(days)
    campaign_profit_map: dict[int, float] = {}
    for o in promo_orders:
        cid = int(o["campaign_id"])
        profit = order_economics(dict(o))["service_profit_rub"]
        campaign_profit_map[cid] = campaign_profit_map.get(cid, 0.0) + profit

    best: tuple[str, float] | None = None
    for r in promo_rows:
        attracted = int(r["attracted_users"] or 0)
        if attracted <= 0:
            continue
        ad_spend = float(r["ad_spend_rub"] or 0.0)
        bonus_percent = float(r["bonus_percent"] or 0.0)
        campaign_profit = float(campaign_profit_map.get(int(r["id"]), 0.0))
        bonus_cost = campaign_profit * (bonus_percent / 100.0)
        analytics_net = campaign_profit - bonus_cost - ad_spend
        roi = ((analytics_net / ad_spend) * 100.0) if ad_spend > 0 else analytics_net
        name = f"{r['name']} ({r['code']})"
        if best is None or roi > best[1]:
            best = (name, roi)

    if not best:
        return None
    label = "сегодня" if days == 1 else f"{days}д"
    return f"🎯 Promo · {label}: лучшая <b>{best[0]}</b> · ROI ~ <code>{best[1]:,.0f}%</code>"
