"""Начисление партнёрской комиссии при PAID (общая БД с exchange)."""
import logging

from services.db import get_pool
from services.partner_tier_service import campaign_tier_snapshot
from services.economics_snapshot import order_economics

logger = logging.getLogger("partner_commission")


async def _accrue_partner_commission(conn, order_id: str) -> bool:
    order = await conn.fetchrow(
        "SELECT order_id, user_id, status, direction, crypto, fiat_amount, crypto_amount, rate, "
        "cashback_applied_rub, card_fee_pct, economics_snapshot FROM orders WHERE order_id = $1",
        order_id,
    )
    if not order or order["status"] != "PAID":
        return False

    exists = await conn.fetchval(
        "SELECT 1 FROM partner_ledger WHERE order_id = $1", order_id
    )
    if exists:
        return False

    attr = await conn.fetchrow(
        """
        SELECT pa.promo_code
        FROM promo_attributions pa
        JOIN promo_campaigns pc ON pc.code = pa.promo_code AND pc.is_active = TRUE
        WHERE pa.user_id = $1
        """,
        order["user_id"],
    )
    if not attr:
        return False

    campaign = await conn.fetchrow(
        """
        SELECT id, code, partner_commission_percent,
               partner_tier_base_percent, partner_tier_step_percent,
               partner_tier_every_n, partner_tier_max_percent,
               author_telegram_id
        FROM promo_campaigns
        WHERE code = $1 AND is_active = TRUE
        """,
        attr["promo_code"],
    )
    if not campaign or campaign["author_telegram_id"] is not None:
        return False

    profit = order_economics(dict(order))["service_profit_rub"]
    if profit <= 0:
        return False

    tier = await campaign_tier_snapshot(conn, dict(campaign), attr["promo_code"])
    pct = float(tier["effective_percent"])
    accrual = round(profit * pct / 100.0, 2)
    if accrual <= 0:
        return False

    await conn.execute(
        """
        INSERT INTO partner_ledger (campaign_id, type, amount_rub, order_id)
        VALUES ($1, 'accrual', $2, $3)
        """,
        campaign["id"],
        accrual,
        order_id,
    )
    logger.info(
        "Partner accrual %.2f RUB campaign=%s order=%s",
        accrual,
        campaign["code"],
        order_id,
    )
    return True


async def accrue_partner_commission(order_id: str, *, conn=None) -> bool:
    if conn is not None:
        return await _accrue_partner_commission(conn, order_id)

    pool = await get_pool()
    async with pool.acquire() as acquired:
        async with acquired.transaction():
            return await _accrue_partner_commission(acquired, order_id)
