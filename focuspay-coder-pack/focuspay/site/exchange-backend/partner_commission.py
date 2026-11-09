"""Partner commission accrual on PAID orders."""
import logging

from db import get_pool
from partner_tier_service import campaign_tier_snapshot
from economics_snapshot import order_economics

logger = logging.getLogger("partner_commission")


async def accrue_partner_commission(order_id: str) -> bool:
    """
    Начисляет партнёру % от прибыли, если пользователь пришёл по promo и ордер PAID.
    Идемпотентно по order_id. Возвращает True если начисление создано.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow(
                "SELECT order_id, user_id, status, direction, crypto, fiat_amount, crypto_amount, rate, "
                "cashback_applied_rub, card_fee_pct, economics_snapshot "
                "FROM orders WHERE order_id = $1",
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


async def get_campaign_balance(conn, campaign_id: int) -> float:
    val = await conn.fetchval(
        "SELECT COALESCE(SUM(amount_rub), 0)::float FROM partner_ledger WHERE campaign_id = $1",
        campaign_id,
    )
    return float(val or 0)


async def get_campaign_pending_withdrawals(conn, campaign_id: int) -> float:
    val = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM partner_withdrawals
        WHERE campaign_id = $1 AND status = 'pending'
        """,
        campaign_id,
    )
    return float(val or 0)


async def get_campaign_available_balance(conn, campaign_id: int) -> float:
    balance = await get_campaign_balance(conn, campaign_id)
    pending = await get_campaign_pending_withdrawals(conn, campaign_id)
    return round(max(0.0, balance - pending), 2)
