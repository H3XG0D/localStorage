"""Ссылка FocusBet: URL бота, меню, пост-paid после отзыва."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.casino_login import focusbet_menu_handler
from services.config_rates import casino_bot_url, casino_bot_username
from services.focusbet_link import (
    FOCUSBET_TEXT,
    focusbet_invite_text,
    focusbet_keyboard,
    focusbet_reply_markup_dict,
)
from services.menu import MENU_FOCUS_LUCKY, MENU_FOCUSBET, MENU_FOCUSVPN, main_menu_keyboard


class CasinoBotUrlTests(unittest.TestCase):
    def test_default_prod_username(self):
        env = {k: v for k, v in os.environ.items() if k != "CASINO_BOT_USERNAME"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(casino_bot_username(), "focusludka_bot")
            self.assertEqual(casino_bot_url(), "https://t.me/focusludka_bot")

    def test_env_override_strips_at(self):
        with patch.dict(os.environ, {"CASINO_BOT_USERNAME": "@staging_focusbet_bot"}):
            self.assertEqual(casino_bot_username(), "staging_focusbet_bot")
            self.assertEqual(casino_bot_url(), "https://t.me/staging_focusbet_bot")

    def test_empty_env_falls_back(self):
        with patch.dict(os.environ, {"CASINO_BOT_USERNAME": "  "}):
            self.assertEqual(casino_bot_url(), "https://t.me/focusludka_bot")


class FocusBetMainMenuTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_keyboard_has_focusbet_not_focus_lucky(self):
        kb = await main_menu_keyboard()
        labels = [btn.text for row in kb.keyboard for btn in row]
        self.assertEqual(labels, ["Совершить обмен", "Профиль", "О нас", MENU_FOCUSBET, MENU_FOCUSVPN])
        self.assertNotIn(MENU_FOCUS_LUCKY, labels)


class FocusBetMarkupTests(unittest.TestCase):
    def test_invite_text_and_http_markup(self):
        self.assertEqual(focusbet_invite_text(), "FocusBet")
        self.assertEqual(MENU_FOCUSBET, FOCUSBET_TEXT)
        with patch.dict(os.environ, {"CASINO_BOT_USERNAME": "focusludka_bot"}):
            d = focusbet_reply_markup_dict()
            btn = d["inline_keyboard"][0][0]
            self.assertEqual(btn["text"], "FocusBet")
            self.assertEqual(btn["url"], "https://t.me/focusludka_bot")

    def test_keyboard_url(self):
        with patch.dict(os.environ, {"CASINO_BOT_USERNAME": "focusludka_bot"}):
            kb = focusbet_keyboard()
            self.assertEqual(kb.inline_keyboard[0][0].text, "FocusBet")
            self.assertEqual(kb.inline_keyboard[0][0].url, "https://t.me/focusludka_bot")


class FocusBetMenuHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_focusbet_url_button(self):
        msg = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(message=msg)
        context = SimpleNamespace()
        with (
            patch("handlers.casino_login.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch.dict(os.environ, {"CASINO_BOT_USERNAME": "focusludka_bot"}),
        ):
            await focusbet_menu_handler(update, context)
        kwargs = msg.reply_text.await_args.kwargs
        self.assertEqual(msg.reply_text.await_args.args[0], "FocusBet")
        self.assertEqual(
            kwargs["reply_markup"].inline_keyboard[0][0].url,
            "https://t.me/focusludka_bot",
        )


class NotifyBuyerPaidFocusBetTests(unittest.IsolatedAsyncioTestCase):
    async def test_focusbet_after_review_invite(self):
        order = {
            "order_id": "OP1",
            "user_id": 42,
            "crypto": "usdt",
            "crypto_amount": 10,
            "wallet_address": "Txxx",
            "direction": "buy",
        }
        bot = SimpleNamespace(send_message=AsyncMock())
        sequence: list[str] = []

        async def _mark(name: str):
            async def _inner(*_a, **_k):
                sequence.append(name)

            return _inner

        with (
            patch(
                "services.buy_payout.order_cashback_notify_info",
                new=AsyncMock(
                    return_value={"applied": 0.0, "accrued": 0.0, "overpay_credit": 0.0}
                ),
            ),
            patch(
                "services.marketing_messages.send_post_paid_marketing",
                new=await _mark("marketing"),
            ),
            patch(
                "services.marketing_messages.send_post_paid_focus_lucky",
                new=await _mark("lucky"),
            ),
            patch(
                "services.marketing_messages.send_post_paid_review_invite",
                new=await _mark("review"),
            ),
            patch(
                "services.marketing_messages.send_post_paid_focusbet",
                new=await _mark("focusbet"),
            ),
        ):
            from services.buy_payout import notify_buyer_paid

            await notify_buyer_paid(order, "https://example.com/tx", bot=bot)

        self.assertEqual(sequence, ["marketing", "lucky", "review", "focusbet"])
        bot.send_message.assert_awaited()


class SendPostPaidFocusBetTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_url_button(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch.dict(os.environ, {"CASINO_BOT_USERNAME": "focusludka_bot"}):
            from services.marketing_messages import send_post_paid_focusbet

            await send_post_paid_focusbet(99, bot=bot)
        kwargs = bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["text"], "FocusBet")
        self.assertEqual(
            kwargs["reply_markup"].inline_keyboard[0][0].url,
            "https://t.me/focusludka_bot",
        )


if __name__ == "__main__":
    unittest.main()
