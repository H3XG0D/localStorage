"""Обработка висящих заявок на вступление в канал отзывов FocusPay."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from telegram import Bot
from telegram.error import BadRequest, Forbidden, RetryAfter

from services.config_rates import TELEGRAM_ADMIN_IDS, reviews_chat_id
from services.db import get_bot_user_ids
from services.reviews_join_actions import try_approve_reviews_join

logger = logging.getLogger("reviews_join_sync")

_SKIP_ERRORS = frozenset(
    {
        "hide_requester_missing",
        "user_already_participant",
        "user_not_found",
        "invalid user_id",
        "user is deactivated",
    }
)


@dataclass
class ReviewsJoinSyncResult:
    checked: int = 0
    approved: int = 0
    skipped: int = 0
    channels_blocked: int = 0
    errors: int = 0


def _is_skip_error(exc: BadRequest) -> bool:
    msg = str(exc).lower()
    return any(token in msg for token in _SKIP_ERRORS)


def _resolve_gid(chat_id: int | str | None) -> int | str:
    gid = chat_id if chat_id is not None and chat_id != 0 else reviews_chat_id()
    if not gid:
        raise ValueError("reviews chat_id не задан")
    return gid


async def sync_reviews_join_requests(
    bot: Bot,
    *,
    chat_id: int | str | None = None,
    user_ids: list[int] | None = None,
    delay_sec: float = 0.04,
    notify_on_channels_limit: bool = True,
) -> ReviewsJoinSyncResult:
    """
    Пробегает bot_users (+ админы) и пытается approve висящие заявки в отзывы.
    Telegram не отдаёт список pending — только approveChatJoinRequest по user_id.
    """
    gid = _resolve_gid(chat_id)

    ids = {int(x) for x in (user_ids or []) if int(x) > 0}
    if not ids:
        raw = await get_bot_user_ids()
        ids.update(int(x) for x in raw if int(x) > 0)
        ids.update(int(x) for x in TELEGRAM_ADMIN_IDS if int(x) > 0)

    result = ReviewsJoinSyncResult()
    for user_id in sorted(ids):
        result.checked += 1
        outcome = await try_approve_reviews_join(
            bot,
            user_id,
            chat_id=gid,
            notify_on_channels_limit=notify_on_channels_limit,
        )
        if outcome == "approved":
            result.approved += 1
            logger.info("reviews sync approved user=%s chat=%s", user_id, gid)
        elif outcome == "channels_blocked":
            result.channels_blocked += 1
        elif outcome == "no_request":
            result.skipped += 1
        else:
            result.errors += 1

        if delay_sec > 0:
            await asyncio.sleep(delay_sec)

    logger.info(
        "reviews sync done chat=%s checked=%s approved=%s channels_blocked=%s skipped=%s errors=%s",
        gid,
        result.checked,
        result.approved,
        result.channels_blocked,
        result.skipped,
        result.errors,
    )
    return result


async def decline_reviews_join_requests(
    bot: Bot,
    *,
    chat_id: int | str | None = None,
    user_ids: list[int],
    delay_sec: float = 0.04,
) -> tuple[int, int]:
    """Отклонить заявки по user_id (для висящих без /start). Возвращает (declined, errors)."""
    gid = _resolve_gid(chat_id)

    bot_name = (bot.username or "focuspay1_bot").lstrip("@")
    declined = 0
    errors = 0
    for user_id in sorted({int(x) for x in user_ids if int(x) > 0}):
        while True:
            try:
                ok = await bot.decline_chat_join_request(chat_id=gid, user_id=user_id)
                if ok:
                    declined += 1
                    text = (
                        "❌ Заявка в канал отзывов FocusPay отклонена.\n\n"
                        f"Сначала запустите бота @{bot_name} и нажмите <b>Start</b>, "
                        "затем снова подайте заявку на вступление."
                    )
                    try:
                        await bot.send_message(
                            chat_id=user_id, text=text, parse_mode="HTML"
                        )
                    except Exception:
                        logger.debug("ignored non-fatal error", exc_info=True)
                else:
                    errors += 1
                break
            except RetryAfter as e:
                await asyncio.sleep(float(e.retry_after) + 0.5)
            except BadRequest as e:
                if _is_skip_error(e):
                    break
                errors += 1
                logger.warning(
                    "reviews decline failed user=%s chat=%s: %s",
                    user_id,
                    gid,
                    e,
                )
                break
            except Forbidden:
                break
        if delay_sec > 0:
            await asyncio.sleep(delay_sec)
    return declined, errors
