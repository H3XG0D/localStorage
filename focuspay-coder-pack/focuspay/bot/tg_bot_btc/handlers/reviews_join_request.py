"""Автоприём заявок на вступление в канал отзывов (только пользователи бота)."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.config_rates import TELEGRAM_ADMIN_IDS, is_reviews_chat
from services.db import get_bot_user
from services.reviews_join_actions import (
    bot_reviews_start_url,
    notify_reviews_channels_limit,
    try_approve_reviews_join,
)

logger = logging.getLogger("reviews_join_request")


def is_eligible_for_reviews(
    user_id: int,
    *,
    bot_user_row,
    admin_ids: frozenset[int] | None = None,
) -> bool:
    """Пропуск в отзывы: админ или есть запись в bot_users (/start)."""
    admins = admin_ids if admin_ids is not None else frozenset(TELEGRAM_ADMIN_IDS)
    if int(user_id) in admins:
        return True
    return bot_user_row is not None


def _pending_join_message(bot_username: str | None) -> tuple[str, InlineKeyboardMarkup]:
    bot_name = (bot_username or "focuspay1_bot").lstrip("@")
    start_url = bot_reviews_start_url(bot_username)
    text = (
        "📢 <b>Заявка в канал отзывов FocusPay</b>\n\n"
        f"Чтобы вступить, сначала запустите бота @{bot_name} и нажмите <b>Start</b>.\n\n"
        "Ваша заявка <b>сохранена</b> — после Start вступление подтвердится автоматически."
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Запустить бота", url=start_url)]]
    )
    return text, keyboard


async def reviews_join_request_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    req = update.chat_join_request
    if not req or not req.from_user or not req.chat:
        return
    username = getattr(req.chat, "username", None)
    if not is_reviews_chat(req.chat.id, username=username):
        return

    user = req.from_user
    user_id = int(user.id)
    logger.info(
        "reviews join request user=%s chat=%s",
        user_id,
        req.chat.id,
    )
    bot_user = await get_bot_user(user_id)

    if is_eligible_for_reviews(user_id, bot_user_row=bot_user):
        result = await try_approve_reviews_join(
            context.bot,
            user_id,
            chat_id=req.chat.id,
        )
        if result == "channels_blocked":
            dm_chat = int(req.user_chat_id or user_id)
            await notify_reviews_channels_limit(context.bot, dm_chat)
        return

    text, keyboard = _pending_join_message(context.bot.username)
    dm_chat = int(req.user_chat_id or user_id)
    try:
        await context.bot.send_message(
            chat_id=dm_chat,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        logger.info(
            "reviews join pending user=%s chat=%s (not in bot_users, notified)",
            user_id,
            req.chat.id,
        )
    except Exception as e:
        logger.warning(
            "reviews join pending DM failed user=%s chat=%s: %s",
            user_id,
            req.chat.id,
            e,
        )
