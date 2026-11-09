"""Promo campaign attribution (parity with tg_bot_btc/services/db.py)."""
from __future__ import annotations

import asyncio
import logging

from db import get_pool

logger = logging.getLogger("promo_attribution")


async def get_active_promo_campaign_by_ref_token(ref_token: str):
    token = (ref_token or "").strip().lower()
    if not token:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT id, code, name, bonus_percent, ad_spend_rub, is_active, created_by,
                   ref_token, campaign_kind, client_fixed_bonus_rub, created_at, updated_at
            FROM promo_campaigns
            WHERE ref_token = $1 AND is_active = TRUE
            LIMIT 1
            """,
            token,
        )


async def get_active_promo_campaign_by_code(code: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT id, code, name, bonus_percent, ad_spend_rub, is_active, created_by,
                   ref_token, campaign_kind, client_fixed_bonus_rub, created_at, updated_at
            FROM promo_campaigns
            WHERE code = $1 AND is_active = TRUE
            LIMIT 1
            """,
            code,
        )


async def assign_promo_to_user_if_first(user_id: int, promo_code: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            campaign = await conn.fetchrow(
                """
                SELECT max_activations, campaign_kind FROM promo_campaigns
                WHERE code = $1 AND is_active = TRUE
                FOR UPDATE
                """,
                promo_code,
            )
            if not campaign:
                return False
            kind = (campaign.get("campaign_kind") or "").lower()
            if kind != "partner":
                max_act = int(campaign["max_activations"] or 5)
                used = int(
                    await conn.fetchval(
                        "SELECT COUNT(*)::int FROM promo_attributions WHERE promo_code = $1",
                        promo_code,
                    )
                    or 0
                )
                if used >= max_act:
                    return False
            result = await conn.execute(
                """
                INSERT INTO promo_attributions (user_id, promo_code, assigned_at)
                VALUES ($1, $2, now())
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id,
                promo_code,
            )
            applied = result.endswith("1")
            is_partner = kind == "partner"
        if applied and is_partner:
            try:
                from partner_tier_notify import maybe_notify_tier_upgrade

                asyncio.create_task(maybe_notify_tier_upgrade(promo_code))
            except Exception as e:
                logger.debug("tier notify skipped: %s", e)
        return applied
