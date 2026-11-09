"""Payout jobs: traders claim RUB payouts within a deadline."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    PayoutClaim,
    PayoutClaimStatus,
    PayoutJob,
    PayoutJobStatus,
    PayoutPayMethod,
    Requisite,
    RequisiteStatus,
    User,
    UserRole,
)
from app.services.notifications import notify_roles, notify_user

CLAIM_TTL_MINUTES = 15
OPEN_STATUSES = {RequisiteStatus.active, RequisiteStatus.in_work, RequisiteStatus.awaiting_doliv, RequisiteStatus.doliv_in_progress}


async def card_float_summary(db: AsyncSession) -> dict:
    result = await db.execute(
        select(func.coalesce(func.sum(Requisite.float_rub), 0)).where(
            Requisite.status.in_(list(OPEN_STATUSES))
        )
    )
    total = Decimal(str(result.scalar() or 0))
    by_trader = await db.execute(
        select(Requisite.trader_id, func.coalesce(func.sum(Requisite.float_rub), 0))
        .where(Requisite.status.in_(list(OPEN_STATUSES)))
        .group_by(Requisite.trader_id)
    )
    traders = [
        {"trader_id": tid, "float_rub": str(Decimal(str(flt)))}
        for tid, flt in by_trader.all()
        if Decimal(str(flt)) > 0
    ]
    traders.sort(key=lambda x: Decimal(x["float_rub"]), reverse=True)
    return {"total_float_rub": str(total), "by_trader": traders, "traders_with_float": len(traders)}


async def trader_available_float(db: AsyncSession, trader_id: int) -> Decimal:
    result = await db.execute(
        select(func.coalesce(func.sum(Requisite.float_rub), 0)).where(
            Requisite.trader_id == trader_id,
            Requisite.status.in_(list(OPEN_STATUSES)),
        )
    )
    return Decimal(str(result.scalar() or 0))


async def create_job(
    db: AsyncSession,
    *,
    amount_rub: Decimal,
    pay_method: PayoutPayMethod,
    requisites: dict | None,
    source: str = "manual",
    external_ref: str | None = None,
    created_by_id: int | None = None,
    ttl_minutes: int = CLAIM_TTL_MINUTES,
) -> PayoutJob:
    if amount_rub <= 0:
        raise HTTPException(400, "amount_rub must be positive")
    now = datetime.now(timezone.utc)
    job = PayoutJob(
        amount_rub=amount_rub,
        remaining_rub=amount_rub,
        pay_method=pay_method,
        requisites=requisites or {},
        source=source,
        external_ref=external_ref,
        status=PayoutJobStatus.open,
        claim_deadline=now + timedelta(minutes=ttl_minutes),
        created_by_id=created_by_id,
    )
    db.add(job)
    await db.flush()

    # Prefer notifying traders who have float (fewer checks / better coverage)
    summary = await card_float_summary(db)
    for row in summary["by_trader"][:50]:
        await notify_user(
            db,
            int(row["trader_id"]),
            "Новая выплата",
            f"Заявка #{job.id}: {amount_rub} ₽ · принять за {ttl_minutes} мин (укажите сумму)",
            kind="payout",
            link="/trader/payouts",
        )
    if not summary["by_trader"]:
        await notify_roles(
            db,
            [UserRole.trader],
            "Новая выплата",
            f"Заявка #{job.id}: {amount_rub} ₽ · принять за {ttl_minutes} мин",
            kind="payout",
            link="/trader/payouts",
        )
    return job


async def expire_if_needed(db: AsyncSession, job: PayoutJob) -> PayoutJob:
    if job.status in (PayoutJobStatus.done, PayoutJobStatus.cancelled, PayoutJobStatus.expired):
        return job
    now = datetime.now(timezone.utc)
    deadline = job.claim_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if now > deadline and job.remaining_rub > 0:
        job.status = PayoutJobStatus.expired
        await db.flush()
    return job


async def claim(
    db: AsyncSession,
    job: PayoutJob,
    trader: User,
    amount_rub: Decimal,
) -> PayoutClaim:
    await expire_if_needed(db, job)
    if job.status not in (PayoutJobStatus.open, PayoutJobStatus.partial):
        raise HTTPException(400, f"Job not claimable (status={job.status.value})")
    if amount_rub <= 0:
        raise HTTPException(400, "amount_rub must be positive")
    if amount_rub > job.remaining_rub:
        raise HTTPException(400, f"amount exceeds remaining {job.remaining_rub}")

    avail = await trader_available_float(db, trader.id)
    if amount_rub > avail:
        raise HTTPException(400, f"Insufficient card float: have {avail}, need {amount_rub}")

    claim_row = PayoutClaim(
        job_id=job.id,
        trader_id=trader.id,
        amount_rub=amount_rub,
        status=PayoutClaimStatus.claimed,
    )
    db.add(claim_row)
    job.remaining_rub = Decimal(job.remaining_rub) - amount_rub
    if job.remaining_rub <= 0:
        job.remaining_rub = Decimal("0")
        job.status = PayoutJobStatus.done
    else:
        job.status = PayoutJobStatus.partial
    await db.flush()
    return claim_row


async def mark_claim_paid(db: AsyncSession, claim_row: PayoutClaim, trader: User) -> PayoutClaim:
    if claim_row.trader_id != trader.id:
        raise HTTPException(404, "Claim not found")
    if claim_row.status != PayoutClaimStatus.claimed:
        raise HTTPException(400, "Claim already closed")
    claim_row.status = PayoutClaimStatus.paid
    claim_row.paid_at = datetime.now(timezone.utc)
    await db.flush()
    return claim_row


async def list_open_jobs(db: AsyncSession) -> list[PayoutJob]:
    result = await db.execute(
        select(PayoutJob)
        .options(selectinload(PayoutJob.claims))
        .where(PayoutJob.status.in_([PayoutJobStatus.open, PayoutJobStatus.partial]))
        .order_by(PayoutJob.id.desc())
    )
    jobs = list(result.scalars().all())
    for j in jobs:
        await expire_if_needed(db, j)
    return [j for j in jobs if j.status in (PayoutJobStatus.open, PayoutJobStatus.partial)]
