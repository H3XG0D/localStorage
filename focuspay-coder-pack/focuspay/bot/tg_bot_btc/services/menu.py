import logging
import os

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonDefault,
    MenuButtonWebApp,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from services.partner_db import get_partner_by_telegram
from services.raffle_constants import FOCUS_LUCKY_MENU

logger = logging.getLogger("menu")

# Reply-кнопки главного меню (текст должен совпадать с regex в main.py)
MENU_EXCHANGE = "Совершить обмен"
MENU_APP = "Приложение"
# Текст последнего сообщения: его видно в списке чатов рядом с синей «ОТКРЫТЬ».
EXCHANGE_OPEN_TEXT = "Обмен в приложении"
EXCHANGE_OPEN_BUTTON = "Открыть обмен"
MENU_APP_CASINO = "Казино"
CASINO_OPEN_TEXT = "Казино в приложении"
CASINO_OPEN_BUTTON = "🎰 Открыть FocusBet"
MENU_PROFILE = "Профиль"
MENU_ABOUT = "О нас"
MENU_FOCUS_LUCKY = FOCUS_LUCKY_MENU
MENU_FOCUSBET = "FocusBet"
MENU_FOCUSVPN = "FocusVPN"
MENU_PARTNER = "Партнёрский кабинет"
MENU_ACTIVE_ORDER = "Активная заявка"

# Старые подписи — для пользователей со старой reply-клавиатурой до /start
MENU_EXCHANGE_LEGACY = "🔄 Совершить обмен"


def _https_miniapp_url(env_name: str) -> str | None:
    """Кнопка у поля ввода только для публичного https. http и пустое значение её не ставят."""
    raw = (os.getenv(env_name) or "").strip()
    if raw.lower().startswith("https://"):
        return raw
    return None


def exchange_miniapp_url() -> str | None:
    return _https_miniapp_url("EXCHANGE_MINIAPP_URL")


def casino_miniapp_url() -> str | None:
    return _https_miniapp_url("CASINO_MINIAPP_URL")


def exchange_chat_menu_button():
    """Официальная кнопка Telegram слева от поля ввода, не ряд reply-клавиатуры."""
    url = exchange_miniapp_url()
    if not url:
        return MenuButtonDefault()
    return MenuButtonWebApp(text=MENU_APP, web_app=WebAppInfo(url=url))


def casino_chat_menu_button():
    """Казино в приоритете; без его URL остаётся прежняя кнопка обмена."""
    url = casino_miniapp_url()
    if not url:
        return exchange_chat_menu_button()
    return MenuButtonWebApp(text=MENU_APP_CASINO, web_app=WebAppInfo(url=url))


async def install_chat_menu_button(bot) -> None:
    await bot.set_chat_menu_button(menu_button=casino_chat_menu_button())


def _open_markup(label: str, url: str | None) -> InlineKeyboardMarkup | None:
    """Inline web_app. Клиент рисует «ОТКРЫТЬ» в списке чатов, только если это последнее сообщение."""
    if not url:
        return None
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    label,
                    web_app=WebAppInfo(url=url),
                    style="primary",
                )
            ]
        ]
    )


def exchange_open_markup() -> InlineKeyboardMarkup | None:
    return _open_markup(EXCHANGE_OPEN_BUTTON, exchange_miniapp_url())


def casino_open_markup() -> InlineKeyboardMarkup | None:
    return _open_markup(CASINO_OPEN_BUTTON, casino_miniapp_url())


async def send_exchange_open_prompt(bot, chat_id: int) -> bool:
    """Отдельное сообщение: reply-клавиатура и inline-кнопка на одном сообщении не живут."""
    markup = exchange_open_markup()
    if markup is None:
        return False
    await bot.send_message(chat_id=chat_id, text=EXCHANGE_OPEN_TEXT, reply_markup=markup)
    return True


async def send_casino_open_prompt(bot, chat_id: int) -> bool:
    markup = casino_open_markup()
    if markup is None:
        return False
    await bot.send_message(chat_id=chat_id, text=CASINO_OPEN_TEXT, reply_markup=markup)
    return True


async def main_menu_keyboard(user_id: int | None = None, username: str | None = None):
    rows: list[list[KeyboardButton]] = []

    if user_id is not None:
        try:
            from services.db import user_has_payment_active_order

            if await user_has_payment_active_order(user_id):
                rows.append([KeyboardButton(MENU_ACTIVE_ORDER)])
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)

    rows.append([KeyboardButton(MENU_EXCHANGE, style="success")])
    rows.append(
        [
            KeyboardButton(MENU_PROFILE, style="primary"),
            KeyboardButton(MENU_ABOUT, style="danger"),
        ]
    )
    rows.append([KeyboardButton(MENU_FOCUSBET), KeyboardButton(MENU_FOCUSVPN)])

    if user_id is not None:
        partner = await get_partner_by_telegram(user_id, username)
        if partner:
            rows.append([KeyboardButton(MENU_PARTNER)])

    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие или введите промокод…",
    )
