"""Reply-keyboard main menu for FocusCasino bot (no slash commands)."""
from __future__ import annotations

from telebot import types


# Текст кнопок главного меню (для сопоставления в handlers)
MENU_CREATE_GAME = "🎮 Создать игру"
MENU_FIND_GAME = "🎯 Активные игры"
MENU_MY_GAMES = "🎲 Мои игры"
MENU_PROFILE = "👤 Профиль"
MENU_TEAM = "👥 Команда"
MENU_BALANCE = "💰 Баланс"
MENU_DEPOSIT = "💳 Пополнить"
MENU_MINIAPP = "🎰 На сайте"


def miniapp_url() -> str:
    try:
        import config as casino_config

        return str(getattr(casino_config, "CASINO_MINIAPP_URL", "") or "").strip()
    except Exception:
        return ""


def miniapp_web_app_url() -> str:
    """Telegram Web App buttons accept HTTPS only.

    Staging uses http://127.0.0.1:18081/casino/tg. Attaching that as web_app
    makes Telegram reject the whole /start message (HTTP 400).
    """
    url = miniapp_url()
    return url if url.lower().startswith("https://") else ""


def main_menu_keyboard() -> types.ReplyKeyboardMarkup:
    """Главное меню casino-бота (ReplyKeyboardMarkup, как в FocusPay)."""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)

    # Первая строка: создание и поиск игр
    keyboard.row(
        types.KeyboardButton(MENU_CREATE_GAME),
        types.KeyboardButton(MENU_FIND_GAME),
    )

    # Вторая строка: свои игры и профиль
    keyboard.row(
        types.KeyboardButton(MENU_MY_GAMES),
        types.KeyboardButton(MENU_PROFILE),
    )
    keyboard.row(
        types.KeyboardButton(MENU_BALANCE),
        types.KeyboardButton(MENU_DEPOSIT),
    )

    url = miniapp_web_app_url()
    if url:
        keyboard.row(types.KeyboardButton(MENU_MINIAPP, web_app=types.WebAppInfo(url=url)))

    return keyboard
