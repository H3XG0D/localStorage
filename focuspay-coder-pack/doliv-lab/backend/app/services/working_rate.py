"""Office working USDT/RUB rate — admin-owned snapshot."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, WorkingRate, WorkingRateMode
from app.services.rapira import get_rapira_usdt_rub_rate


def _q(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


async def get_active_working_rate(db: AsyncSession) -> WorkingRate:
    result = await db.execute(select(WorkingRate).order_by(WorkingRate.id.desc()).limit(1))
    row = result.scalar_one_or_none()
    if row:
        return row
    # Bootstrap: Rapira snap so lab works before admin sets rate
    rate = await get_rapira_usdt_rub_rate()
    row = WorkingRate(
        rate=_q(rate),
        mode=WorkingRateMode.rapira_snap,
        comment="auto-bootstrap",
        set_by_id=None,
    )
    db.add(row)
    await db.flush()
    return row


async def require_active_rate_value(db: AsyncSession) -> Decimal:
    row = await get_active_working_rate(db)
    if row.mode == WorkingRateMode.fixed and row.valid_until is not None:
        now = datetime.now(timezone.utc)
        vu = row.valid_until
        if vu.tzinfo is None:
            vu = vu.replace(tzinfo=timezone.utc)
        if now > vu:
            raise HTTPException(
                400,
                "Working rate expired — admin must set a new office rate",
            )
    return _q(row.rate)


async def set_working_rate(
    db: AsyncSession,
    *,
    rate: Decimal,
    mode: WorkingRateMode,
    actor: User,
    valid_until: datetime | None = None,
    comment: str | None = None,
) -> WorkingRate:
    if rate <= 0:
        raise HTTPException(400, "rate must be > 0")
    row = WorkingRate(
        rate=_q(rate),
        mode=mode,
        valid_until=valid_until,
        comment=comment,
        set_by_id=actor.id,
    )
    db.add(row)
    await db.flush()
    return row


async def set_from_rapira(
    db: AsyncSession,
    *,
    actor: User,
    comment: str | None = None,
    valid_until: datetime | None = None,
) -> WorkingRate:
    rate = await get_rapira_usdt_rub_rate()
    mode = WorkingRateMode.fixed if valid_until else WorkingRateMode.rapira_snap
    return await set_working_rate(
        db,
        rate=rate,
        mode=mode,
        actor=actor,
        valid_until=valid_until,
        comment=comment or "Rapira snapshot",
    )
