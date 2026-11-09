from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LoginFailure

_RATE_WINDOW_SECONDS = 60
_MAX_FAILURES = 10


async def check_login_rate_limit(db: AsyncSession, rate_key: str) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=_RATE_WINDOW_SECONDS)
    count = (
        await db.execute(
            select(func.count(LoginFailure.id)).where(
                LoginFailure.rate_key == rate_key,
                LoginFailure.failed_at >= cutoff,
            )
        )
    ).scalar() or 0
    if count >= _MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
        )
    await db.execute(delete(LoginFailure).where(LoginFailure.failed_at < cutoff - timedelta(hours=1)))
    await db.flush()


async def record_login_failure(db: AsyncSession, rate_key: str) -> None:
    db.add(LoginFailure(rate_key=rate_key[:128]))
    await db.flush()
