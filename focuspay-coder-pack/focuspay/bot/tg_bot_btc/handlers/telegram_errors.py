"""Глобальный error handler и fallback для неотвеченных callback_query."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

_GENERIC_CB_TEXT = "Не удалось выполнить действие. Попробуйте ещё раз."
_GENERIC_MSG_TEXT = "Не удалось обработать запрос. Нажмите «Профиль» ещё раз или /start."
_UNHANDLED_CB_TEXT = "Эта кнопка больше не действует. Откройте «Профиль» или /start."


async def answer_callback_safe(
    query,
    text: str = "",
    *,
    show_alert: bool = False,
) -> bool:
    """Всегда пытается закрыть Telegram spinner. False — если answer не прошёл."""
    if query is None:
        return False
    try:
        await query.answer(text or None, show_alert=show_alert)
        return True
    except Exception:
        logger.exception("answerCallbackQuery failed data=%r", getattr(query, "data", None))
        return False


def _chat_type(update: object) -> str | None:
    chat = getattr(update, "effective_chat", None) if update is not None else None
    if chat is None and update is not None:
        message = getattr(update, "effective_message", None)
        chat = getattr(message, "chat", None) if message else None
    return getattr(chat, "type", None) if chat else None


async def telegram_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("telegram handler error: %s", context.error)
    query = getattr(update, "callback_query", None) if update is not None else None
    if query:
        await answer_callback_safe(query, _GENERIC_CB_TEXT, show_alert=True)
        return
    if _chat_type(update) in ("group", "supergroup", "channel"):
        return
    message = getattr(update, "effective_message", None) if update is not None else None
    if message:
        try:
            await message.reply_text(_GENERIC_MSG_TEXT)
        except Exception:
            logger.exception("error handler reply_text failed")


async def unanswered_callback_fallback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query:
        return
    logger.warning("unhandled callback_data=%r", query.data)
    await answer_callback_safe(query, _UNHANDLED_CB_TEXT, show_alert=True)
