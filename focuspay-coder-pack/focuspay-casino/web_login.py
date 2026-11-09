"""Site login via /start cauth_<token> — FocusBet web session, not Mini App."""
from __future__ import annotations

import logging
import re
from typing import Any

from telebot import types

from focuspay_client import get_focuspay_client

logger = logging.getLogger(__name__)

CAUTH_RE = re.compile(r"cauth_([a-f0-9]{32})", re.IGNORECASE)


def extract_cauth_token(payload: str | None) -> str | None:
    raw = (payload or "").strip()
    if not raw:
        return None
    match = CAUTH_RE.search(raw)
    if not match:
        return None
    return match.group(1).lower()


def _open_keyboard(url: str) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("Открыть казино", url=url))
    return keyboard


async def maybe_send_site_login(bot: Any, message: Any) -> bool:
    """If /start carried cauth_, attach Telegram and send the site ticket button."""
    if getattr(getattr(message, "chat", None), "type", "") != "private":
        return False
    token = extract_cauth_token(getattr(message, "text", None) or "")
    if not token:
        return False
    user = message.from_user
    if user is None:
        return True
    try:
        client = await get_focuspay_client()
        attached = await client.attach_web_login(
            start_token=f"cauth_{token}",
            telegram_id=int(user.id),
            username=getattr(user, "username", None),
            first_name=getattr(user, "first_name", None),
        )
    except Exception:
        logger.exception("site cauth attach failed user=%s", getattr(user, "id", None))
        await bot.send_message(
            message.chat.id,
            "Не удалось открыть сайт. Нажмите «Войти» на сайте ещё раз.",
        )
        return True
    if not attached:
        await bot.send_message(
            message.chat.id,
            "Ссылка входа истекла. Вернитесь на сайт FocusBet и нажмите «Войти» ещё раз.",
        )
        return True
    await bot.send_message(
        message.chat.id,
        "Вход в <b>FocusBet</b>.\n\n"
        "Нажмите кнопку — откроется казино уже под вашим Telegram.\n"
        "Номер телефона вводить не нужно.",
        parse_mode="HTML",
        reply_markup=_open_keyboard(str(attached["url"])),
    )
    return True
