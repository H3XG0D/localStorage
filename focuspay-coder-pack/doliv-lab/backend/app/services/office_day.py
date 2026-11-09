"""Office calendar day bounds from AppSettings.timezone."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSettings


async def day_start_utc(db: AsyncSession) -> datetime:
    settings = await db.get(AppSettings, 1)
    tz_name = (settings.timezone if settings else None) or "Europe/Moscow"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Europe/Moscow")
    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc)
