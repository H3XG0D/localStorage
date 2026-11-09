"""Прибыль сервиса с реферальных сделок партнёров."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from economics_snapshot import order_economics


def _gross_profit_from_orders(orders: list[dict]) -> float:
    total = 0.0
    for o in orders:
        total += order_economics(o)["service_profit_rub"]
    return round(total, 2)

PARTNER_REFERRED_ORDER_SQL = """
    SELECT pc.id AS campaign_id,
           o.direction, o.crypto, o.fiat_amount, o.crypto_amount, o.rate,
           o.cashback_applied_rub, o.card_fee_pct, o.economics_snapshot
    FROM orders o
    JOIN promo_attributions pa ON pa.user_id = o.user_id
    JOIN promo_campaigns pc ON pc.code = pa.promo_code
    JOIN partner_accounts pacc ON pacc.promo_campaign_id = pc.id
    WHERE o.status IN ('PAID', 'COMPLETED')
"""


async def fetch_partner_referred_orders(conn, *, promo_code: str | None = None) -> list[Any]:
    if promo_code:
        rows = await conn.fetch(
            PARTNER_REFERRED_ORDER_SQL + " AND pa.promo_code = $1",
            promo_code,
        )
    else:
        rows = await conn.fetch(PARTNER_REFERRED_ORDER_SQL)
    return list(rows)


def profit_by_campaign_id(rows: list[Any]) -> dict[int, float]:
    by_campaign: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_campaign[int(row["campaign_id"])].append(dict(row))
    return {
        campaign_id: _gross_profit_from_orders(orders)
        for campaign_id, orders in by_campaign.items()
    }


def partner_service_profit_metrics(gross: float, accrued: float) -> dict[str, float]:
    gross_rub = round(float(gross or 0), 2)
    net_rub = round(gross_rub - float(accrued or 0), 2)
    return {
        "service_profit_gross_rub": gross_rub,
        "service_profit_net_rub": net_rub,
    }
