from __future__ import annotations

import logging

import telegram

from services.support_urls import telegram_web_url
from services.text_sanitize import sanitize_telegram_html, strip_html

logger = logging.getLogger(__name__)


def url_button(text: str, url: str | None) -> telegram.InlineKeyboardButton | None:
    """Inline URL-кнопка только если Bot API примет адрес."""
    safe = telegram_web_url(url)
    if not safe:
        return None
    return telegram.InlineKeyboardButton(text, url=safe)


_EDIT_FAIL_PLAIN = "Не удалось обновить сообщение."


def _is_not_modified(exc: BaseException) -> bool:
    return "message is not modified" in str(exc).lower()


async def edit_message_text_safe(
    edit_fn,
    text: str,
    *,
    reply_markup=None,
    disable_web_page_preview: bool | None = None,
) -> bool:
    """Редактирует сообщение: HTML → sanitized HTML → plain. Не бросает наружу."""
    extra = {}
    if reply_markup is not None:
        extra["reply_markup"] = reply_markup
    if disable_web_page_preview is not None:
        extra["disable_web_page_preview"] = disable_web_page_preview

    sanitized = sanitize_telegram_html(text)
    plain = strip_html(sanitized or text).strip() or _EDIT_FAIL_PLAIN
    attempts: list[tuple[str, str | None]] = [
        (text, "HTML"),
        (sanitized or _EDIT_FAIL_PLAIN, "HTML"),
        (plain, None),
    ]

    seen: set[tuple[str, str | None]] = set()
    for body, parse_mode in attempts:
        key = (body, parse_mode)
        if key in seen:
            continue
        seen.add(key)
        kwargs = dict(extra)
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        try:
            await edit_fn(body, **kwargs)
            return True
        except telegram.error.BadRequest as ex:
            if _is_not_modified(ex):
                return True
            logger.warning(
                "edit_message_text failed mode=%s: %s",
                parse_mode or "plain",
                type(ex).__name__,
            )
        except Exception as ex:
            logger.warning(
                "edit_message_text failed mode=%s: %s",
                parse_mode or "plain",
                type(ex).__name__,
            )
    return False


async def edit_order_message(bot, chat_id: int, message_id: int, text: str):
    async def _edit(body: str, **kwargs):
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=body,
            **kwargs,
        )

    await edit_message_text_safe(_edit, text)
