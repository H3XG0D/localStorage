"""Callbacks device_review (fingerprint/IP) — отдельно от account_review."""
from __future__ import annotations

import html
import logging

from telegram import Update
from telegram.ext import ContextTypes

from services import config_rates
from services.callback_signatures import verify_device_review_signature
from services.config_rates import TELEGRAM_ADMIN_IDS
from services.db import ban_user, set_device_review_status

logger = logging.getLogger("device_review_callbacks")


async def device_review_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query or not query.message:
        return

    chat_id = query.message.chat_id
    if not (
        config_rates.is_client_review_group_chat(chat_id)
        or config_rates.is_ops_group_chat(chat_id)
    ):
        await query.answer("⛔ Только в группе проверки клиентов", show_alert=True)
        return
    if query.from_user.id not in TELEGRAM_ADMIN_IDS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    parts = (query.data or "").split(":")
    # dreview:ok|soft|no:123:sig
    if len(parts) != 4 or parts[0] != "dreview":
        await query.answer("❌ Неверные данные", show_alert=True)
        return
    action, uid_s, sig = parts[1], parts[2], parts[3]
    try:
        user_id = int(uid_s)
    except ValueError:
        await query.answer("❌ Неверный user_id", show_alert=True)
        return
    if not verify_device_review_signature(user_id, sig):
        await query.answer("❌ Подпись недействительна", show_alert=True)
        return

    op = query.from_user.id
    try:
        if action == "ok":
            await set_device_review_status(
                user_id, "approved", reason="ops_approved", operator_id=op
            )
            await query.answer("Устройство одобрено")
            note = "✅ Устройство одобрено (клиенту не пишем — пусть заново запросит реквизиты)"
        elif action == "soft":
            await set_device_review_status(
                user_id, "rejected", reason="ops_soft", operator_id=op
            )
            await ban_user(
                user_id, reason="device_review_soft", operator_id=op, ban_type="soft"
            )
            await query.answer("Тихий блок")
            note = "🔇 Тихий блок по устройству"
        elif action == "no":
            await set_device_review_status(
                user_id, "rejected", reason="ops_ban", operator_id=op
            )
            await ban_user(
                user_id, reason="device_review_ban", operator_id=op, ban_type="hard"
            )
            await query.answer("Бан")
            note = "❌ Бан по устройству"
        else:
            await query.answer("❌ Неизвестное действие", show_alert=True)
            return
    except Exception as e:
        logger.exception("device review failed action=%s user=%s", action, user_id)
        try:
            await query.answer(f"Ошибка: {e}"[:180], show_alert=True)
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
        return

    try:
        await query.edit_message_text(
            (query.message.text_html or query.message.text or "")
            + f"\n\n{note}\nОператор: <code>{op}</code>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        await query.message.reply_text(note, parse_mode="HTML")
