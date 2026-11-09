"""Кешбэк 5% покупателю при PAID."""
import logging

from services import config_rates
from services.db import get_pool
from services.economics_snapshot import order_economics

logger = logging.getLogger("user_cashback_commission")


async def _accrue_user_cashback(conn, order_id: str) -> bool:
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
    if (order["direction"] or "").lower() != "buy":
        return False

    exists = await conn.fetchval(
        """
        SELECT 1 FROM user_cashback_ledger
        WHERE order_id = $1 AND type = 'accrual'
        """,
        order_id,
    )
    if exists:
        return False

    profit = order_economics(dict(order))["service_profit_rub"]
    if profit <= 0:
        return False

    from services.cashback_tier import count_completed_exchanges, percent_for_completed_count

    completed = await count_completed_exchanges(conn, int(order["user_id"]))
    pct = percent_for_completed_count(completed)
    accrual = round(profit * pct / 100.0, 2)
    if accrual <= 0:
        return False

    await conn.execute(
        """
        INSERT INTO user_cashback_ledger (
            user_id, type, amount_rub, order_id, note
        )
        VALUES ($1, 'accrual', $2, $3, $4)
        """,
        order["user_id"],
        accrual,
        order_id,
        f"Кешбэк {pct:g}% от прибыли {profit:.2f} ₽",
    )
    logger.info("Cashback accrual %.2f user=%s order=%s", accrual, order["user_id"], order_id)
    return True


async def accrue_user_cashback(order_id: str, *, conn=None) -> bool:
    if conn is not None:
        return await _accrue_user_cashback(conn, order_id)

    pool = await get_pool()
    async with pool.acquire() as acquired:
        async with acquired.transaction():
            return await _accrue_user_cashback(acquired, order_id)
