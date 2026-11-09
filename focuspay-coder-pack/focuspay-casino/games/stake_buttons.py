"""Inline stake buttons that work in groups when Telegram privacy mode is on."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from telebot import types

STAKE_PRESETS = (10, 25, 50, 100, 250, 500)


def is_private_chat(chat: Any, user: Any) -> bool:
    chat_id = getattr(chat, "id", None)
    user_id = getattr(user, "id", None)
    return (
        getattr(chat, "type", None) == "private"
        and isinstance(chat_id, int)
        and isinstance(user_id, int)
        and chat_id == user_id
    )


def stake_keyboard(
    *,
    callback_prefix: str,
    min_bet,
    max_bet,
    private: bool,
) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    lo = Decimal(str(min_bet))
    hi = Decimal(str(max_bet))
    buttons = [
        types.InlineKeyboardButton(f"{stake} ₽", callback_data=f"{callback_prefix}{stake}")
        for stake in STAKE_PRESETS
        if lo <= Decimal(stake) <= hi
    ]
    if buttons:
        keyboard.add(*buttons)
    if private:
        keyboard.add(types.InlineKeyboardButton("✏️ Своя сумма", callback_data=f"{callback_prefix}custom"))
    return keyboard


def command_stake_arg(text: str | None) -> str | None:
    parts = str(text or "").split()
    if len(parts) < 2:
        return None
    return parts[1]
