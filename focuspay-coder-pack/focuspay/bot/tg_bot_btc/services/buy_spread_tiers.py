"""Amount-based buy spread grid. Empty → caller uses scalar buy_spread_auto_pct."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

PCT_MIN = 0.0
PCT_MAX = 50.0


@dataclass(frozen=True)
class BuySpreadTier:
    min_amount_rub: float
    pct: float


def _as_finite_float(value: object, *, label: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{label} is required")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if result != result or result == float("inf") or result == float("-inf"):
        raise ValueError(f"{label} must be a finite number")
    return result


def parse_buy_spread_auto_tiers_patch(raw: object | None) -> tuple[BuySpreadTier, ...]:
    """PATCH /pricing-settings: grid required, first min = 0, increasing mins."""
    tiers = parse_buy_spread_auto_tiers(raw, strict=True)
    if not tiers:
        raise ValueError("buy_spread_auto_tiers must not be empty")
    return tiers


def parse_buy_spread_auto_tiers(raw: object | None, *, strict: bool = True) -> tuple[BuySpreadTier, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except (TypeError, ValueError) as exc:
            if strict:
                raise ValueError("buy_spread_auto_tiers must be a list") from exc
            return ()
    if not isinstance(raw, list):
        if strict:
            raise ValueError("buy_spread_auto_tiers must be a list")
        return ()
    if not raw:
        return ()
    try:
        tiers = [_parse_tier_row(item) for item in raw]
    except ValueError:
        if strict:
            raise
        return ()
    ordered = sorted(tiers, key=lambda tier: tier.min_amount_rub)
    if abs(ordered[0].min_amount_rub) > 1e-9:
        if strict:
            raise ValueError("buy_spread_auto_tiers must start at min_amount_rub = 0")
        return ()
    seen: set[float] = set()
    prev = -1.0
    for tier in ordered:
        key = round(tier.min_amount_rub, 2)
        if key in seen:
            if strict:
                raise ValueError("buy_spread_auto_tiers min_amount_rub values must be unique")
            return ()
        seen.add(key)
        if prev >= 0 and tier.min_amount_rub <= prev:
            if strict:
                raise ValueError("buy_spread_auto_tiers min_amount_rub values must increase")
            return ()
        prev = tier.min_amount_rub
    return tuple(ordered)


def _parse_tier_row(item: object) -> BuySpreadTier:
    if not isinstance(item, Mapping):
        raise ValueError("Each buy spread tier must be an object")
    min_amount = _as_finite_float(
        item.get("min_amount_rub", item.get("min_wager_rub", 0)),
        label="min_amount_rub",
    )
    pct = _as_finite_float(item.get("pct", item.get("percent")), label="pct")
    if min_amount < 0:
        raise ValueError("min_amount_rub must be >= 0")
    if pct < PCT_MIN or pct > PCT_MAX:
        raise ValueError("pct must be between 0 and 50")
    return BuySpreadTier(min_amount_rub=min_amount, pct=pct)


def resolve_buy_spread_pct(
    tiers: Sequence[BuySpreadTier],
    amount_rub: float | int | None,
    *,
    fallback_pct: float,
) -> float:
    if not tiers or amount_rub is None:
        return float(fallback_pct)
    try:
        amount = float(amount_rub)
    except (TypeError, ValueError):
        return float(fallback_pct)
    if amount != amount or amount < 0:
        return float(fallback_pct)
    chosen = tiers[0]
    for tier in tiers:
        if amount >= tier.min_amount_rub:
            chosen = tier
        else:
            break
    return float(chosen.pct)


def buy_spread_auto_tiers_to_public(tiers: Sequence[BuySpreadTier]) -> list[dict[str, float]]:
    return [{"min_amount_rub": t.min_amount_rub, "pct": t.pct} for t in tiers]


def buy_spread_range_label(tiers: Sequence[BuySpreadTier], *, fallback_pct: float) -> str:
    if not tiers:
        return f"{_fmt_pct(float(fallback_pct))}%"
    pcts = [tier.pct for tier in tiers]
    lo, hi = min(pcts), max(pcts)
    if abs(lo - hi) < 1e-9:
        return f"{_fmt_pct(lo)}%"
    return f"{_fmt_pct(lo)}–{_fmt_pct(hi)}%"


def _fmt_pct(pct: float) -> str:
    return f"{round(pct, 1):g}"
