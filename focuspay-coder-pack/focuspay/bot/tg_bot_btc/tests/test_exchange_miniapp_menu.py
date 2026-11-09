"""«Приложение» — кнопка у поля ввода, не ряд reply-клавиатуры."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from telegram import MenuButtonDefault, MenuButtonWebApp

from services.menu import (
    EXCHANGE_OPEN_BUTTON,
    EXCHANGE_OPEN_TEXT,
    MENU_APP,
    MENU_EXCHANGE,
    exchange_chat_menu_button,
    exchange_miniapp_url,
    exchange_open_markup,
    main_menu_keyboard,
    send_exchange_open_prompt,
)


class ExchangeMiniappMenuTests(unittest.IsolatedAsyncioTestCase):
    def test_http_and_empty_urls_are_ignored(self):
        cases = {
            "": None,
            "http://focuspay.org/exchange/tg": None,
            "https://focuspay.org/exchange/tg": "https://focuspay.org/exchange/tg",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw), patch.dict("os.environ", {"EXCHANGE_MINIAPP_URL": raw}):
                self.assertEqual(exchange_miniapp_url(), expected)

    def test_https_sets_the_chat_menu_button(self):
        with patch.dict("os.environ", {"EXCHANGE_MINIAPP_URL": "https://focuspay.org/exchange/tg"}):
            button = exchange_chat_menu_button()
        self.assertIsInstance(button, MenuButtonWebApp)
        self.assertEqual(button.text, MENU_APP)
        self.assertEqual(button.web_app.url, "https://focuspay.org/exchange/tg")

    def test_missing_url_resets_the_chat_menu_button(self):
        with patch.dict("os.environ", {"EXCHANGE_MINIAPP_URL": ""}):
            self.assertIsInstance(exchange_chat_menu_button(), MenuButtonDefault)

    async def test_reply_keyboard_never_contains_the_app_button(self):
        for raw in ("", "https://focuspay.org/exchange/tg"):
            with (
                self.subTest(raw=raw),
                patch.dict("os.environ", {"EXCHANGE_MINIAPP_URL": raw}),
                patch("services.menu.get_partner_by_telegram", new=AsyncMock(return_value=None)),
                patch("services.db.user_has_payment_active_order", new=AsyncMock(return_value=False)),
            ):
                menu = await main_menu_keyboard(7, "buyer")
            labels = [button.text for row in menu.keyboard for button in row]
            self.assertNotIn(MENU_APP, labels)
            self.assertIn(MENU_EXCHANGE, labels)

    def test_https_url_builds_the_chat_list_open_button(self):
        with patch.dict("os.environ", {"EXCHANGE_MINIAPP_URL": "https://focuspay.org/exchange/tg"}):
            markup = exchange_open_markup()
        self.assertIsNotNone(markup)
        button = markup.inline_keyboard[0][0]
        self.assertEqual(button.text, EXCHANGE_OPEN_BUTTON)
        self.assertEqual(button.web_app.url, "https://focuspay.org/exchange/tg")
        self.assertEqual(len(markup.inline_keyboard), 1)
        self.assertEqual(len(markup.inline_keyboard[0]), 1)

    def test_missing_url_has_no_chat_list_button(self):
        with patch.dict("os.environ", {"EXCHANGE_MINIAPP_URL": ""}):
            self.assertIsNone(exchange_open_markup())

    async def test_prompt_is_one_web_app_message(self):
        bot = AsyncMock()
        with patch.dict("os.environ", {"EXCHANGE_MINIAPP_URL": "https://focuspay.org/exchange/tg"}):
            sent = await send_exchange_open_prompt(bot, 42)
        self.assertTrue(sent)
        bot.send_message.assert_awaited_once()
        _, kwargs = bot.send_message.await_args
        self.assertEqual(kwargs["chat_id"], 42)
        self.assertEqual(kwargs["text"], EXCHANGE_OPEN_TEXT)
        button = kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.web_app.url, "https://focuspay.org/exchange/tg")

    async def test_prompt_is_skipped_without_url(self):
        bot = AsyncMock()
        with patch.dict("os.environ", {"EXCHANGE_MINIAPP_URL": ""}):
            sent = await send_exchange_open_prompt(bot, 42)
        self.assertFalse(sent)
        bot.send_message.assert_not_awaited()
