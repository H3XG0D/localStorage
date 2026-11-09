"""После сообщения клиента — отдельное сообщение с web_app-кнопкой казино.

Отдельная поздняя группа: хендлеры обмена отрабатывают первыми, а это сообщение
уходит последним, иначе список чатов не покажет «ОТКРЫТЬ» на мини-приложение.
"""
from __future__ import annotations

import logging
import time

from telegram import Update
from telegram.ext import ContextTypes

from services.menu import send_casino_open_prompt

logger = logging.getLogger("casino_open_prompt")

# Кнопка на каждое слово — спам: одно напоминание в сутки на пользователя.
PROMPT_COOLDOWN_SEC = 24 * 60 * 60
LAST_PROMPT_KEY = "casino_open_prompt_at"

# Пока клиент внутри сценария (сумма, реквизиты, промокод, отзыв, вывод рефералки),
# лишнее сообщение сбивает шаг и прячет reply-клавиатуру.
BUSY_FLAGS = ("step", "awaiting_review", "uref_wd", "promo_enter")


def _is_busy(user_data: dict) -> bool:
    return any(user_data.get(flag) for flag in BUSY_FLAGS)


def _cooldown_passed(user_data: dict, now: float) -> bool:
    last = user_data.get(LAST_PROMPT_KEY)
    if not isinstance(last, (int, float)):
        return True
    return now - last >= PROMPT_COOLDOWN_SEC


async def casino_open_prompt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None or chat.type != chat.PRIVATE:
        return

    user_data = context.user_data
    if user_data is None or _is_busy(user_data):
        return

    now = time.time()
    if not _cooldown_passed(user_data, now):
        return

    try:
        sent = await send_casino_open_prompt(context.bot, chat.id)
    except Exception:
        logger.exception("casino open prompt failed chat=%s", chat.id)
        return

    if sent:
        user_data[LAST_PROMPT_KEY] = now
