"""Процент комиссии для UI."""
from __future__ import annotations

from buy_spread_tiers import buy_spread_range_label
from runtime_settings import (
    buy_spread_auto_tiers_from,
    buy_spread_pct,
    get_settings_sync,
    sell_client_pct,
)


def commission_percent(
    crypto: str,
    direction: str,
    *,
    manual: bool = False,
    amount_rub: float | int | None = None,
) -> float:
    del crypto
    if direction == "buy":
        return round(buy_spread_pct(manual=manual, amount_rub=amount_rub), 1)
    return round(sell_client_pct(), 1)


def commission_label(
    crypto: str,
    direction: str,
    *,
    manual: bool = False,
    amount_rub: float | int | None = None,
) -> str:
    if direction == "buy" and amount_rub is None and not manual:
        s = get_settings_sync()
        return buy_spread_range_label(
            buy_spread_auto_tiers_from(s),
            fallback_pct=float(s["buy_spread_auto_pct"]),
        )
    return f"{commission_percent(crypto, direction, manual=manual, amount_rub=amount_rub):g}%"
