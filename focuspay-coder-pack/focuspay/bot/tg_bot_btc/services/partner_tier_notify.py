"""Telegram notifications when partner commission % changes."""
from __future__ import annotations

from services.https_fetch import https_urlopen

import json
import logging
import urllib.request

from services import config_rates
from services.db import get_pool
from services.partner_tier import resolve_tier_settings, tier_info
from services.runtime_settings import partner_tier_global, refresh_settings

logger = logging.getLogger("partner_tier_notify")

COMMISSION_BASIS = "чистой прибыли сервиса"


def format_rate_change_message(
    *,
    new_percent: float,
    refs: int,
    tier_after: dict,
    old_percent: float | None = None,
    reason: str = "tier",
) -> str:
    """HTML message for Telegram DM."""
    if old_percent is not None and abs(old_percent - new_percent) >= 0.01:
        head = (
            f"📈 <b>Ставка изменилась:</b> {old_percent:g}% → <b>{new_percent:g}%</b>\n"
            f"Начисление: <b>{new_percent:g}%</b> с {COMMISSION_BASIS} по каждой оплаченной сделке ваших клиентов."
        )
    else:
        head = (
            f"📈 <b>Ставка повышена!</b> Теперь <b>{new_percent:g}%</b> с {COMMISSION_BASIS} "
            f"по каждой оплаченной сделке ваших клиентов."
        )

    lines = [head, f"\nПриведено клиентов: <b>{refs}</b>"]

    if tier_after.get("at_max_tier"):
        lines.append("Вы на максимальном уровне программы.")
    else:
        nxt = tier_after.get("next_tier_percent")
        until = tier_after.get("refs_until_next_tier", 0)
        if nxt is not None:
            lines.append(f"До {nxt:g}%: ещё <b>{until}</b> реф.")

    if reason == "admin":
        lines.append("\n<i>Ставку обновил администратор.</i>")

    lines.append(f"\n📊 Кабинет: {config_rates.PUBLIC_SITE_URL.rstrip('/')}/partner/login")
    return "\n".join(lines)


async def send_partner_dm(user_id: int, text: str) -> None:
    try:
        from services.bot_context import get_bot

        bot = get_bot()
        if bot:
            await bot.send_message(chat_id=int(user_id), text=text, parse_mode="HTML")
            return
    except Exception as e:
        logger.warning("partner notify (bot): %s", e)

    token = (config_rates.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        return
    payload = json.dumps(
        {"chat_id": int(user_id), "text": text, "parse_mode": "HTML"}
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with https_urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
        if not body.get("ok"):
            logger.warning("partner notify (http): %s", body)
    except Exception as e:
        logger.warning("partner notify (http): %s", e)


async def notify_partner_rate_change(
    telegram_user_id: int,
    *,
    old_percent: float,
    new_percent: float,
    refs: int,
    tier_after: dict,
    reason: str = "tier",
) -> None:
    if abs(old_percent - new_percent) < 0.01:
        return
    text = format_rate_change_message(
        new_percent=new_percent,
        old_percent=old_percent,
        refs=refs,
        tier_after=tier_after,
        reason=reason,
    )
    await send_partner_dm(telegram_user_id, text)
    logger.info(
        "partner rate notify tg=%s %.2f->%.2f refs=%s reason=%s",
        telegram_user_id,
        old_percent,
        new_percent,
        refs,
        reason,
    )


async def maybe_notify_tier_upgrade(promo_code: str) -> None:
    """If effective % rose after latest promo_attribution, DM the partner."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT pc.*, pa.telegram_user_id
            FROM promo_campaigns pc
            JOIN partner_accounts pa ON pa.promo_campaign_id = pc.id
            WHERE pc.code = $1 AND pc.campaign_kind = 'partner'
            """,
            promo_code,
        )
        if not row or not row["telegram_user_id"]:
            return

        await refresh_settings()
        global_tier = partner_tier_global()
        settings = resolve_tier_settings(global_tier, dict(row))
        refs = int(
            await conn.fetchval(
                "SELECT COUNT(*)::int FROM promo_attributions WHERE promo_code = $1",
                promo_code,
            )
            or 0
        )
        if refs < 1:
            return

        after = tier_info(refs, settings)
        before = tier_info(refs - 1, settings)
        if after["effective_percent"] <= before["effective_percent"]:
            return

        await notify_partner_rate_change(
            int(row["telegram_user_id"]),
            old_percent=float(before["effective_percent"]),
            new_percent=float(after["effective_percent"]),
            refs=refs,
            tier_after=after,
            reason="tier",
        )


# backwards compat for partner_auto_upgrade
_send_dm = send_partner_dm
