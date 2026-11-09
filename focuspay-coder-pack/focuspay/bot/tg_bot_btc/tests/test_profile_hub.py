"""Кнопка «Профиль»: reply-клавиатура, hub callback, ошибки не молчат."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.profile_hub import (
    HUB_CB_PREFIX,
    PROFILE_CB_DATA,
    PROFILE_FAIL_TEXT,
    hub_callback,
    profile_hub_handler,
)
from services.menu import MENU_FOCUS_LUCKY, MENU_FOCUSBET, MENU_PROFILE, main_menu_keyboard


def _user(uid=42, username="buyer"):
    return SimpleNamespace(id=uid, username=username, full_name="Buyer", first_name="Buyer")


def _message(user=None):
    msg = SimpleNamespace(
        text=MENU_PROFILE,
        chat=SimpleNamespace(id=42),
        reply_text=AsyncMock(),
        reply_photo=AsyncMock(),
    )
    return msg


def _update_message():
    user = _user()
    msg = _message(user)
    return SimpleNamespace(
        message=msg,
        effective_user=user,
        effective_chat=msg.chat,
        callback_query=None,
    ), msg, user


def _update_callback(data=PROFILE_CB_DATA):
    user = _user()
    msg = _message(user)
    query = SimpleNamespace(
        data=data,
        message=msg,
        from_user=user,
        answer=AsyncMock(),
    )
    return SimpleNamespace(
        callback_query=query,
        message=None,
        effective_user=user,
        effective_chat=msg.chat,
    ), query, msg


class MenuProfileButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_keyboard_uses_text_not_callback(self):
        kb = await main_menu_keyboard()
        labels = [btn.text for row in kb.keyboard for btn in row]
        self.assertIn(MENU_PROFILE, labels)
        self.assertEqual(MENU_PROFILE, "Профиль")
        self.assertIn(MENU_FOCUSBET, labels)
        self.assertEqual(MENU_FOCUSBET, "FocusBet")
        self.assertEqual(labels[3], MENU_FOCUSBET)
        self.assertNotIn(MENU_FOCUS_LUCKY, labels)
        self.assertEqual(MENU_FOCUS_LUCKY, "🍀 FocusLucky")
        profile_btn = next(btn for row in kb.keyboard for btn in row if btn.text == MENU_PROFILE)
        self.assertIsNone(getattr(profile_btn, "callback_data", None))

    def test_inline_profile_callback_value(self):
        self.assertEqual(PROFILE_CB_DATA, "hub:profile")
        self.assertTrue(PROFILE_CB_DATA.startswith(HUB_CB_PREFIX))


class ProfileHubHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_profile_and_registers_hub_callback(self):
        update, msg, user = _update_message()
        context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))
        with (
            patch("handlers.profile_hub.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch(
                "handlers.profile_hub._deliver_profile",
                new=AsyncMock(),
            ) as deliver,
        ):
            await profile_hub_handler(update, context)
        deliver.assert_awaited_once()
        context.bot.send_chat_action.assert_awaited()

    async def test_exception_replies_instead_of_silence(self):
        update, msg, user = _update_message()
        context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))
        with (
            patch("handlers.profile_hub.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch(
                "handlers.profile_hub._deliver_profile",
                new=AsyncMock(side_effect=RuntimeError("db down")),
            ),
            patch(
                "services.menu.main_menu_keyboard",
                new=AsyncMock(return_value="menu"),
            ),
        ):
            await profile_hub_handler(update, context)
        msg.reply_text.assert_awaited()
        args, kwargs = msg.reply_text.await_args
        self.assertEqual(args[0], PROFILE_FAIL_TEXT)


class HubCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_answers_callback_before_work(self):
        update, query, msg = _update_callback()
        context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))
        with (
            patch("handlers.profile_hub.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch("handlers.profile_hub._deliver_profile", new=AsyncMock()) as deliver,
        ):
            await hub_callback(update, context)
        query.answer.assert_awaited()
        deliver.assert_awaited_once()

    async def test_answers_even_when_rate_limited(self):
        update, query, msg = _update_callback(data="hub:balance")
        context = SimpleNamespace(bot=object())
        with patch("handlers.profile_hub.rate_limit_ok", new=AsyncMock(return_value=False)):
            await hub_callback(update, context)
        query.answer.assert_awaited()
        msg.reply_text.assert_not_awaited()

    async def test_exception_after_answer_still_notifies_user(self):
        update, query, msg = _update_callback(data="hub:balance")
        context = SimpleNamespace(bot=object())
        with (
            patch("handlers.profile_hub.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch(
                "handlers.profile_hub._hub_callback_body",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            await hub_callback(update, context)
        query.answer.assert_awaited()
        msg.reply_text.assert_awaited_with(PROFILE_FAIL_TEXT)


class MainWiringTests(unittest.TestCase):
    def test_main_registers_profile_and_error_handlers(self):
        from pathlib import Path

        src = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
        self.assertIn("profile_hub_handler", src)
        self.assertIn("MENU_PROFILE", src)
        self.assertIn("FOCUS_LUCKY_MENU", src)
        self.assertIn("MENU_FOCUSBET", src)
        self.assertIn("focusbet_menu_handler", src)
        self.assertIn('pattern="^hub:"', src)
        self.assertIn("ops_bind_command", src)
        self.assertIn("ops_profile_callback", src)
        self.assertIn("unanswered_callback_fallback", src)
        self.assertIn("telegram_error_handler", src)
        self.assertIn('CommandHandler("ops_bind"', src)


if __name__ == "__main__":
    unittest.main()
