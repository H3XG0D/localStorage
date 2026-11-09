"""Модерация отзывов в ops-группе."""
from __future__ import annotations

import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from services import config_rates, runtime_settings
from services.callback_signatures import sign_review_submission
from services.review_bonus import (
    _safe_vpn_photo,
    can_claim_review_bonus_today,
    exchange_review_has_telegram_source,
    get_submission,
    vpn_bonus_claimed_within_week,
    vpn_review_amounts,
)

logger = logging.getLogger("review_moderation")


def _has_photo(sub: dict) -> bool:
    return bool(sub.get("source_photo_message_id") or sub.get("source_photo_path"))


def _bonus_pair(sub: dict) -> tuple[int, int]:
    if (sub.get("product") or "exchange") == "vpn":
        return int(sub.get("bonus_text_rub") or 25), int(sub.get("bonus_photo_rub") or 50)
    return (
        int(runtime_settings.review_bonus_text_rub()),
        int(runtime_settings.review_bonus_photo_rub()),
    )


def format_moderation_message(sub: dict) -> str:
    has_photo = _has_photo(sub)
    tier_label = "текст + скрин" if has_photo else "только текст"
    t50, t100 = _bonus_pair(sub)
    author = html.escape(sub.get("author_display") or f"id{sub['user_id']}")
    text = html.escape((sub.get("review_text") or "")[:500])
    oid = sub.get("order_id")
    vpn = (sub.get("product") or "exchange") == "vpn"
    title = "Отзыв VPN на модерацию" if vpn else "Отзыв на модерацию"
    lines = [
        f"📝 <b>{title}</b> #{sub['id']}",
        f"👤 {author} · <code>{sub['user_id']}</code>",
        f"📎 Формат: <b>{tier_label}</b> · бонус: {t50} ₽ / {t100} ₽",
    ]
    if vpn:
        lines.append("⏳ Бонус VPN — не чаще раза в 7 дней")
    elif not exchange_review_has_telegram_source(sub):
        lines.append("🌐 Источник: <b>сайт</b> · скрин не прикладывался")
    if oid:
        lines.append(f"🧾 Заявка: <code>{html.escape(str(oid))}</code>")
    lines.append(f"\n{text}")
    return "\n".join(lines)


def moderation_keyboard(sub: dict) -> InlineKeyboardMarkup:
    sid = int(sub["id"])
    sig = sign_review_submission(sid)
    t50, t100 = _bonus_pair(sub)
    rows = [
        [
            InlineKeyboardButton(
                f"✅ Опубликовать + {t50} ₽",
                callback_data=f"rev:pub50:{sid}:{sig}",
            ),
        ],
        [
            InlineKeyboardButton(
                f"✅ Опубликовать + {t100} ₽",
                callback_data=f"rev:pub100:{sid}:{sig}",
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ Не публиковать",
                callback_data=f"rev:reject:{sid}:{sig}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(rows)


async def send_moderation_request(bot, submission_id: int) -> None:
    sub = await get_submission(submission_id)
    if not sub:
        return
    ops_id = config_rates.ops_group_id()
    if not ops_id:
        logger.warning("TELEGRAM_OPS_GROUP_ID not set — review moderation skipped")
        return

    vpn = (sub.get("product") or "exchange") == "vpn"
    if vpn:
        text_rub, photo_rub = await vpn_review_amounts()
        sub = dict(sub)
        sub["bonus_text_rub"] = text_rub
        sub["bonus_photo_rub"] = photo_rub
        try:
            await bot.send_message(chat_id=ops_id, text=(sub.get("review_text") or "")[:4000])
            target = _safe_vpn_photo(sub.get("source_photo_path"))
            if target is not None:
                with target.open("rb") as fh:
                    await bot.send_photo(chat_id=ops_id, photo=fh)
        except Exception as e:
            logger.warning("vpn review preview to ops: %s", e)
    elif not exchange_review_has_telegram_source(sub):
        try:
            await bot.send_message(chat_id=ops_id, text=(sub.get("review_text") or "")[:4000])
        except Exception as e:
            logger.warning("site review preview to ops: %s", e)
    else:
        try:
            await bot.forward_message(
                chat_id=ops_id,
                from_chat_id=int(sub["source_text_chat_id"]),
                message_id=int(sub["source_text_message_id"]),
            )
            photo_mid = sub.get("source_photo_message_id")
            text_mid = sub.get("source_text_message_id")
            if photo_mid and int(photo_mid) != int(text_mid):
                await bot.forward_message(
                    chat_id=ops_id,
                    from_chat_id=int(sub["source_photo_chat_id"]),
                    message_id=int(photo_mid),
                )
        except Exception as e:
            logger.warning("forward review to ops: %s", e)

    bonus_hint = ""
    if vpn:
        if await vpn_bonus_claimed_within_week(int(sub["user_id"])):
            bonus_hint = "\n\n⚠️ <i>Бонус за отзыв VPN уже был на этой неделе — кнопки с ₽ не сработают.</i>"
    elif not await can_claim_review_bonus_today(int(sub["user_id"])):
        bonus_hint = "\n\n⚠️ <i>Бонус сегодня уже начислялся — кнопки с ₽ не сработают.</i>"

    card = await bot.send_message(
        chat_id=ops_id,
        text=format_moderation_message(sub) + bonus_hint,
        parse_mode="HTML",
        reply_markup=moderation_keyboard(sub),
    )

    from services.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE review_submissions
            SET moderation_chat_id = $2, moderation_message_id = $3
            WHERE id = $1
            """,
            submission_id,
            ops_id,
            card.message_id,
        )
