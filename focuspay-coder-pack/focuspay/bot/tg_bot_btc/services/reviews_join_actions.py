"""Общие действия с заявками на вступление в канал отзывов FocusPay."""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from telegram import Bot
from telegram.error import BadRequest, Forbidden, RetryAfter

from services.config_rates import reviews_chat_id

logger = logging.getLogger("reviews_join_actions")

ReviewsApproveResult = Literal["approved", "no_request", "channels_blocked", "error"]

_CHANNELS_TOO_MUCH = "user_channels_too_much"

_SKIP_ERRORS = frozenset(
    {
        "hide_requester_missing",
        "user_already_participant",
        "user_not_found",
        "invalid user_id",
        "user is deactivated",
    }
)


def bot_reviews_start_url(bot_username: str | None) -> str:
    name = (bot_username or "focuspay1_bot").lstrip("@")
    return f"https://t.me/{name}?start=reviews"


def _is_skip_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(token in msg for token in _SKIP_ERRORS)


def is_channels_too_much(exc: Exception) -> bool:
    return _CHANNELS_TOO_MUCH in str(exc).lower()


def _resolve_chat_id(chat_id: int | str | None) -> int | str:
    if chat_id is not None and chat_id != 0 and chat_id != "":
        return chat_id
    return reviews_chat_id()


async def notify_reviews_channels_limit(bot: Bot, chat_id: int) -> None:
    text = (
        "⚠️ Заявка в канал отзывов FocusPay не принята: у вас лимит групп/каналов в Telegram.\n\n"
        "Выйдите из нескольких чатов и снова подайте заявку на вступление."
    )
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logger.debug("reviews channels limit DM failed chat=%s: %s", chat_id, e)


async def try_approve_reviews_join(
    bot: Bot,
    user_id: int,
    *,
    chat_id: int | str | None = None,
    notify_on_channels_limit: bool = True,
) -> ReviewsApproveResult:
    gid = _resolve_chat_id(chat_id)
    if not gid or int(user_id) <= 0:
        return "no_request"

    while True:
        try:
            ok = await bot.approve_chat_join_request(chat_id=gid, user_id=int(user_id))
            if ok:
                logger.info("reviews join approved user=%s chat=%s", user_id, gid)
                return "approved"
            return "error"
        except RetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 0.5)
        except BadRequest as e:
            if _is_skip_error(e):
                return "no_request"
            if is_channels_too_much(e):
                logger.warning(
                    "reviews join approve blocked user=%s chat=%s: too many channels",
                    user_id,
                    gid,
                )
                if notify_on_channels_limit:
                    await notify_reviews_channels_limit(bot, int(user_id))
                return "channels_blocked"
            logger.warning(
                "reviews join approve failed user=%s chat=%s: %s",
                user_id,
                gid,
                e,
            )
            return "error"
        except Forbidden as e:
            if _is_skip_error(e):
                return "no_request"
            logger.warning(
                "reviews join approve forbidden user=%s chat=%s: %s",
                user_id,
                gid,
                e,
            )
            return "no_request"
