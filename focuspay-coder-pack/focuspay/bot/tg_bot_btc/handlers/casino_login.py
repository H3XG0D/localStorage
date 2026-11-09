""" /start cauth_TOKEN and /casino — open FocusBet without the site phone widget. """

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from services.antispam import rate_limit_ok
from services.casino_bot_login import (
    CAUTH_PAYLOAD_KEY,
    attach_telegram_to_start,
    create_direct_ticket,
    extract_cauth_token,
)
from services.focusbet_link import FOCUSBET_TEXT, focusbet_keyboard

logger = logging.getLogger(__name__)


def _open_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Открыть казино", url=url)]]
    )


def _success_text() -> str:
    return (
        "Вход в <b>FocusBet</b>.\n\n"
        "Нажмите кнопку — откроется казино уже под вашим Telegram.\n"
        "Номер телефона вводить не нужно."
    )


async def _reply_casino(update: Update, url: str) -> None:
    target = update.effective_message
    if not target:
        return
    await target.reply_text(
        _success_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=_open_keyboard(url),
        disable_web_page_preview=True,
    )


def _payload_from_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    args = context.args or []
    if args:
        return str(args[0])
    stashed = str(context.user_data.get(CAUTH_PAYLOAD_KEY) or "")
    if extract_cauth_token(stashed):
        return stashed
    return ""


async def maybe_send_casino_login(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """True if this /start carried cauth_ (success or expired). Does not skip captcha."""
    payload = _payload_from_update(update, context)
    if not extract_cauth_token(payload):
        return False
    context.user_data.pop(CAUTH_PAYLOAD_KEY, None)
    user = update.effective_user
    if not user:
        return True
    try:
        attached = await attach_telegram_to_start(
            payload,
            user.id,
            username=user.username,
            first_name=user.first_name,
        )
    except Exception:
        logger.exception("casino cauth attach failed user=%s", user.id)
        target = update.effective_message
        if target:
            await target.reply_text(
                "Не удалось открыть казино из‑за ошибки сервера. Нажмите /casino или откройте ссылку с сайта ещё раз."
            )
        return True
    if not attached:
        target = update.effective_message
        if target:
            await target.reply_text(
                "Ссылка входа истекла. Вернитесь на сайт FocusBet и нажмите «Войти» ещё раз."
            )
        return True
    await _reply_casino(update, attached["url"])
    return True


async def casino_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not await rate_limit_ok(update):
        return
    user = update.effective_user
    if not user:
        return
    try:
        ticket = await create_direct_ticket(
            user.id,
            username=user.username,
            first_name=user.first_name,
        )
    except Exception:
        logger.exception("casino /casino ticket failed user=%s", user.id)
        await update.message.reply_text(
            "Не удалось открыть казино. Попробуйте /casino ещё раз через минуту."
        )
        return
    await _reply_casino(update, ticket["url"])


async def focusbet_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not await rate_limit_ok(update):
        return
    await update.message.reply_text(
        FOCUSBET_TEXT,
        reply_markup=focusbet_keyboard(),
        disable_web_page_preview=True,
    )
