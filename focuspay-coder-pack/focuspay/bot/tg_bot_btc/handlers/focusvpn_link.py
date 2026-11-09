"""Кнопка «FocusVPN» главного меню: описание + переход в бот FocusVPN."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from services.antispam import rate_limit_ok
from services.focusvpn_link import DEFAULT_PURCHASE_MIN_EXCHANGES, exchange_progress, focusvpn_keyboard, focusvpn_text

logger = logging.getLogger(__name__)


async def focusvpn_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not await rate_limit_ok(update):
        return
    try:
        have, need, invited_have, invited_need, trusted = await exchange_progress(update.effective_user.id)
    except Exception:
        logger.exception("focusvpn progress failed user=%s", update.effective_user.id)
        have, need, invited_have, invited_need, trusted = 0, DEFAULT_PURCHASE_MIN_EXCHANGES, 0, 30, False
    await update.message.reply_text(
        focusvpn_text(have, need, invited_have, invited_need, trusted=trusted),
        parse_mode=ParseMode.HTML,
        reply_markup=focusvpn_keyboard(),
        disable_web_page_preview=True,
    )
