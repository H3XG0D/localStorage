"""Реферальный кабинет пользователя (parity с ботом)."""
import logging

from db import get_pool
from config import settings
from referral_links import generate_ref_token

logger = logging.getLogger("user_referral_db")


async def get_or_create_ref_token(user_id: int) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT ref_token FROM bot_users WHERE user_id = $1",
            user_id,
        )
        if row and row["ref_token"]:
            return row["ref_token"]
        for _ in range(5):
            token = generate_ref_token()
            try:
                await conn.execute(
                    "UPDATE bot_users SET ref_token = $1 WHERE user_id = $2",
                    token,
                    user_id,
                )
                return token
            except Exception:
                logger.debug("ref_token collision, retry", exc_info=True)
    raise RuntimeError("Could not allocate ref_token")


async def get_canonical_ref_token(user_id: int) -> str:
    """Единый реферальный токен — один на все каналы (parity с ботом).

    Для партнёра каноном является promo_campaigns.ref_token (совпадает с
    bot_users.ref_token после миграции). Для обычного пользователя —
    bot_users.ref_token (создаётся лениво).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        partner_token = await conn.fetchval(
            """
            SELECT pc.ref_token
            FROM partner_accounts pa
            JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
            WHERE pa.telegram_user_id = $1
              AND pa.is_active = TRUE
              AND pc.is_active = TRUE
            LIMIT 1
            """,
            user_id,
        )
    if partner_token:
        return partner_token
    return await get_or_create_ref_token(user_id)


async def fetch_user_referrer(conn, user_id: int) -> dict | None:
    """Кто пригласил пользователя (первая uref-атрибуция)."""
    row = await conn.fetchrow(
        """
        SELECT a.referrer_user_id, a.created_at, u.username, u.first_name
        FROM user_referral_attributions a
        LEFT JOIN bot_users u ON u.user_id = a.referrer_user_id
        WHERE a.user_id = $1
        """,
        user_id,
    )
    if not row:
        return None
    created = row["created_at"]
    return {
        "user_id": int(row["referrer_user_id"]),
        "username": row.get("username"),
        "first_name": row.get("first_name"),
        "attributed_at": created.isoformat() if hasattr(created, "isoformat") else created,
    }


async def get_referral_stats(user_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        balance = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM user_referral_ledger WHERE referrer_user_id = $1
            """,
            user_id,
        )
        pending = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM user_referral_withdrawals
            WHERE referrer_user_id = $1 AND status = 'pending'
            """,
            user_id,
        )
        referred = await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM user_referral_attributions
            WHERE referrer_user_id = $1
            """,
            user_id,
        )
        paid_orders = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT o.order_id)::int
            FROM user_referral_attributions a
            JOIN orders o ON o.user_id = a.user_id AND o.status = 'PAID'
            WHERE a.referrer_user_id = $1
            """,
            user_id,
        )
        today = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM user_referral_ledger
            WHERE referrer_user_id = $1 AND type = 'accrual'
              AND created_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
            """,
            user_id,
        )
        total_accrued = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM user_referral_ledger
            WHERE referrer_user_id = $1 AND type = 'accrual'
            """,
            user_id,
        )

    bal = float(balance or 0)
    pend = float(pending or 0)
    return {
        "balance_rub": round(bal, 2),
        "available_rub": round(max(0.0, bal - pend), 2),
        "pending_withdraw_rub": round(pend, 2),
        "referred_count": int(referred or 0),
        "paid_orders_count": int(paid_orders or 0),
        "today_accrual_rub": round(float(today or 0), 2),
        "total_accrual_rub": round(float(total_accrued or 0), 2),
    }


async def has_pending_withdrawal(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if await conn.fetchval(
            """
            SELECT 1 FROM user_referral_withdrawals
            WHERE referrer_user_id = $1
              AND status IN ('pending', 'reserved', 'sending')
            LIMIT 1
            """,
            user_id,
        ):
            return True
        campaign_id = await conn.fetchval(
            """
            SELECT pa.promo_campaign_id
            FROM partner_accounts pa
            JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
            WHERE pa.telegram_user_id = $1
              AND pa.is_active = TRUE
              AND pc.is_active = TRUE
            LIMIT 1
            """,
            user_id,
        )
        if not campaign_id:
            return False
        return bool(
            await conn.fetchval(
                """
                SELECT 1 FROM partner_withdrawals
                WHERE campaign_id = $1
                  AND status IN ('pending', 'reserved', 'sending')
                LIMIT 1
                """,
                campaign_id,
            )
        )


async def assign_referrer_if_first(user_id: int, ref_token: str) -> bool:
    token = (ref_token or "").strip().lower()
    if not token:
        return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        locked = await conn.fetchval(
            "SELECT referral_locked FROM bot_users WHERE user_id = $1",
            user_id,
        )
        if locked:
            return False
        referrer = await conn.fetchrow(
            "SELECT user_id FROM bot_users WHERE ref_token = $1",
            token,
        )
        if not referrer:
            return False
        referrer_id = int(referrer["user_id"])
        if referrer_id == user_id:
            return False
        result = await conn.execute(
            """
            INSERT INTO user_referral_attributions (user_id, referrer_user_id)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user_id,
            referrer_id,
        )
        if result.endswith("1"):
            from referral_share import ensure_promo_attribution_for_partner_referrer

            await ensure_promo_attribution_for_partner_referrer(conn, user_id, referrer_id)
    return result.endswith("1")


async def seal_referral_gate(user_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE bot_users
            SET referral_locked = TRUE,
                pending_ref_token = NULL
            WHERE user_id = $1
              AND referral_locked = FALSE
              AND pending_ref_token IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM user_referral_attributions WHERE user_id = $1
              )
              AND NOT EXISTS (
                  SELECT 1 FROM promo_attributions WHERE user_id = $1
              )
            """,
            user_id,
        )


async def get_referral_cabinet_payload(user_id: int) -> dict:
    from referral_share import resolve_share_links

    share = await resolve_share_links(user_id)
    stats = await get_referral_stats(user_id)
    import runtime_settings

    pct = runtime_settings.user_referral_pct()
    return {
        **stats,
        "percent": pct,
        "ref_token": share["ref_token"],
        "share_link_kind": share["kind"],
        "telegram_link": share["telegram_link"],
        "web_invite_link": share["web_link"],
        "onion_invite_link": share.get("onion_web_link"),
        "min_withdraw_card_rub": runtime_settings.min_withdraw_card_rub(),
        "min_withdraw_crypto_usd": settings.user_referral_min_withdraw_crypto_usd,
        "has_pending_withdrawal": await has_pending_withdrawal(user_id),
    }
