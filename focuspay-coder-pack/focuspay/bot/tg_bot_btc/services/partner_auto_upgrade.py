"""Auto-create partner cabinet after the first user-referral attribution."""
from __future__ import annotations

import logging

from services import config_rates
from services.db import get_pool
from services.partner_provisioning import (
    create_partner_in_tx,
    migrate_uref_attributions_to_promo,
    suggest_username,
)
from services.partner_tier import resolve_tier_settings, tier_info
from services.partner_tier_notify import _send_dm
from services.referral_links import telegram_deep_link, web_ref_link
from services.runtime_settings import partner_tier_global, refresh_settings

logger = logging.getLogger("partner_auto_upgrade")


async def _has_partner_account(telegram_user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return bool(
            await conn.fetchval(
                """
                SELECT 1 FROM partner_accounts
                WHERE telegram_user_id = $1 AND is_active = TRUE
                LIMIT 1
                """,
                telegram_user_id,
            )
        )


async def _referred_count(referrer_user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return int(
            await conn.fetchval(
                """
                SELECT COUNT(*)::int FROM user_referral_attributions
                WHERE referrer_user_id = $1
                """,
                referrer_user_id,
            )
            or 0
        )


async def _fetch_tg_username(user_id: int) -> str | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT username FROM bot_users WHERE user_id = $1",
            user_id,
        )


async def maybe_auto_upgrade_referrer(referrer_user_id: int) -> bool:
    """
    After first uref attribution: create partner cabinet, migrate attributions, DM credentials.
    Returns True if a new partner was created.
    """
    if await _has_partner_account(referrer_user_id):
        return False
    if await _referred_count(referrer_user_id) != 1:
        return False

    tg_username = await _fetch_tg_username(referrer_user_id)
    username = suggest_username(referrer_user_id, tg_username)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if await conn.fetchval(
                """
                SELECT 1 FROM partner_accounts
                WHERE telegram_user_id = $1 LIMIT 1
                """,
                referrer_user_id,
            ):
                return False

            created = await create_partner_in_tx(
                conn,
                username=username,
                telegram_user_id=referrer_user_id,
                created_by=None,
            )
            promo_code = created["promo_code"]
            await migrate_uref_attributions_to_promo(conn, referrer_user_id, promo_code)

    await refresh_settings()
    global_tier = partner_tier_global()
    settings = resolve_tier_settings(global_tier, created["campaign"])
    async with pool.acquire() as conn:
        refs = int(
            await conn.fetchval(
                "SELECT COUNT(*)::int FROM promo_attributions WHERE promo_code = $1",
                promo_code,
            )
            or 0
        )
    info = tier_info(refs, settings)
    ref_token = created["ref_token"]
    site = config_rates.PUBLIC_SITE_URL.rstrip("/")
    tg_link = telegram_deep_link(ref_token)
    web_link = web_ref_link(ref_token, site)
    login_url = f"{site}/partner/login"
    pwd = created["password_plain"]
    uname = created["username"]

    until = info["refs_until_next_tier"]
    eff = info["effective_percent"]
    step = settings["step_percent"]
    every_n = settings["every_n"]
    max_pct = settings["max_percent"]

    settings_url = f"{site}/partner/settings"

    text = (
        "🎉 <b>Вы привели первого клиента — открыт партнёрский кабинет!</b>\n\n"
        f"Логин: <code>{uname}</code>\n"
        f"Пароль: <code>{pwd}</code> <i>(показывается один раз)</i>\n"
        f"Кабинет: {login_url}\n\n"
        "🔐 <b>После входа обязательно:</b>\n"
        f"• смените пароль — {settings_url}\n"
        "• включите Google Authenticator в разделе «Безопасность»\n\n"
        "<b>Ваши ссылки:</b>\n"
        f"• Telegram: {tg_link}\n"
        f"• Сайт: {web_link}\n\n"
        f"💰 Сейчас: <b>{eff:g}%</b> с чистой прибыли сервиса по каждой оплаченной сделке клиента.\n"
        f"📈 Ставка растёт: +{step:g}% за каждых {every_n} приведённых (макс. {max_pct:g}%)."
    )
    if not info["at_max_tier"]:
        text += f" · до повышения: <b>{until}</b> реф."

    await _send_dm(referrer_user_id, text)

    from services.partner_tier_notify import maybe_notify_tier_upgrade

    await maybe_notify_tier_upgrade(promo_code)

    logger.info(
        "auto partner created user=%s username=%s code=%s",
        referrer_user_id,
        uname,
        promo_code,
    )
    return True
