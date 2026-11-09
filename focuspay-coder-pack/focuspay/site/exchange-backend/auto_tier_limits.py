"""Тиры лимитов автопилота по числу оплаченных BUY (фаза 4)."""
from __future__ import annotations

from runtime_settings import get_settings_sync


def auto_cap_rub_for_paid_count(paid_count: int, *, kind: str = "payout") -> int:
    """kind: payout | no_shift | withdraw — пока общая шкала."""
    _ = kind
    n = max(0, int(paid_count))
    settings = get_settings_sync()
    base = int(settings.get("auto_payout_max_rub") or 10_000)
    if not settings.get("auto_tier_limits_enabled"):
        return base
    if n >= 20:
        return max(base, 30_000)
    if n >= 10:
        return max(base, 15_000)
    if n >= 5:
        return max(base, 5_000)
    return base
