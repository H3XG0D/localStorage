"""Уровни кешбэка: +step% за каждые N завершённых обменов, до max%."""
from services import runtime_settings


def _settings() -> tuple[float, float, int, float]:
    return (
        runtime_settings.user_cashback_base_pct(),
        runtime_settings.user_cashback_tier_step_pct(),
        runtime_settings.user_cashback_tier_every_n(),
        runtime_settings.user_cashback_max_pct(),
    )


def percent_for_completed_count(completed: int) -> float:
    base, step, every_n, max_pct = _settings()
    tiers = completed // every_n if every_n > 0 else 0
    return min(max_pct, base + tiers * step)


def tier_info(completed: int) -> dict:
    base, step, every_n, max_pct = _settings()
    pct = percent_for_completed_count(completed)
    at_max = pct >= max_pct - 1e-9
    if at_max:
        until = 0
    else:
        next_boundary = ((completed // every_n) + 1) * every_n
        until = max(0, next_boundary - completed)
    return {
        "percent": round(pct, 2),
        "percent_base": base,
        "percent_max": max_pct,
        "tier_step_percent": step,
        "exchanges_per_tier": every_n,
        "completed_exchanges": completed,
        "exchanges_until_next_tier": until,
    }


async def count_completed_exchanges(conn, user_id: int) -> int:
    val = await conn.fetchval(
        """
        SELECT COUNT(*)::int FROM orders
        WHERE user_id = $1 AND status IN ('PAID', 'COMPLETED')
        """,
        user_id,
    )
    return int(val or 0)
