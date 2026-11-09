"""Per-requisite RUB float: money sitting on the card after payment confirm."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FloatLedgerType, Requisite, RequisiteFloatLedger

RUB_Q = Decimal("0.01")


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(RUB_Q, rounding=ROUND_HALF_UP)


async def _add_float(
    db: AsyncSession,
    requisite: Requisite,
    *,
    entry_type: FloatLedgerType,
    amount: Decimal,
    idempotency_key: str,
    actor_id: int | None = None,
    zaliv_id: int | None = None,
    comment: str | None = None,
    allow_negative: bool = False,
) -> RequisiteFloatLedger:
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Float amount must be positive")
    amount = _q(amount)

    existing = await db.execute(
        select(RequisiteFloatLedger).where(RequisiteFloatLedger.idempotency_key == idempotency_key)
    )
    found = existing.scalar_one_or_none()
    if found:
        return found

    delta = amount if entry_type == FloatLedgerType.confirm else -amount
    if entry_type == FloatLedgerType.adjust:
        # adjust uses signed amount via comment convention: positive confirm-like, negative settle-like
        # For simplicity adjust always decreases unless comment starts with '+'
        delta = -amount

    new_float = _q((requisite.float_rub or Decimal("0")) + delta)
    if new_float < 0 and not allow_negative:
        raise HTTPException(status_code=400, detail="float_rub cannot go negative")

    entry = RequisiteFloatLedger(
        requisite_id=requisite.id,
        entry_type=entry_type,
        amount=amount,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
        zaliv_id=zaliv_id,
        comment=comment,
    )
    db.add(entry)
    requisite.float_rub = new_float
    await db.flush()
    return entry


async def confirm_payment(
    db: AsyncSession,
    requisite: Requisite,
    amount: Decimal,
    *,
    zaliv_id: int,
    actor_id: int | None,
) -> RequisiteFloatLedger:
    return await _add_float(
        db,
        requisite,
        entry_type=FloatLedgerType.confirm,
        amount=amount,
        idempotency_key=f"confirm-zaliv-{zaliv_id}",
        actor_id=actor_id,
        zaliv_id=zaliv_id,
        comment="Payment confirmed (zaliv)",
    )


async def settle_float(
    db: AsyncSession,
    requisite: Requisite,
    amount: Decimal,
    *,
    actor_id: int | None,
    idempotency_key: str,
    comment: str | None = None,
) -> RequisiteFloatLedger:
    return await _add_float(
        db,
        requisite,
        entry_type=FloatLedgerType.settle,
        amount=amount,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
        comment=comment or "Settle float",
    )


async def close_float(
    db: AsyncSession,
    requisite: Requisite,
    *,
    actor_id: int | None,
) -> RequisiteFloatLedger | None:
    current = _q(requisite.float_rub or Decimal("0"))
    if current <= 0:
        requisite.float_rub = Decimal("0")
        return None
    return await _add_float(
        db,
        requisite,
        entry_type=FloatLedgerType.close,
        amount=current,
        idempotency_key=f"close-float-req-{requisite.id}",
        actor_id=actor_id,
        comment="Close deal — zero float",
    )


async def float_summary_for_trader(db: AsyncSession, trader_id: int) -> list[dict]:
    result = await db.execute(
        select(Requisite).where(Requisite.trader_id == trader_id).order_by(Requisite.id.desc())
    )
    rows = []
    total = Decimal("0")
    for r in result.scalars().all():
        fr = _q(r.float_rub or Decimal("0"))
        total += fr
        rows.append(
            {
                "requisite_id": r.id,
                "name": r.name,
                "status": r.status.value,
                "float_rub": fr,
            }
        )
    return {"items": rows, "total_float_rub": total}


async def recompute_float_from_ledger(db: AsyncSession, requisite_id: int) -> Decimal:
    result = await db.execute(
        select(RequisiteFloatLedger).where(RequisiteFloatLedger.requisite_id == requisite_id)
    )
    total = Decimal("0")
    for e in result.scalars().all():
        if e.entry_type == FloatLedgerType.confirm:
            total += e.amount
        else:
            total -= e.amount
    return _q(max(total, Decimal("0")))
