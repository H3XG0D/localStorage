"""Привязка топика «Смены» для уведомлений об открытии/закрытии смен."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.config_rates import TELEGRAM_ADMIN_IDS
from services.operator_shift_store import normalize_topic_id, write_operator_shift_target

logger = logging.getLogger("operator_shift_chat")


async def register_operator_shift_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.effective_chat or not update.effective_user or not update.message:
        return
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Команда только для группы с ботом.")
        return
    if update.effective_user.id not in TELEGRAM_ADMIN_IDS:
        await update.message.reply_text(
            "Только админ может привязать чат смен. "
            "Используйте /shift в нужном топике."
        )
        return

    topic_id = normalize_topic_id(getattr(update.message, "message_thread_id", None))
    try:
        path = write_operator_shift_target(chat.id, topic_id)
    except OSError as e:
        logger.error("write operator shift config: %s", e)
        await update.message.reply_text(f"Ошибка записи конфига: {e}")
        return

    title = chat.title or ""
    topic_line = f"\nТопик: <code>{topic_id}</code>" if topic_id else ""
    await update.message.reply_text(
        f"✅ <b>Чат смен</b>\n"
        f"<code>{chat.id}</code> · {title}{topic_line}\n\n"
        f"Сюда будут приходить уведомления: кто открыл/закрыл смену.\n"
        f"Файл: <code>{path}</code>",
        parse_mode="HTML",
    )
    logger.info(
        "operator shift chat registered chat_id=%s topic_id=%s file=%s",
        chat.id,
        topic_id,
        path,
    )
