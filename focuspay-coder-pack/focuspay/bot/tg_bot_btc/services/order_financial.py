"""Финансовые побочные эффекты смены статуса заявки."""
import logging

from services.exchange_discount_db import (
    confirm_discount_for_order,
    release_discount_for_order,
)
from services.user_cashback_db import (
    apply_pending_remainder_for_order,
    confirm_cashback_for_order,
    release_cashback_for_order,
)

logger = logging.getLogger("order_financial")


async def apply_paid_financial_effects(order_id: str, *, conn=None) -> None:
    """Кешбэк spend + остаток на баланс — только после PAID/COMPLETED."""
    await confirm_cashback_for_order(order_id, conn=conn)
    await confirm_discount_for_order(order_id, conn=conn)
    await apply_pending_remainder_for_order(order_id, conn=conn)


async def apply_cancel_financial_effects(order_id: str, *, conn=None) -> None:
    await release_cashback_for_order(order_id, conn=conn)
    await release_discount_for_order(order_id, conn=conn)


async def reverse_paid_accruals_for_order(order_id: str, *, conn=None) -> None:
    """Откат начислений referral/cashback/partner при отмене после COMPLETED/PAID."""

    async def _run(c):
        await c.execute(
            "DELETE FROM user_referral_ledger WHERE order_id = $1 AND type = 'accrual'",
            order_id,
        )
        await c.execute(
            "DELETE FROM user_cashback_ledger WHERE order_id = $1 AND type = 'accrual'",
            order_id,
        )
        await c.execute(
            "DELETE FROM user_cashback_ledger WHERE order_id = $1 AND type = 'remainder_credit'",
            f"{order_id}:remainder",
        )
        await c.execute("DELETE FROM partner_ledger WHERE order_id = $1", order_id)
        from services.raffle_accrual import void_raffle_tickets_for_order

        await void_raffle_tickets_for_order(order_id, conn=c)

    if conn is not None:
        await _run(conn)
        return
    from services.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as acquired:
        async with acquired.transaction():
            await _run(acquired)


async def apply_cancel_group_if_needed(order_id: str, *, conn=None) -> None:
    async def _run(c):
        row = await c.fetchrow(
            "SELECT group_id, part_index, status FROM orders WHERE order_id = $1",
            order_id,
        )
        if not row or not row["group_id"]:
            return
        if int(row.get("part_index") or 1) != 1:
            return
        from services.order_groups import cancel_order_group

        await cancel_order_group(int(row["group_id"]))

    if conn is not None:
        await _run(conn)
        return
    from services.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as acquired:
        await _run(acquired)
