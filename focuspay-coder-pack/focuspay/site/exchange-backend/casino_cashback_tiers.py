"""Политика недельного кешбека казино по настраиваемой сетке оборота."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Final

from casino_tier_config import (
    DEFAULT_CASHBACK_VOLUME_TIERS,
    CashbackVolumeTier,
    load_tier_config,
    resolve_cashback_percent,
)

MONEY_STEP: Final = Decimal("0.01")
PERCENT_DIVISOR: Final = Decimal("100")

# Совместимость со старым upper-bound API в тестах/импортах.
CASHBACK_TIERS: Final = tuple(
    (tier.min_wager_rub, tier.percent) for tier in DEFAULT_CASHBACK_VOLUME_TIERS
)


def money(value: Decimal | int | float | str) -> Decimal:
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return amount.quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def cashback_percent_for_wager(
    total_wager_rub: Decimal | int | float | str,
    tiers: tuple[CashbackVolumeTier, ...] | None = None,
) -> Decimal:
    """Вернуть процент кешбека для недельного объёма ставок."""
    total_wager = money(total_wager_rub)
    if total_wager < 0:
        raise ValueError("Total wager cannot be negative")
    return resolve_cashback_percent(tiers or DEFAULT_CASHBACK_VOLUME_TIERS, total_wager)


async def cashback_percent_for_wager_conn(conn, total_wager_rub: Decimal | int | float | str) -> Decimal:
    tiers = (await load_tier_config(conn)).cashback_volume_tiers
    return cashback_percent_for_wager(total_wager_rub, tiers)


def cashback_amount(
    total_wager_rub: Decimal | int | float | str,
    eligible_loss_rub: Decimal | int | float | str,
    tiers: tuple[CashbackVolumeTier, ...] | None = None,
) -> Decimal:
    eligible_loss = money(eligible_loss_rub)
    if eligible_loss < 0:
        raise ValueError("Eligible loss cannot be negative")
    percent = cashback_percent_for_wager(total_wager_rub, tiers)
    return money(eligible_loss * percent / PERCENT_DIVISOR)


async def cashback_amount_conn(
    conn,
    total_wager_rub: Decimal | int | float | str,
    eligible_loss_rub: Decimal | int | float | str,
) -> Decimal:
    tiers = (await load_tier_config(conn)).cashback_volume_tiers
    return cashback_amount(total_wager_rub, eligible_loss_rub, tiers)


def cashback_percent_for_loss(net_loss_rub: Decimal | int | float | str) -> Decimal:
    return cashback_percent_for_wager(net_loss_rub)


def cashback_amount_for_loss(net_loss_rub: Decimal | int | float | str) -> Decimal:
    return cashback_amount(net_loss_rub, net_loss_rub)
