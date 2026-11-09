"""Настраиваемые сетки казино: кешбек и комиссия по недельному обороту ставок."""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from casino_finance import whole_percent

MONEY_STEP = Decimal("0.01")


@dataclass(frozen=True)
class CashbackVolumeTier:
    min_wager_rub: Decimal
    percent: Decimal


@dataclass(frozen=True)
class CommissionVolumeTier:
    min_wager_rub: Decimal
    active_rate: Decimal
    complete_rate: Decimal


@dataclass(frozen=True)
class CasinoTierConfig:
    cashback_volume_tiers: tuple[CashbackVolumeTier, ...]
    commission_volume_tiers: tuple[CommissionVolumeTier, ...]


DEFAULT_CASHBACK_VOLUME_TIERS: tuple[CashbackVolumeTier, ...] = (
    CashbackVolumeTier(Decimal("0"), Decimal("2")),
    CashbackVolumeTier(Decimal("50000"), Decimal("5")),
    CashbackVolumeTier(Decimal("100000"), Decimal("7")),
    CashbackVolumeTier(Decimal("200000"), Decimal("10")),
    CashbackVolumeTier(Decimal("500000"), Decimal("15")),
)

DEFAULT_COMMISSION_VOLUME_TIERS: tuple[CommissionVolumeTier, ...] = (
    CommissionVolumeTier(Decimal("0"), Decimal("15"), Decimal("5")),
    CommissionVolumeTier(Decimal("50000"), Decimal("12"), Decimal("4")),
    CommissionVolumeTier(Decimal("100000"), Decimal("10"), Decimal("3")),
    CommissionVolumeTier(Decimal("200000"), Decimal("8"), Decimal("2.5")),
)


def _money(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("Invalid money value")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid money value") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid money value")
    return result.quantize(MONEY_STEP)


def _parse_tier_rows(raw: object) -> list[Mapping[str, Any]]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        raise ValueError("Tier grid must be a list")
    rows: list[Mapping[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("Each tier row must be an object")
        rows.append(item)
    return rows


def parse_cashback_volume_tiers(raw: object | None) -> tuple[CashbackVolumeTier, ...]:
    if raw is None:
        return DEFAULT_CASHBACK_VOLUME_TIERS
    tiers: list[CashbackVolumeTier] = []
    for row in _parse_tier_rows(raw):
        tiers.append(
            CashbackVolumeTier(
                min_wager_rub=_money(row.get("min_wager_rub", 0)),
                percent=whole_percent(row.get("percent", 0)),
            )
        )
    return _normalize_cashback_tiers(tiers)


def parse_commission_volume_tiers(raw: object | None) -> tuple[CommissionVolumeTier, ...]:
    if raw is None:
        return DEFAULT_COMMISSION_VOLUME_TIERS
    tiers: list[CommissionVolumeTier] = []
    for row in _parse_tier_rows(raw):
        active_rate = whole_percent(row.get("active_rate", row.get("commission_rate_wagering_active", 0)))
        complete_rate = whole_percent(row.get("complete_rate", row.get("commission_rate_wagering_complete", 0)))
        tiers.append(
            CommissionVolumeTier(
                min_wager_rub=_money(row.get("min_wager_rub", 0)),
                active_rate=active_rate,
                complete_rate=complete_rate,
            )
        )
    return _normalize_commission_tiers(tiers)


def _normalize_cashback_tiers(tiers: Sequence[CashbackVolumeTier]) -> tuple[CashbackVolumeTier, ...]:
    if not tiers:
        raise ValueError("Cashback tier grid cannot be empty")
    ordered = sorted(tiers, key=lambda tier: tier.min_wager_rub)
    if ordered[0].min_wager_rub != Decimal("0"):
        raise ValueError("Cashback tier grid must start at min_wager_rub = 0")
    seen: set[Decimal] = set()
    for tier in ordered:
        if tier.min_wager_rub in seen:
            raise ValueError("Cashback tier min_wager_rub values must be unique")
        seen.add(tier.min_wager_rub)
    return tuple(ordered)


def _normalize_commission_tiers(tiers: Sequence[CommissionVolumeTier]) -> tuple[CommissionVolumeTier, ...]:
    if not tiers:
        raise ValueError("Commission tier grid cannot be empty")
    ordered = sorted(tiers, key=lambda tier: tier.min_wager_rub)
    if ordered[0].min_wager_rub != Decimal("0"):
        raise ValueError("Commission tier grid must start at min_wager_rub = 0")
    seen: set[Decimal] = set()
    for tier in ordered:
        if tier.min_wager_rub in seen:
            raise ValueError("Commission tier min_wager_rub values must be unique")
        if tier.complete_rate > tier.active_rate:
            raise ValueError("Complete commission rate cannot exceed active rate in a tier row")
        seen.add(tier.min_wager_rub)
    return tuple(ordered)


def resolve_cashback_percent(
    tiers: Sequence[CashbackVolumeTier],
    wager_rub: Decimal | int | float | str,
) -> Decimal:
    wager = _money(wager_rub)
    selected = tiers[0]
    for tier in tiers:
        if wager >= tier.min_wager_rub:
            selected = tier
    return selected.percent


def resolve_commission_volume_tier(
    tiers: Sequence[CommissionVolumeTier],
    wager_rub: Decimal | int | float | str,
) -> CommissionVolumeTier:
    wager = _money(wager_rub)
    selected = tiers[0]
    for tier in tiers:
        if wager >= tier.min_wager_rub:
            selected = tier
    return selected


def next_cashback_tier(
    tiers: Sequence[CashbackVolumeTier],
    wager_rub: Decimal | int | float | str,
) -> CashbackVolumeTier | None:
    wager = _money(wager_rub)
    for tier in tiers:
        if wager < tier.min_wager_rub:
            return tier
    return None


def tier_config_from_settings(values: Mapping[str, object]) -> CasinoTierConfig:
    cashback_raw = values.get("cashback_volume_tiers")
    commission_raw = values.get("commission_volume_tiers")
    if isinstance(cashback_raw, str):
        cashback_raw = json.loads(cashback_raw)
    if isinstance(commission_raw, str):
        commission_raw = json.loads(commission_raw)
    return CasinoTierConfig(
        cashback_volume_tiers=parse_cashback_volume_tiers(cashback_raw),
        commission_volume_tiers=parse_commission_volume_tiers(commission_raw),
    )


async def load_tier_config(conn) -> CasinoTierConfig:
    rows = await conn.fetch(
        """
        SELECT key, value
        FROM casino_settings
        WHERE key = ANY($1::text[])
        """,
        ["cashback_volume_tiers", "commission_volume_tiers"],
    )
    values = {str(row["key"]): row["value"] for row in rows}
    return tier_config_from_settings(values)


def cashback_tiers_to_public(tiers: Sequence[CashbackVolumeTier]) -> list[dict[str, float]]:
    return [
        {"min_wager_rub": float(tier.min_wager_rub), "percent": float(tier.percent)}
        for tier in tiers
    ]


def commission_tiers_to_public(tiers: Sequence[CommissionVolumeTier]) -> list[dict[str, float]]:
    return [
        {
            "min_wager_rub": float(tier.min_wager_rub),
            "active_rate": float(tier.active_rate),
            "complete_rate": float(tier.complete_rate),
        }
        for tier in tiers
    ]
