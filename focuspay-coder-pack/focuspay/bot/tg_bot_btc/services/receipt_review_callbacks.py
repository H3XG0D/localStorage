"""Callback проверки чека оператором перед Payfast."""
from __future__ import annotations

import html
import logging

from telegram import Update
from telegram.ext import ContextTypes

from services import config_rates
from services.callback_signatures import verify_receipt_review_signature
from services.config_rates import TELEGRAM_ADMIN_IDS
from services.receipt_ops_review import (
    approve_receipt_and_send_to_payfast,
    reject_receipt_ban_and_cancel,
)

logger = logging.getLogger("receipt_review_callbacks")


async def _safe_callback_answer(query, text: str, *, show_alert: bool = False) -> None:
    try:
        await query.answer(text, show_alert=show_alert)
    except Exception as exc:
        logger.debug("receipt callback answer failed: %s", exc)


async def _safe_callback_reply(query, text: str) -> None:
    try:
        await query.message.reply_text(text)
    except Exception:
        logger.exception("receipt callback result reply failed")


async def _safe_remove_callback_markup(query) -> None:
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        logger.debug("receipt callback markup removal failed", exc_info=True)


async def receipt_review_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query or not query.message:
        return

    chat_id = query.message.chat_id
    if not (
        config_rates.is_ops_group_chat(chat_id)
        or config_rates.is_client_review_group_chat(chat_id)
    ):
        await _safe_callback_answer(
            query, "⛔ Только в ops / проверке клиентов", show_alert=True
        )
        return
    if query.from_user.id not in TELEGRAM_ADMIN_IDS:
        await _safe_callback_answer(query, "⛔ Нет доступа", show_alert=True)
        return

    parts = (query.data or "").split(":")
    if len(parts) != 4 or parts[0] != "rcpt":
        await _safe_callback_answer(query, "❌ Неверные данные", show_alert=True)
        return

    action, order_id, signature = parts[1], parts[2], parts[3]
    if action not in ("approve", "reject"):
        await _safe_callback_answer(query, "❌ Неизвестное действие", show_alert=True)
        return

    if not verify_receipt_review_signature(order_id, signature):
        await _safe_callback_answer(query, "🚨 Подделка запроса", show_alert=True)
        return

    operator_id = query.from_user.id
    op_label = html.escape(query.from_user.username or str(operator_id))
    await _safe_callback_answer(query, "⏳ Обрабатываю чек…")

    try:
        if action == "approve":
            ok, err = await approve_receipt_and_send_to_payfast(
                order_id,
                operator_id,
                bot=context.bot,
            )
            if not ok:
                await _safe_callback_reply(
                    query,
                    f"⚠️ {err or 'Не удалось отправить чек в Payfast'}",
                )
                return
            await _safe_remove_callback_markup(query)
            await _safe_callback_reply(
                query, f"✅ Чек принят (@{op_label})"
            )
            return

        ok, err = await reject_receipt_ban_and_cancel(
            order_id,
            operator_id,
            bot=context.bot,
        )
        if not ok:
            await _safe_callback_reply(query, f"⚠️ {err or 'Уже обработано'}")
            return
        await _safe_remove_callback_markup(query)
        await _safe_callback_reply(
            query, f"❌ Заявка отменена, клиент заблокирован (@{op_label})"
        )
    except Exception:
        logger.exception("receipt review callback failed action=%s order=%s", action, order_id)
        await _safe_callback_reply(
            query,
            "⚠️ Ошибка обработки заявки. Повторите позже или сообщите оператору.",
        )
