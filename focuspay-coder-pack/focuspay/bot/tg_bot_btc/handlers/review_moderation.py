"""Callback модерации отзывов в ops-группе."""
from __future__ import annotations

import html

from telegram import Update
from telegram.ext import ContextTypes

from services import config_rates, runtime_settings
from services.callback_signatures import verify_review_submission_signature
from services.config_rates import TELEGRAM_ADMIN_IDS
from services.review_bonus import (
    ReviewBonusError,
    get_submission,
    notify_review_user,
    publish_bonus_rub,
    publish_submission,
    reject_submission,
    vpn_review_amounts,
)


async def review_moderation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()

    if not config_rates.is_ops_group_chat(query.message.chat_id):
        await query.answer("⛔ Только в ops-группе", show_alert=True)
        return
    if query.from_user.id not in TELEGRAM_ADMIN_IDS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    parts = (query.data or "").split(":")
    if len(parts) != 4 or parts[0] != "rev":
        await query.answer("❌ Неверные данные", show_alert=True)
        return

    action, sid_s, signature = parts[1], parts[2], parts[3]
    try:
        submission_id = int(sid_s)
    except ValueError:
        await query.answer("❌ Неверный ID", show_alert=True)
        return

    if not verify_review_submission_signature(submission_id, signature):
        await query.answer("🚨 Подделка запроса", show_alert=True)
        return

    admin_id = query.from_user.id
    sub = await get_submission(submission_id)
    product = (sub or {}).get("product") or "exchange"

    if action == "reject":
        sub = await reject_submission(submission_id, moderated_by=admin_id)
        if not sub:
            await query.answer("Уже обработано", show_alert=True)
            return
        await query.edit_message_reply_markup(reply_markup=None)
        product = sub.get("product") or "exchange"
        if product == "vpn":
            reject_text = (
                "ℹ️ Ваш отзыв не опубликован после проверки. "
                "Можете отправить новый в боте FocusVPN."
            )
        else:
            reject_text = (
                "ℹ️ Ваш отзыв не опубликован после проверки. "
                "Можете отправить новый через меню «Отзывы»."
            )
        await notify_review_user(context.bot, int(sub["user_id"]), reject_text, product)
        await query.message.reply_text(
            f"❌ Отзыв #{submission_id} отклонён (@{query.from_user.username or admin_id})"
        )
        return

    if action in ("pub50", "pub100"):
        vpn_text, vpn_photo = (25, 50)
        if product == "vpn":
            vpn_text, vpn_photo = await vpn_review_amounts()
        bonus = publish_bonus_rub(
            product,
            action,
            exchange_text=float(runtime_settings.review_bonus_text_rub()),
            exchange_photo=float(runtime_settings.review_bonus_photo_rub()),
            vpn_text=vpn_text,
            vpn_photo=vpn_photo,
        )
    else:
        await query.answer("❌ Неизвестное действие", show_alert=True)
        return

    try:
        result = await publish_submission(
            context.bot,
            submission_id,
            bonus_rub=bonus,
            moderated_by=admin_id,
        )
    except ReviewBonusError as e:
        await query.answer(str(e), show_alert=True)
        return
    except Exception:
        await query.answer("❌ Ошибка публикации", show_alert=True)
        return

    await query.edit_message_reply_markup(reply_markup=None)
    ch_url = html.escape(result["channel_url"])
    amount = result["amount_rub"]
    product = result.get("product") or product
    user_lines = [
        "✅ <b>Ваш отзыв одобрен и опубликован!</b>",
        f'📢 <a href="{ch_url}">Канал отзывов</a>',
        f'🌐 <a href="{html.escape(result["site_url"])}">Сайт</a>',
    ]
    if amount > 0:
        user_lines.insert(1, f"🎁 На баланс: <b>{amount:g} ₽</b>")
    elif result.get("bonus_skipped_weekly_limit"):
        user_lines.insert(1, "ℹ️ Бонус за отзыв VPN уже был на этой неделе — повторная выплата не выдаётся.")
    elif result.get("bonus_skipped_daily_limit"):
        user_lines.insert(1, "ℹ️ Бонус за отзыв сегодня уже начислялся — повторная выплата не выдаётся.")
    await notify_review_user(context.bot, int(result["user_id"]), "\n".join(user_lines), product)
    bonus_note = f"+{int(amount)} ₽" if amount else "без бонуса"
    await query.message.reply_text(
        f"✅ Отзыв #{submission_id} опубликован ({bonus_note})"
    )
