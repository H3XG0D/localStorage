"""Автоприём заявок на вступление в новости FocusPay (только пользователи бота)."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.config_rates import TELEGRAM_ADMIN_IDS, is_news_chat
from services.db import get_bot_user
from services.news_join_actions import (
    bot_news_start_url,
    notify_news_channels_limit,
    try_approve_news_join,
)

logger = logging.getLogger("news_join_request")


def is_eligible_for_news(
    user_id: int,
    *,
    bot_user_row,
    admin_ids: frozenset[int] | None = None,
) -> bool:
    """Пропуск в новости: админ или есть запись в bot_users (/start)."""
    admins = admin_ids if admin_ids is not None else frozenset(TELEGRAM_ADMIN_IDS)
    if int(user_id) in admins:
        return True
    return bot_user_row is not None


def _pending_join_message(bot_username: str | None) -> tuple[str, InlineKeyboardMarkup]:
    bot_name = (bot_username or "focuspay1_bot").lstrip("@")
    start_url = bot_news_start_url(bot_username)
    text = (
        "📢 <b>Заявка в новости FocusPay</b>\n\n"
        f"Чтобы вступить, сначала запустите бота @{bot_name} и нажмите <b>Start</b>.\n\n"
        "Ваша заявка <b>сохранена</b> — после Start вступление подтвердится автоматически."
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Запустить бота", url=start_url)]]
    )
    return text, keyboard


async def news_join_request_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    req = update.chat_join_request
    if not req or not req.from_user or not req.chat:
        return
    if not is_news_chat(req.chat.id):
        return

    user = req.from_user
    user_id = int(user.id)
    logger.info(
        "news join request user=%s chat=%s",
        user_id,
        req.chat.id,
    )
    bot_user = await get_bot_user(user_id)

    if is_eligible_for_news(user_id, bot_user_row=bot_user):
        result = await try_approve_news_join(
            context.bot,
            user_id,
            chat_id=req.chat.id,
        )
        if result == "channels_blocked":
            dm_chat = int(req.user_chat_id or user_id)
            await notify_news_channels_limit(context.bot, dm_chat)
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
            "news join pending user=%s chat=%s (not in bot_users, notified)",
            user_id,
            req.chat.id,
        )
    except Exception as e:
        logger.warning(
            "news join pending DM failed user=%s chat=%s: %s",
            user_id,
            req.chat.id,
            e,
        )
