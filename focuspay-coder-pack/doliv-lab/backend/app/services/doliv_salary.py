"""Per-dolivshchik fixed salary rate (USDT per completed doliv)."""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSettings, User

DEFAULT_DOLIV_SALARY_USDT = Decimal("1")


async def resolve_doliv_salary_usdt(db: AsyncSession, user: User) -> Decimal:
    """Return the fixed USDT rate per completed doliv for a dolivshchik."""
    if user.doliv_salary_usdt is not None:
        return user.doliv_salary_usdt
    settings = await db.get(AppSettings, 1)
    if settings and settings.doliv_salary_percent is not None:
        return settings.doliv_salary_percent
    return DEFAULT_DOLIV_SALARY_USDT
