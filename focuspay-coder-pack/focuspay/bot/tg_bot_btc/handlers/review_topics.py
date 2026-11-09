"""Register a forum group: /review_topics creates «VPN» and «Обмены»."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.config_rates import TELEGRAM_ADMIN_IDS
from services.review_topics import ReviewTopicsError, ensure_topics

logger = logging.getLogger("review_topics")


async def register_review_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user or not update.message:
        return
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text(
            "Команда только для группы. Канал отзывов темы не умеет: нужна группа с включёнными «Темами»."
        )
        return
    if update.effective_user.id not in TELEGRAM_ADMIN_IDS:
        return
    try:
        store = await ensure_topics(context.bot, chat.id)
    except ReviewTopicsError as exc:
        await update.message.reply_text(str(exc))
        return
    except Exception as exc:
        logger.warning("review topics create failed: %s", type(exc).__name__)
        await update.message.reply_text("Не удалось создать темы. Бот должен быть админом с правом управлять темами.")
        return
    await update.message.reply_text(
        "Темы готовы: VPN и Обмены.\n"
        f"VPN <code>{store['vpn']}</code> · Обмены <code>{store['exchange']}</code>\n\n"
        "Одобренный отзыв из канала копируется в свою тему и не смешивается с другим продуктом.",
        parse_mode="HTML",
    )
