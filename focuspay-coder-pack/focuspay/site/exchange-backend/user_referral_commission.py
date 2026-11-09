"""User referral commission accrual on PAID orders (5% of service profit)."""
import logging

from db import get_pool
from economics_snapshot import order_economics

logger = logging.getLogger("user_referral_commission")

USER_REFERRAL_PERCENT = 5.0


async def accrue_user_referral_commission(order_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow(
                """
                SELECT order_id, user_id, status, direction, crypto,
                       fiat_amount, crypto_amount, rate, cashback_applied_rub,
                       card_fee_pct, economics_snapshot
                FROM orders WHERE order_id = $1
                """,
                order_id,
            )
            if not order or order["status"] not in ("PAID", "COMPLETED"):
                return False

            exists = await conn.fetchval(
                "SELECT 1 FROM user_referral_ledger WHERE order_id = $1",
                order_id,
            )
            if exists:
                return False

            attr = await conn.fetchrow(
                """
                SELECT referrer_user_id FROM user_referral_attributions
                WHERE user_id = $1
                """,
                order["user_id"],
            )
            if not attr:
                return False

            referrer_id = int(attr["referrer_user_id"])
            profit = order_economics(dict(order))["service_profit_rub"]
            if profit <= 0:
                return False

            import runtime_settings

            pct = runtime_settings.user_referral_pct()
            accrual = round(profit * pct / 100.0, 2)
            if accrual <= 0:
                return False

            await conn.execute(
                """
                INSERT INTO user_referral_ledger (
                    referrer_user_id, type, amount_rub, order_id, note
                )
                VALUES ($1, 'accrual', $2, $3, $4)
                """,
                referrer_id,
                accrual,
                order_id,
                f"{pct:g}% от прибыли {profit:.2f} ₽, сделка {order_id}",
            )
            logger.info(
                "User referral accrual %.2f RUB referrer=%s order=%s",
                accrual,
                referrer_id,
                order_id,
            )
            return True
