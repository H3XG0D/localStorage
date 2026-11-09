"""Парсинг периода для /stats и /dash."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

PaidOrdersGetter = Callable[[], Awaitable[list[Any]]]


def parse_stats_period_arg(
    arg: str,
    *,
    get_paid_for_date: Callable[[date], Awaitable[list[Any]]],
    get_paid_for_days: Callable[[int], Awaitable[list[Any]]],
) -> tuple[PaidOrdersGetter, dict]:
    """
    Аргумент: число дней или DD.MM.YYYY.
    Возвращает (корутина без аргументов → список PAID, header_kw).
    """
    arg = (arg or "").strip()
    try:
        dt = datetime.strptime(arg, "%d.%m.%Y")
        date_obj = dt.date()
        date_label = dt.strftime("%d.%m.%Y")

        async def _get_orders_date(d: date = date_obj) -> list[Any]:
            return await get_paid_for_date(d)

        return _get_orders_date, {"date_label": date_label, "by_date": True}
    except ValueError:
        pass

    try:
        days = int(arg) if arg else 1
        if days < 1:
            days = 1
        if days > 365:
            days = 365
    except ValueError:
        days = 1

    async def _get_orders_days(n: int = days) -> list[Any]:
        return await get_paid_for_days(n)

    if days % 10 == 1 and days % 100 != 11:
        period, last_word = "день", "последний"
    elif days % 10 in (2, 3, 4) and days % 100 not in (12, 13, 14):
        period, last_word = "дня", "последние"
    else:
        period, last_word = "дней", "последние"
    return _get_orders_days, {
        "days": days,
        "period": period,
        "last_word": last_word,
        "by_date": False,
    }
