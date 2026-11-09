"""Маркетинговые дополнения после PAID и прогресс кешбэка."""
from __future__ import annotations

from services.https_fetch import https_read_json_async

import html
import os

from services import config_rates, runtime_settings
from services.cashback_tier import tier_info
from services.db import get_completed_orders_count
from services.referral_share import resolve_share_links
from services.review_invite_content import (
    review_invite_reply_markup_dict,
    review_invite_text,
)
from services.focusbet_link import (
    focusbet_invite_text,
    focusbet_keyboard,
    focusbet_reply_markup_dict,
)


async def cashback_progress_line(user_id: int) -> str | None:
    completed = await get_completed_orders_count(user_id)
    info = tier_info(completed)
    pct = info["percent"]
    until = int(info["exchanges_until_next_tier"] or 0)
    if until <= 0:
        return f"🎁 Кешбэк: <b>{pct:g}%</b> — максимальный уровень"
    return (
        f"🎁 Кешбэк: <b>{pct:g}%</b> · ещё <b>{until}</b> "
        f"обмен(ов) до +{info['tier_step_percent']:g}%"
    )


async def focus_lucky_progress_line(user_id: int) -> str | None:
    from services.raffle_db import get_active_campaigns, get_user_snapshot
    from services.db import get_pool

    campaigns = await get_active_campaigns()
    if not campaigns:
        return None
    pool = await get_pool()
    parts: list[str] = []
    async with pool.acquire() as conn:
        for campaign in campaigns:
            snap = await get_user_snapshot(campaign["id"], user_id, conn)
            if snap["tickets_total"] <= 0:
                continue
            kind = "недельный" if str(campaign.get("kind") or "") == "weekly" else "месячный"
            parts.append(
                f"🍀 FocusLucky ({kind}): <b>{snap['tickets_total']}</b> билетиков · "
                f"шанс <b>{snap['win_chance_label']}</b>"
            )
    if not parts:
        return None
    return "\n".join(parts)


async def send_post_paid_focus_lucky(user_id: int, *, bot=None) -> None:
    """Сообщение после PAID о новых билетах FocusLucky."""
    import json
    import logging
    import urllib.request

    from services.raffle_db import get_active_campaigns, get_user_snapshot
    from services.db import get_pool

    logger = logging.getLogger("marketing_messages")
    campaigns = await get_active_campaigns()
    if not campaigns:
        return

    pool = await get_pool()
    lines: list[str] = []
    async with pool.acquire() as conn:
        for campaign in campaigns:
            snap = await get_user_snapshot(campaign["id"], user_id, conn)
            if snap["tickets_total"] <= 0:
                continue
            kind = "недельный" if str(campaign.get("kind") or "") == "weekly" else "месячный"
            lines.append(
                f"🎟 {kind}: <b>{snap['tickets_total']}</b> билетиков · "
                f"шанс <b>{snap['win_chance_label']}</b>"
            )

    if not lines:
        return

    text = "\n".join(lines) + "\n🍀 FocusLucky"

    async def _send(b):
        await b.send_message(chat_id=int(user_id), text=text, parse_mode="HTML")

    if bot:
        try:
            await _send(bot)
            return
        except Exception as e:
            logger.warning("focus lucky (bot): %s", e)

    try:
        from services.bot_context import get_bot

        app_bot = get_bot()
        if app_bot:
            await _send(app_bot)
            return
    except Exception as e:
        logger.warning("focus lucky (app bot): %s", e)

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
        await https_read_json_async(req, timeout=15)
    except Exception as e:
        logger.warning("focus lucky (http): %s", e)


async def post_paid_followup_text(user_id: int) -> str | None:
    """Второе сообщение после PAID: реферал + кешбэк."""
    lines: list[str] = []
    try:
        share = await resolve_share_links(user_id)
        link = share["telegram_link"]
        pct = float(runtime_settings.user_referral_pct())
        tier = runtime_settings.partner_tier_global()
        lines.append(
            f"👥 <b>Приведи друга</b> — получай ~<b>{pct:g}%</b> с его сделок "
            f"и лесенку с оплаты VPN "
            f"(+{float(tier['step_percent']):g}% за каждых {int(tier['every_n'])}, "
            f"макс. {float(tier['max_percent']):g}%):\n"
            f"{html.escape(link)}"
        )
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)
    cb = await cashback_progress_line(user_id)
    if cb:
        lines.append(cb)
    fl = await focus_lucky_progress_line(user_id)
    if fl:
        lines.append(fl)
    return "\n\n".join(lines) if lines else None


async def send_post_paid_review_invite(
    user_id: int,
    *,
    bot=None,
    order_id: str | None = None,
) -> None:
    """Отдельное сообщение после PAID: отзыв за бонус."""
    import json
    import logging
    import urllib.request

    from services.review_bonus import (
        ReviewBonusError,
        can_claim_review_bonus_today,
        remember_pending_review_order,
        resolve_review_order_id,
    )

    logger = logging.getLogger("marketing_messages")
    try:
        eligible_oid = await resolve_review_order_id(user_id, order_id)
    except ReviewBonusError:
        return
    remember_pending_review_order(user_id, eligible_oid)
    text = review_invite_text()
    if not await can_claim_review_bonus_today(user_id):
        text += (
            "\n\n<i>Бонус сегодня уже начислялся — "
            "отзыв всё равно можно оставить (без повторного начисления).</i>"
        )
    kb_dict = review_invite_reply_markup_dict()

    async def _send_via_bot(b):
        from services.review_bonus import review_invite_keyboard

        await b.send_message(
            chat_id=int(user_id),
            text=text,
            parse_mode="HTML",
            reply_markup=review_invite_keyboard(),
        )

    if bot:
        try:
            await _send_via_bot(bot)
            return
        except Exception as e:
            logger.warning("review invite (bot): %s", e)

    try:
        from services.bot_context import get_bot

        app_bot = get_bot()
        if app_bot:
            await _send_via_bot(app_bot)
            return
    except Exception as e:
        logger.warning("review invite (app bot): %s", e)

    token = (config_rates.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        logger.warning("review invite: no TELEGRAM_BOT_TOKEN")
        return
    payload = json.dumps(
        {
            "chat_id": int(user_id),
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": kb_dict,
        }
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        body = await https_read_json_async(req, timeout=15)
        if not body.get("ok"):
            logger.warning("review invite (http): %s", body)
    except Exception as e:
        logger.warning("review invite (http): %s", e)


async def send_post_paid_focusbet(user_id: int, *, bot=None) -> None:
    """Последнее сообщение после PAID: ссылка в бота FocusBet."""
    import json
    import logging
    import urllib.request

    logger = logging.getLogger("marketing_messages")
    text = focusbet_invite_text()
    kb_dict = focusbet_reply_markup_dict()

    async def _send_via_bot(b):
        await b.send_message(
            chat_id=int(user_id),
            text=text,
            reply_markup=focusbet_keyboard(),
            disable_web_page_preview=True,
        )

    if bot:
        try:
            await _send_via_bot(bot)
            return
        except Exception as e:
            logger.warning("focusbet (bot): %s", e)

    try:
        from services.bot_context import get_bot

        app_bot = get_bot()
        if app_bot:
            await _send_via_bot(app_bot)
            return
    except Exception as e:
        logger.warning("focusbet (app bot): %s", e)

    token = (config_rates.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        logger.warning("focusbet: no TELEGRAM_BOT_TOKEN")
        return
    payload = json.dumps(
        {
            "chat_id": int(user_id),
            "text": text,
            "reply_markup": kb_dict,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        body = await https_read_json_async(req, timeout=15)
        if not body.get("ok"):
            logger.warning("focusbet (http): %s", body)
    except Exception as e:
        logger.warning("focusbet (http): %s", e)


async def send_post_paid_marketing(user_id: int, *, bot=None) -> None:
    text = await post_paid_followup_text(user_id)
    if not text:
        return
    if bot:
        try:
            await bot.send_message(chat_id=int(user_id), text=text, parse_mode="HTML")
            return
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
    try:
        from services.bot_context import get_bot

        app_bot = get_bot()
        if app_bot:
            await app_bot.send_message(chat_id=int(user_id), text=text, parse_mode="HTML")
            return
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)
    import json
    import urllib.request

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
        await https_read_json_async(req, timeout=15)
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)
