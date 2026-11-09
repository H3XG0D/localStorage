"""Settle deposit hold + float + trader/teamlead credits when a deal closes."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSettings, DealResult, Requisite, TokenLedgerType, User, UserRole, Zaliv
from app.services import float_ledger, token_ledger
from app.services.teamlead_pool import calc_teamlead_keep_usdt, resolve_pool_percent


async def settle_requisite_closed(
    db: AsyncSession,
    requisite: Requisite,
    deal: DealResult,
    *,
    actor_id: int | None,
) -> None:
    """Release hold, zero float, credit trader (+ teamlead keep from pool)."""
    if requisite.work_token_id and requisite.hold_usdt and requisite.hold_usdt > 0:
        await token_ledger.release_for_requisite(
            db,
            requisite.work_token_id,
            requisite.id,
            Decimal(requisite.hold_usdt),
            actor_id=actor_id,
        )
        requisite.hold_usdt = Decimal("0")

    await float_ledger.close_float(db, requisite, actor_id=actor_id)

    trader = await db.get(User, requisite.trader_id)
    if not trader or not requisite.work_token_id:
        return

    trader_credit = Decimal(deal.zaliv_profit or 0)
    if trader_credit > 0:
        await token_ledger.credit(
            db,
            requisite.work_token_id,
            trader_credit,
            actor_id=actor_id,
            idempotency_key=f"credit-deal-{requisite.id}-trader",
            requisite_id=requisite.id,
            comment=f"Trader profit {trader.profit_percent}%",
        )

    if not trader.teamlead_id:
        return
    tl = await db.get(User, trader.teamlead_id)
    if not tl or tl.role != UserRole.teamlead or not tl.is_active:
        return

    settings = await db.get(AppSettings, 1)
    pool = resolve_pool_percent(tl, settings)

    # Always query — do not touch requisite.zalivs (lazy load breaks outside greenlet).
    result = await db.execute(select(Zaliv).where(Zaliv.requisite_id == requisite.id))
    zalivs = list(result.scalars().all())

    tl_amount = calc_teamlead_keep_usdt(
        zalivs,
        pool=pool,
        target_rate=Decimal(requisite.target_rate),
    )
    if tl_amount <= 0:
        return

    tl_token = await token_ledger.get_active_token_for_user(db, tl.id)
    target_token_id = tl_token.id if tl_token else requisite.work_token_id
    await token_ledger.credit(
        db,
        target_token_id,
        tl_amount,
        actor_id=actor_id,
        idempotency_key=f"credit-deal-{requisite.id}-teamlead",
        requisite_id=requisite.id,
        comment=f"Teamlead keep from pool {pool}%",
        entry_type=TokenLedgerType.credit,
    )


async def release_on_deactivate(
    db: AsyncSession,
    requisite: Requisite,
    *,
    actor_id: int | None,
) -> None:
    if requisite.work_token_id and requisite.hold_usdt and requisite.hold_usdt > 0:
        await token_ledger.release_for_requisite(
            db,
            requisite.work_token_id,
            requisite.id,
            Decimal(requisite.hold_usdt),
            actor_id=actor_id,
        )
        requisite.hold_usdt = Decimal("0")
