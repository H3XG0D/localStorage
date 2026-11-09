"""Ссылка на игровой бот FocusBet: меню и сообщение после PAID."""
from __future__ import annotations

from services.config_rates import casino_bot_url

FOCUSBET_TEXT = "FocusBet"


def focusbet_invite_text() -> str:
    return FOCUSBET_TEXT


def focusbet_reply_markup_dict() -> dict:
    return {
        "inline_keyboard": [
            [{"text": FOCUSBET_TEXT, "url": casino_bot_url()}],
        ],
    }


def focusbet_keyboard():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(FOCUSBET_TEXT, url=casino_bot_url())]]
    )
