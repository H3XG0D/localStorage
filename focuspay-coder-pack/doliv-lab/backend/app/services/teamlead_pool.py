"""Teamlead margin pool: traders get a share; TL keeps the remainder."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSettings, User, UserRole, Zaliv


def _q(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def resolve_pool_percent(tl: User, settings: AppSettings | None) -> Decimal:
    """teamlead_percent on TL user = margin pool (admin-set)."""
    if tl.teamlead_percent is not None:
        return Decimal(tl.teamlead_percent)
    if settings and settings.default_teamlead_percent is not None:
        return Decimal(settings.default_teamlead_percent)
    return Decimal("12")


async def get_teamlead_pool(db: AsyncSession, teamlead_id: int | None) -> Decimal | None:
    if not teamlead_id:
        return None
    tl = await db.get(User, teamlead_id)
    if not tl or tl.role != UserRole.teamlead:
        return None
    settings = await db.get(AppSettings, 1)
    return resolve_pool_percent(tl, settings)


async def assert_trader_percent_within_pool(
    db: AsyncSession,
    *,
    profit_percent: Decimal,
    teamlead_id: int | None,
) -> None:
    if teamlead_id is None:
        return
    pool = await get_teamlead_pool(db, teamlead_id)
    if pool is None:
        return
    if profit_percent > pool:
        raise HTTPException(
            400,
            f"Trader profit_percent {profit_percent}% exceeds teamlead pool {pool}%",
        )


def calc_teamlead_keep_usdt(
    zalivs: list[Zaliv],
    *,
    pool: Decimal,
    target_rate: Decimal,
) -> Decimal:
    """TL share = Σ amount * (pool - stamped%) / 100 / target_rate."""
    if target_rate <= 0 or pool < 0:
        return Decimal("0")
    total = Decimal("0")
    for z in zalivs:
        keep = pool - Decimal(z.profit_percent)
        if keep <= 0:
            continue
        total += Decimal(z.amount) * keep / Decimal("100") / target_rate
    return _q(total)
