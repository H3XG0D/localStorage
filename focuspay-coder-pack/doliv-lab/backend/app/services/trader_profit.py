"""Per-trader profit percent resolution and bulk recalculation."""

from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSettings, Requisite, RequisiteStatus, User, Zaliv

MIN_DOLIV_RATE = Decimal("50")
MAX_DOLIV_RATE = Decimal("200")
DEFAULT_PROFIT_PERCENT = Decimal("12")

_OPEN_STATUSES = (
    RequisiteStatus.active,
    RequisiteStatus.in_work,
    RequisiteStatus.awaiting_doliv,
    RequisiteStatus.doliv_in_progress,
)


def _normalize_doliv_rate(rate: Decimal, target_rate: Decimal) -> Decimal:
    if rate < MIN_DOLIV_RATE or rate > MAX_DOLIV_RATE:
        return target_rate
    return rate


async def resolve_trader_profit_percent(db: AsyncSession, user: User) -> Decimal:
    """Return the fixed profit percent for a trader."""
    if user.profit_percent is not None:
        return user.profit_percent
    settings = await db.get(AppSettings, 1)
    if settings and settings.default_profit_percent is not None:
        return settings.default_profit_percent
    return DEFAULT_PROFIT_PERCENT


async def apply_trader_profit_percent(
    db: AsyncSession,
    trader_id: int,
    new_percent: Decimal,
) -> tuple[int, int]:
    """Update profit_percent on open requisites only; closed deals are immutable.

    Returns (zalivs_updated, deal_results_updated).
    """
    open_requisite_ids = (
        await db.execute(
            select(Requisite.id).where(
                Requisite.trader_id == trader_id,
                Requisite.status.in_(_OPEN_STATUSES),
            )
        )
    ).scalars().all()

    zalivs_updated = 0
    if open_requisite_ids:
        result = await db.execute(
            update(Zaliv)
            .where(Zaliv.requisite_id.in_(open_requisite_ids))
            .values(profit_percent=new_percent)
        )
        zalivs_updated = result.rowcount or 0

    return zalivs_updated, 0
