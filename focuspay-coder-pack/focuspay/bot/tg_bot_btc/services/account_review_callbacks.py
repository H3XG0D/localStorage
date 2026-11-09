"""Callback ручной проверки аккаунта до реквизитов."""
from __future__ import annotations

import html

from telegram import Update
from telegram.ext import ContextTypes

from services import config_rates
from services.account_review import (
    approve_account_review,
    reject_account_review,
    soft_block_account_review,
)
from services.callback_signatures import verify_account_review_signature
from services.config_rates import TELEGRAM_ADMIN_IDS


async def account_review_callback_handler(
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
    # areview:ok|soft|no:123:sig
    if len(parts) != 4 or parts[0] != "areview":
        await query.answer("❌ Неверные данные", show_alert=True)
        return

    action, uid_raw, signature = parts[1], parts[2], parts[3]
    if action not in ("ok", "no", "soft"):
        await query.answer("❌ Неизвестное действие", show_alert=True)
        return
    try:
        user_id = int(uid_raw)
    except ValueError:
        await query.answer("❌ Неверный user_id", show_alert=True)
        return

    if not verify_account_review_signature(user_id, signature):
        await query.answer("🚨 Подделка запроса", show_alert=True)
        return

    operator_id = query.from_user.id
    op_label = html.escape(query.from_user.username or str(operator_id))

    if action == "ok":
        ok, err = await approve_account_review(user_id, operator_id)
        if not ok:
            await query.answer(err or "Не удалось одобрить", show_alert=True)
            return
        await query.answer("Одобрено (клиенту не пишем)")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"✅ Аккаунт <code>{user_id}</code> одобрен — реки можно выдавать "
            f"(@{op_label}, клиенту не писали)",
            parse_mode="HTML",
        )
        return

    if action == "soft":
        ok, err = await soft_block_account_review(user_id, operator_id)
        if not ok:
            await query.answer(err or "Не удалось заблокировать", show_alert=True)
            return
        await query.answer("Тихий блок — реквизиты закрыты")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"🔇 Тихий блок <code>{user_id}</code>: реквизиты не выдаются, "
            f"клиент видит «нет реквизитов» (@{op_label})",
            parse_mode="HTML",
        )
        return

    ok, err = await reject_account_review(
        user_id, operator_id, ban=True, ban_type="hard"
    )
    if not ok:
        await query.answer(err or "Не удалось отклонить", show_alert=True)
        return
    await query.answer("Хард-бан")
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        f"❌ Хард-бан <code>{user_id}</code> (@{op_label}, клиенту не писали)",
        parse_mode="HTML",
    )
