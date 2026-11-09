"""Прибыль сервиса по сделке (до кешбэка/рефа в ledger)."""
from __future__ import annotations

from datetime import datetime, timezone

from economics_snapshot import order_economics


def utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def order_profit_rub(order: dict) -> float:
    return order_economics(order)["service_profit_rub"]


def earnings_from_profit(profit_rub: float, percent: float) -> float:
    return round(max(0.0, float(profit_rub)) * float(percent) / 100, 2)
