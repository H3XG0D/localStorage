"""Shared helpers for partner tier accrual."""
from __future__ import annotations

from services.partner_tier import global_tier_from_runtime, resolve_tier_settings, tier_info
from services.runtime_settings import partner_tier_global, refresh_settings


async def campaign_tier_snapshot(conn, campaign_row: dict, promo_code: str) -> dict:
    await refresh_settings()
    global_tier = global_tier_from_runtime(partner_tier_global())
    settings = resolve_tier_settings(global_tier, dict(campaign_row))
    refs = int(
        await conn.fetchval(
            "SELECT COUNT(*)::int FROM promo_attributions WHERE promo_code = $1",
            promo_code,
        )
        or 0
    )
    info = tier_info(refs, settings)
    info["promo_code"] = promo_code
    return info
