"""Обработка ответа на графическую капчу в боте.

Флоу:
  1. start_handler отправляет картинку и сохраняет токен в context.user_data
  2. Пользователь отвечает текстом
  3. captcha_text_handler проверяет ответ
     - Верно  → captcha_passed_at = now(), запускает start
     - Неверно → отправляет новую картинку
"""
from __future__ import annotations

import io
import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.bot_captcha import generate_captcha_image, verify_captcha_answer
from services.db import set_captcha_passed

logger = logging.getLogger("captcha_handler")

CAPTCHA_TOKEN_KEY = "_captcha_token"  # nosec B105
CAPTCHA_REF_PAYLOAD_KEY = "_captcha_start_ref"


async def send_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправить новую картинку-капчу пользователю."""
    user = update.effective_user
    if not user:
        return

    png_bytes, token = generate_captcha_image()
    context.user_data[CAPTCHA_TOKEN_KEY] = token

    caption = (
        "🔐 <b>Проверка: решите пример</b>\n\n"
        "Напишите ответ следующим сообщением.\n"
        "Если картинка нечёткая — нажмите /start для новой."
    )
    await context.bot.send_photo(
        chat_id=user.id,
        photo=io.BytesIO(png_bytes),
        caption=caption,
        parse_mode="HTML",
    )


async def captcha_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработать текстовый ответ пользователя на капчу."""
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return

    token = context.user_data.get(CAPTCHA_TOKEN_KEY)
    if not token:
        return

    answer = update.message.text.strip()

    if verify_captcha_answer(token, answer):
        context.user_data.pop(CAPTCHA_TOKEN_KEY, None)
        await set_captcha_passed(user.id)
        await update.message.reply_text("✅ Проверка пройдена! Добро пожаловать.")

        ref_payload = context.user_data.pop(CAPTCHA_REF_PAYLOAD_KEY, None)
        if ref_payload:
            from services.user_referral_attribution import stash_pending_ref_token_from_payload

            await stash_pending_ref_token_from_payload(user.id, ref_payload)
        from services.user_referral_attribution import apply_pending_ref_token_if_any

        await apply_pending_ref_token_if_any(user.id)

        from handlers.start import start_handler
        try:
            await start_handler(update, context)
        except Exception as e:
            logger.warning("captcha: start_handler failed user=%s: %s", user.id, e)
    else:
        await update.message.reply_text(
            "❌ Неверно. Попробуйте ещё раз — отправьте новую картинку командой /start."
        )
        await send_captcha(update, context)
