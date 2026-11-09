"""Payment corridor (band) helpers for trader cards."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException


def _q(v: Decimal) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_bands(raw: list | None) -> list[dict[str, str]] | None:
    """Validate and normalize bands to JSON-serializable dicts. Empty → None."""
    if not raw:
        return None
    out: list[dict[str, str]] = []
    for item in raw:
        if hasattr(item, "min_rub"):
            lo, hi = _q(item.min_rub), _q(item.max_rub)
        else:
            lo = _q(Decimal(str(item.get("min_rub", item.get("min")))))
            hi = _q(Decimal(str(item.get("max_rub", item.get("max")))))
        if lo <= 0 or hi <= 0:
            raise HTTPException(400, "payment band amounts must be > 0")
        if lo > hi:
            raise HTTPException(400, f"payment band min {lo} > max {hi}")
        out.append({"min_rub": str(lo), "max_rub": str(hi)})
    return out or None


def bands_minmax(bands: list[dict] | None) -> tuple[Decimal | None, Decimal | None]:
    if not bands:
        return None, None
    lows = [_q(Decimal(str(b["min_rub"]))) for b in bands]
    highs = [_q(Decimal(str(b["max_rub"]))) for b in bands]
    return min(lows), max(highs)


def amount_in_bands(amount: Decimal, bands: list[dict] | None) -> bool:
    if not bands:
        return True
    amount = _q(amount)
    for b in bands:
        lo = _q(Decimal(str(b["min_rub"])))
        hi = _q(Decimal(str(b["max_rub"])))
        if lo <= amount <= hi:
            return True
    return False


def assert_zaliv_payment_allowed(
    amount: Decimal,
    *,
    bands: list[dict] | None,
    min_payment_rub: Decimal | None,
    max_payment_rub: Decimal | None,
    remaining_capacity: Decimal,
) -> None:
    if remaining_capacity <= 0:
        raise HTTPException(400, "Daily limit exhausted — accepting is off")
    if amount > remaining_capacity:
        raise HTTPException(
            400,
            f"Zaliv amount {amount} exceeds remaining capacity {remaining_capacity:.2f} ₽",
        )
    if bands:
        if not amount_in_bands(amount, bands):
            raise HTTPException(400, "Zaliv amount outside payment corridors")
        return
    if min_payment_rub is not None and amount < min_payment_rub:
        raise HTTPException(
            400,
            f"Zaliv amount {amount} below min payment {min_payment_rub} ₽",
        )
    if max_payment_rub is not None and amount > max_payment_rub:
        raise HTTPException(
            400,
            f"Zaliv amount {amount} exceeds max payment {max_payment_rub} ₽",
        )
