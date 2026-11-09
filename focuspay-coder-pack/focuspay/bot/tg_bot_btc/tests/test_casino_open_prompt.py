"""Кнопка «Открыть FocusBet»: меню чата и напоминание после сообщения."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import MenuButtonDefault, MenuButtonWebApp

from handlers.casino_open_prompt import (
    LAST_PROMPT_KEY,
    PROMPT_COOLDOWN_SEC,
    casino_open_prompt_handler,
)
from services.menu import (
    CASINO_OPEN_BUTTON,
    CASINO_OPEN_TEXT,
    MENU_APP,
    MENU_APP_CASINO,
    casino_chat_menu_button,
    casino_open_markup,
    send_casino_open_prompt,
)

CASINO_URL = "https://focuspay.org/casino"
EXCHANGE_URL = "https://focuspay.org/exchange/tg"


def _update(chat_type: str = "private"):
    update = MagicMock()
    update.effective_chat.type = chat_type
    update.effective_chat.PRIVATE = "private"
    update.effective_chat.id = 42
    return update


def _context(user_data: dict | None = None):
    context = MagicMock()
    context.bot = AsyncMock()
    context.user_data = {} if user_data is None else user_data
    return context


class CasinoChatMenuButtonTests(unittest.TestCase):
    def test_casino_url_wins_over_exchange(self):
        with patch.dict(
            "os.environ",
            {"CASINO_MINIAPP_URL": CASINO_URL, "EXCHANGE_MINIAPP_URL": EXCHANGE_URL},
        ):
            button = casino_chat_menu_button()
        self.assertIsInstance(button, MenuButtonWebApp)
        self.assertEqual(button.text, MENU_APP_CASINO)
        self.assertEqual(button.web_app.url, CASINO_URL)

    def test_without_casino_url_exchange_button_stays(self):
        with patch.dict(
            "os.environ",
            {"CASINO_MINIAPP_URL": "", "EXCHANGE_MINIAPP_URL": EXCHANGE_URL},
        ):
            button = casino_chat_menu_button()
        self.assertIsInstance(button, MenuButtonWebApp)
        self.assertEqual(button.text, MENU_APP)
        self.assertEqual(button.web_app.url, EXCHANGE_URL)

    def test_http_casino_url_is_ignored(self):
        with patch.dict(
            "os.environ",
            {"CASINO_MINIAPP_URL": "http://focuspay.org/casino", "EXCHANGE_MINIAPP_URL": ""},
        ):
            self.assertIsInstance(casino_chat_menu_button(), MenuButtonDefault)

    def test_markup_is_one_web_app_button(self):
        with patch.dict("os.environ", {"CASINO_MINIAPP_URL": CASINO_URL}):
            markup = casino_open_markup()
        self.assertEqual(len(markup.inline_keyboard), 1)
        button = markup.inline_keyboard[0][0]
        self.assertEqual(button.text, CASINO_OPEN_BUTTON)
        self.assertEqual(button.web_app.url, CASINO_URL)


class CasinoOpenPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_is_sent_once_and_then_throttled(self):
        update, context = _update(), _context()
        with patch.dict("os.environ", {"CASINO_MINIAPP_URL": CASINO_URL}):
            await casino_open_prompt_handler(update, context)
            await casino_open_prompt_handler(update, context)

        context.bot.send_message.assert_awaited_once()
        _, kwargs = context.bot.send_message.await_args
        self.assertEqual(kwargs["chat_id"], 42)
        self.assertEqual(kwargs["text"], CASINO_OPEN_TEXT)
        self.assertIn(LAST_PROMPT_KEY, context.user_data)

    async def test_prompt_returns_after_cooldown(self):
        update = _update()
        context = _context({LAST_PROMPT_KEY: 0.0})
        with (
            patch.dict("os.environ", {"CASINO_MINIAPP_URL": CASINO_URL}),
            patch("handlers.casino_open_prompt.time.time", return_value=PROMPT_COOLDOWN_SEC + 1),
        ):
            await casino_open_prompt_handler(update, context)
        context.bot.send_message.assert_awaited_once()

    async def test_active_exchange_step_is_not_interrupted(self):
        update = _update()
        context = _context({"step": "enter_amount"})
        with patch.dict("os.environ", {"CASINO_MINIAPP_URL": CASINO_URL}):
            await casino_open_prompt_handler(update, context)
        context.bot.send_message.assert_not_awaited()

    async def test_group_chat_is_skipped(self):
        update, context = _update("supergroup"), _context()
        with patch.dict("os.environ", {"CASINO_MINIAPP_URL": CASINO_URL}):
            await casino_open_prompt_handler(update, context)
        context.bot.send_message.assert_not_awaited()

    async def test_without_url_nothing_is_sent_and_cooldown_stays_empty(self):
        update, context = _update(), _context()
        with patch.dict("os.environ", {"CASINO_MINIAPP_URL": ""}):
            await casino_open_prompt_handler(update, context)
        context.bot.send_message.assert_not_awaited()
        self.assertNotIn(LAST_PROMPT_KEY, context.user_data)

    async def test_send_helper_skips_without_url(self):
        bot = AsyncMock()
        with patch.dict("os.environ", {"CASINO_MINIAPP_URL": ""}):
            self.assertFalse(await send_casino_open_prompt(bot, 1))
        bot.send_message.assert_not_awaited()
