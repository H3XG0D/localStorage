"""Реферальный кабинет: баланс, статистика, ссылка."""
import logging

from services import config_rates, runtime_settings
from services.db import get_pool
from services.referral_links import generate_ref_token

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
    """
    Единый реферальный токен пользователя — один на все каналы (бот, сайт, кабинет).

    Для партнёра каноном является promo_campaigns.ref_token (совпадает с
    bot_users.ref_token после миграции синхронизации). Для обычного пользователя —
    bot_users.ref_token (создаётся лениво, если ещё нет).
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
        "balance_rub": bal,
        "available_rub": max(0.0, bal - pend),
        "pending_withdraw_rub": pend,
        "referred_count": int(referred or 0),
        "paid_orders_count": int(paid_orders or 0),
        "today_accrual_rub": float(today or 0),
        "total_accrual_rub": float(total_accrued or 0),
    }


async def format_referral_cabinet_message(user_id: int, username: str | None) -> str:
    from services.partner_db import get_partner_by_telegram

    partner = await get_partner_by_telegram(user_id, username)
    if partner:
        from services.partner_db import format_partner_cabinet_text, get_partner_stats

        stats = await get_partner_stats(
            partner["campaign_id"], partner["campaign_code"], dict(partner)
        )
        return format_partner_cabinet_text(partner, stats)

    from services.referral_share import resolve_share_links

    share = await resolve_share_links(user_id)
    link = share["telegram_link"]
    stats = await get_referral_stats(user_id)
    from services.user_unified_balance import get_unified_balance_stats

    unified = await get_unified_balance_stats(user_id)
    pct = runtime_settings.user_referral_pct()
    await runtime_settings.refresh_settings()
    tier = runtime_settings.partner_tier_global()

    from services.ux_copy import txt_referral_cabinet

    return txt_referral_cabinet(
        pct=pct,
        tier_step=float(tier["step_percent"]),
        tier_every=int(tier["every_n"]),
        tier_max=float(tier["max_percent"]),
        referred=int(stats["referred_count"]),
        paid_orders=int(stats["paid_orders_count"]),
        today_rub=float(stats["today_accrual_rub"]),
        total_rub=float(stats["total_accrual_rub"]),
        balance_rub=float(unified["balance_rub"]),
        cashback_rub=float(unified["cashback_rub"]),
        referral_rub=float(unified["referral_rub"]),
        partner_rub=float(unified.get("partner_balance_rub") or 0),
        available_rub=float(unified["available_rub"]),
        pending_withdraw=float(stats["pending_withdraw_rub"]),
        link=link,
        withdraw_footer=await _withdraw_terms_footer(),
    )


async def _withdraw_terms_footer() -> str:
    from services.crypto_network_fee import format_withdraw_terms_html

    return await format_withdraw_terms_html(compact=True)


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
