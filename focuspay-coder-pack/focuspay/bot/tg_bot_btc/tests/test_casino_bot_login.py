"""cauth_ / /casino: кнопка «Открыть казино», вход до капчи."""

from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.casino_login import casino_command, maybe_send_casino_login
from handlers.start import start_handler
from services.casino_bot_login import extract_cauth_token


TOKEN = "a" * 32


def _update(text="/start cauth_" + TOKEN, uid=99):
    user = SimpleNamespace(id=uid, username="alice", first_name="Alice")
    msg = SimpleNamespace(
        text=text,
        reply_text=AsyncMock(),
        chat=SimpleNamespace(id=uid),
    )
    return SimpleNamespace(
        message=msg,
        effective_message=msg,
        effective_user=user,
        effective_chat=msg.chat,
        callback_query=None,
    ), msg, user


def _stub_captcha_module() -> ModuleType:
    mod = ModuleType("handlers.captcha_handler")
    mod.send_captcha = AsyncMock()
    mod.CAPTCHA_REF_PAYLOAD_KEY = "_captcha_start_ref"
    return mod


class ExtractCauthTests(unittest.TestCase):
    def test_prefix(self):
        self.assertEqual(extract_cauth_token(f"cauth_{TOKEN}"), TOKEN)
        self.assertEqual(extract_cauth_token(f"/start cauth_{TOKEN}"), TOKEN)
        self.assertIsNone(extract_cauth_token("opsbind_ABCDEFGH12"))
        self.assertIsNone(extract_cauth_token("ref_abc123xyz999"))
        self.assertIsNone(extract_cauth_token(TOKEN))


class CasinoLoginHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_cauth_sends_open_button(self):
        update, msg, user = _update()
        context = SimpleNamespace(args=[f"cauth_{TOKEN}"], user_data={})
        attached = {
            "ticket": "b" * 32,
            "return_path": "/casino",
            "url": "https://focuspay.org/login/telegram?ticket=bb&next=%2Fcasino",
        }
        with patch(
            "handlers.casino_login.attach_telegram_to_start",
            new=AsyncMock(return_value=attached),
        ):
            self.assertTrue(await maybe_send_casino_login(update, context))
        text = msg.reply_text.await_args.args[0]
        self.assertIn("FocusBet", text)
        markup = msg.reply_text.await_args.kwargs["reply_markup"]
        self.assertEqual(markup.inline_keyboard[0][0].text, "Открыть казино")
        self.assertIn("/login/telegram", markup.inline_keyboard[0][0].url)

    async def test_expired_explains(self):
        update, msg, user = _update()
        context = SimpleNamespace(args=[f"cauth_{TOKEN}"], user_data={})
        with patch(
            "handlers.casino_login.attach_telegram_to_start",
            new=AsyncMock(return_value=None),
        ):
            self.assertTrue(await maybe_send_casino_login(update, context))
        text = msg.reply_text.await_args.args[0]
        self.assertIn("истекла", text.lower())

    async def test_non_cauth_ignored(self):
        update, msg, user = _update(text="/start ref_abc")
        context = SimpleNamespace(args=["ref_abc123xyz999"], user_data={})
        self.assertFalse(await maybe_send_casino_login(update, context))
        msg.reply_text.assert_not_awaited()

    async def test_casino_command_sends_button(self):
        update, msg, user = _update(text="/casino")
        context = SimpleNamespace(args=[])
        ticket = {
            "url": "https://focuspay.org/login/telegram?ticket=cc&next=%2Fcasino",
        }
        with (
            patch("handlers.casino_login.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch(
                "handlers.casino_login.create_direct_ticket",
                new=AsyncMock(return_value=ticket),
            ),
        ):
            await casino_command(update, context)
        markup = msg.reply_text.await_args.kwargs["reply_markup"]
        self.assertEqual(markup.inline_keyboard[0][0].url, ticket["url"])

    async def test_new_user_cauth_before_captcha(self):
        update, msg, user = _update()
        context = MagicMock()
        context.args = [f"cauth_{TOKEN}"]
        context.user_data = {}
        context.bot = MagicMock()
        captcha_mod = _stub_captcha_module()
        attached = {
            "url": "https://focuspay.org/login/telegram?ticket=dd&next=%2Fcasino",
        }
        with (
            patch.dict(sys.modules, {"handlers.captcha_handler": captcha_mod}),
            patch("handlers.start.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch("handlers.start.get_bot_user", new=AsyncMock(return_value=None)),
            patch("handlers.start.ensure_bot_user", new=AsyncMock()),
            patch("handlers.start._approve_pending_gated_joins", new=AsyncMock()),
            patch("services.config_rates.TELEGRAM_ADMIN_IDS", []),
            patch(
                "handlers.casino_login.attach_telegram_to_start",
                new=AsyncMock(return_value=attached),
            ),
            patch("handlers.ops_bind.extract_ops_bind_token", return_value=None),
        ):
            await start_handler(update, context)
        captcha_mod.send_captcha.assert_awaited_once()
        texts = [c.args[0] for c in msg.reply_text.await_args_list if c.args]
        self.assertTrue(any("FocusBet" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
