"""Расписание кампании FocusLucky: 30 дней от старта до розыгрыша."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.raffle_constants import CAMPAIGN_DURATION_DAYS, DRAW_HOUR_MSK

MSK = timezone(timedelta(hours=3))


def campaign_schedule(
    start: datetime | None = None,
) -> tuple[datetime, datetime, datetime]:
    """
    starts_at — сейчас (или переданный момент),
    ends_at — за секунду до розыгрыша,
    draw_at — через CAMPAIGN_DURATION_DAYS, 20:00 МСК.
    """
    starts = start or datetime.now(MSK)
    if starts.tzinfo is None:
        starts = starts.replace(tzinfo=MSK)
    else:
        starts = starts.astimezone(MSK)

    draw_day = (starts + timedelta(days=CAMPAIGN_DURATION_DAYS)).date()
    draw_at = datetime(
        draw_day.year,
        draw_day.month,
        draw_day.day,
        DRAW_HOUR_MSK,
        0,
        0,
        tzinfo=MSK,
    )
    ends_at = draw_at - timedelta(seconds=1)
    return starts, ends_at, draw_at
