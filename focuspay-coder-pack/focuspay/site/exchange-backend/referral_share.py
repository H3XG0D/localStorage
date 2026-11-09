"""Единый источник правды: какую реферальную ссылку показывать пользователю."""
from __future__ import annotations

from config import settings
from db import get_pool
from referral_links import (
    telegram_deep_link,
    web_onion_ref_link,
    web_ref_link,
)


async def _partner_share_row(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT pa.*, pc.code AS campaign_code, pc.ref_token
            FROM partner_accounts pa
            JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
            WHERE pa.is_active = TRUE
              AND pc.is_active = TRUE
              AND pa.telegram_user_id = $1
            LIMIT 1
            """,
            user_id,
        )


async def resolve_share_links(user_id: int) -> dict:
    """
    Единая реферальная ссылка для всех: всегда ref_ + /ref/{token}.
    Один токен на пользователя (parity с ботом).
    """
    from user_referral_db import get_canonical_ref_token

    partner = await _partner_share_row(user_id)
    site = settings.public_site_url.rstrip("/")
    token = await get_canonical_ref_token(user_id)
    return {
        "kind": "partner" if partner else "user",
        "ref_token": token,
        "telegram_link": telegram_deep_link(token),
        "web_link": web_ref_link(token, site),
        "onion_web_link": web_onion_ref_link(token),
    }


async def ensure_promo_attribution_for_partner_referrer(
    conn,
    referred_user_id: int,
    referrer_user_id: int,
) -> bool:
    """Если реферер — партнёр, дублируем атрибуцию в promo_attributions."""
    row = await conn.fetchrow(
        """
        SELECT pc.code AS promo_code
        FROM partner_accounts pa
        JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
        WHERE pa.telegram_user_id = $1
          AND pa.is_active = TRUE
          AND pc.is_active = TRUE
        LIMIT 1
        """,
        referrer_user_id,
    )
    if not row:
        return False
    result = await conn.execute(
        """
        INSERT INTO promo_attributions (user_id, promo_code, assigned_at)
        VALUES ($1, $2, now())
        ON CONFLICT (user_id) DO NOTHING
        """,
        referred_user_id,
        row["promo_code"],
    )
    return result.endswith("1")
