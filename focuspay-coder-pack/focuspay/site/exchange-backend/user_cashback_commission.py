"""User cashback on PAID/COMPLETED BUY orders."""
import logging

from config import settings
from db import get_pool
from economics_snapshot import order_economics

logger = logging.getLogger("user_cashback_commission")


async def accrue_user_cashback(order_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow(
                "SELECT order_id, user_id, status, direction, crypto, fiat_amount, crypto_amount, rate, "
                "cashback_applied_rub, card_fee_pct, economics_snapshot FROM orders WHERE order_id = $1",
                order_id,
            )
            if not order or order["status"] not in ("PAID", "COMPLETED"):
                return False
            if (order["direction"] or "").lower() != "buy":
                return False
            exists = await conn.fetchval(
                "SELECT 1 FROM user_cashback_ledger WHERE order_id = $1 AND type = 'accrual'",
                order_id,
            )
            if exists:
                return False
            profit = order_economics(dict(order))["service_profit_rub"]
            if profit <= 0:
                return False
            from cashback_tier import count_completed_exchanges, percent_for_completed_count

            completed = await count_completed_exchanges(conn, int(order["user_id"]))
            pct = percent_for_completed_count(completed)
            accrual = round(profit * pct / 100.0, 2)
            if accrual <= 0:
                return False
            await conn.execute(
                """
                INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
                VALUES ($1, 'accrual', $2, $3, $4)
                """,
                order["user_id"],
                accrual,
                order_id,
                f"Кешбэк {pct:g}% от прибыли {profit:.2f} ₽",
            )
            return True
