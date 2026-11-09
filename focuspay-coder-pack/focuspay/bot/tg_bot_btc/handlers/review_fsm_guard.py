"""Приоритетный хендлер FSM отзыва — не даёт кнопкам меню перехватывать ввод."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes, filters

from handlers.review_bonus import _is_review_image_message
from services.antispam import rate_limit_ok


async def review_fsm_priority_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message or not context.user_data.get("awaiting_review"):
        return
    if not await rate_limit_ok(update):
        raise ApplicationHandlerStop

    if _is_review_image_message(update.message):
        from handlers.review_bonus import review_photo_handler

        await review_photo_handler(update, context)
    else:
        from handlers.review_bonus import review_message_handler

        await review_message_handler(update, context)
    raise ApplicationHandlerStop


REVIEW_FSM_PRIVATE_FILTER = (
    filters.ChatType.PRIVATE
    & (filters.TEXT | filters.PHOTO | filters.Document.IMAGE)
    & ~filters.COMMAND
)
