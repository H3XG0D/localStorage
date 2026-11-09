"""Регистрация группы проверки клиентов: /client_review."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.config_rates import TELEGRAM_ADMIN_IDS
from services.client_review_group_store import write_client_review_group_id

logger = logging.getLogger(__name__)


async def register_client_review_group(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.effective_chat or not update.effective_user:
        return
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        if update.message:
            await update.message.reply_text("Команда только для группы с ботом.")
        return
    if update.effective_user.id not in TELEGRAM_ADMIN_IDS:
        return

    cid = chat.id
    title = chat.title or ""
    try:
        path = write_client_review_group_id(cid)
    except OSError as e:
        logger.error("write client review group id: %s", e)
        if update.message:
            await update.message.reply_text(f"Ошибка записи chat_id: {e}")
        return

    logger.warning(
        "TELEGRAM_CLIENT_REVIEW_GROUP_ID registered: %s title=%r file=%s",
        cid,
        title,
        path,
    )
    if update.message:
        await update.message.reply_text(
            f"✅ <b>Группа проверки клиентов</b>\n"
            f"<code>{cid}</code> · {title}\n\n"
            f"Сюда: проверка профиля и совпадение кошелька до реквизитов, "
            f"чеки с уровнем «ДОСКОНАЛЬНО».\n"
            f"Обычные выплаты остаются в ops-группе.\n\n"
            f"Файл: <code>{path}</code>\n"
            f"Или в .env: <code>TELEGRAM_CLIENT_REVIEW_GROUP_ID={cid}</code>",
            parse_mode="HTML",
        )

    try:
        await context.bot.send_message(
            chat_id=cid,
            text=(
                "🔔 Группа проверки клиентов подключена.\n"
                "Сюда приходят заявки на одобрение до выдачи реквизитов."
            ),
        )
    except Exception as e:
        logger.warning("client review group test ping failed: %s", e)
