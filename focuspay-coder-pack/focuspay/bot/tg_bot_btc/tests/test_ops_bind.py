"""opsbind_ / /ops_bind: парсинг токена, ответы хендлера, ссылка /ops/profile."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.ops_bind import (
    OPS_BIND_CB,
    complete_ops_bind,
    maybe_handle_ops_bind,
    ops_bind_command,
    ops_profile_callback,
)
from services.ops_bind import extract_ops_bind_token, ops_profile_url


def _update(text="/ops_bind ABCDEFGH12", uid=99):
    user = SimpleNamespace(id=uid, username="op")
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


class ExtractTokenTests(unittest.TestCase):
    def test_opsbind_prefix_and_command(self):
        self.assertEqual(extract_ops_bind_token("opsbind_ABCDEFGH12"), "ABCDEFGH12")
        self.assertEqual(extract_ops_bind_token("/start opsbind_ABCDEFGH12"), "ABCDEFGH12")
        self.assertEqual(extract_ops_bind_token("/ops_bind ABCDEFGH12"), "ABCDEFGH12")
        self.assertEqual(
            extract_ops_bind_token("abcdefgh12", allow_bare=True), "ABCDEFGH12"
        )
        self.assertIsNone(extract_ops_bind_token("abcdefgh12"))
        self.assertIsNone(extract_ops_bind_token("short"))
        self.assertIsNone(extract_ops_bind_token("/start ref_abc123xyz"))
        self.assertIsNone(extract_ops_bind_token("ref_abc123xyz999"))
        self.assertIsNone(extract_ops_bind_token(""))
        self.assertIsNone(extract_ops_bind_token(None))

    def test_profile_url(self):
        with patch("services.ops_bind.operator_url", return_value="https://focuspay.org/ops/profile"):
            self.assertEqual(ops_profile_url(), "https://focuspay.org/ops/profile")
        self.assertTrue(ops_profile_url().endswith("/ops/profile"))


class OpsBindHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_mentions_ops_profile(self):
        update, msg, user = _update()
        row = {"id": 1, "username": "alice", "display_name": "Alice"}
        with (
            patch(
                "handlers.ops_bind.bind_operator_telegram_by_token",
                new=AsyncMock(return_value=row),
            ),
            patch("handlers.ops_bind.main_menu_keyboard", new=AsyncMock(return_value="menu")),
            patch("handlers.ops_bind.ops_profile_url", return_value="https://focuspay.org/ops/profile"),
        ):
            ok = await complete_ops_bind(update, "opsbind_ABCDEFGH12")
        self.assertTrue(ok)
        text = msg.reply_text.await_args_list[0].args[0]
        self.assertIn("/ops/profile", text)
        self.assertIn("привязан", text.lower())

    async def test_expired_token_explains_auth_not_silent(self):
        update, msg, user = _update()
        with (
            patch(
                "handlers.ops_bind.bind_operator_telegram_by_token",
                new=AsyncMock(return_value=None),
            ),
            patch("handlers.ops_bind.main_menu_keyboard", new=AsyncMock(return_value="menu")),
            patch("handlers.ops_bind.ops_profile_url", return_value="https://focuspay.org/ops/profile"),
        ):
            ok = await complete_ops_bind(update, "opsbind_EXPIRED01")
        self.assertTrue(ok)
        text = msg.reply_text.await_args_list[0].args[0]
        self.assertIn("истекла", text.lower() + " " + text)
        self.assertIn("/ops/profile", text)

    async def test_exception_is_logged_and_replies(self):
        update, msg, user = _update()
        with (
            patch(
                "handlers.ops_bind.bind_operator_telegram_by_token",
                new=AsyncMock(side_effect=RuntimeError("db")),
            ),
            patch("handlers.ops_bind.main_menu_keyboard", new=AsyncMock(return_value="menu")),
            patch("handlers.ops_bind.ops_profile_url", return_value="https://focuspay.org/ops/profile"),
        ):
            ok = await complete_ops_bind(update, "opsbind_ABCDEFGH12")
        self.assertTrue(ok)
        text = msg.reply_text.await_args_list[0].args[0]
        self.assertIn("ошибки", text.lower())

    async def test_command_without_args_shows_usage(self):
        update, msg, user = _update(text="/ops_bind")
        context = SimpleNamespace(args=[])
        with patch("handlers.ops_bind.rate_limit_ok", new=AsyncMock(return_value=True)):
            await ops_bind_command(update, context)
        text = msg.reply_text.await_args.args[0]
        self.assertIn("/ops_bind", text)
        self.assertIn("/ops/profile", text)

    async def test_start_payload_handled(self):
        update, msg, user = _update(text="/start opsbind_ABCDEFGH12")
        context = SimpleNamespace(args=["opsbind_ABCDEFGH12"], user_data={})
        with (
            patch(
                "handlers.ops_bind.bind_operator_telegram_by_token",
                new=AsyncMock(return_value={"username": "bob", "display_name": "Bob"}),
            ),
            patch("handlers.ops_bind.main_menu_keyboard", new=AsyncMock(return_value="menu")),
        ):
            self.assertTrue(await maybe_handle_ops_bind(update, context))

    async def test_non_ops_payload_ignored(self):
        update, msg, user = _update(text="/start ref_abc")
        context = SimpleNamespace(args=["ref_abc123xyz999"], user_data={})
        self.assertFalse(await maybe_handle_ops_bind(update, context))
        msg.reply_text.assert_not_awaited()

    async def test_ops_profile_callback_answers_and_links(self):
        user = SimpleNamespace(id=7, username="op")
        msg = SimpleNamespace(reply_text=AsyncMock())
        query = SimpleNamespace(data=OPS_BIND_CB, message=msg, answer=AsyncMock(), from_user=user)
        update = SimpleNamespace(
            callback_query=query,
            effective_user=user,
            message=None,
        )
        with (
            patch("handlers.ops_bind.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch("handlers.ops_bind.ops_profile_url", return_value="https://focuspay.org/ops/profile"),
        ):
            await ops_profile_callback(update, SimpleNamespace())
        query.answer.assert_awaited()
        text = msg.reply_text.await_args.args[0]
        self.assertIn("/ops/profile", text)
        self.assertIn("сесси", text.lower())


class BindDbTests(unittest.IsolatedAsyncioTestCase):
    async def test_bind_uses_stripped_token(self):
        from services.ops_bind import bind_operator_telegram_by_token

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"id": 3, "username": "op", "display_name": "Op", "telegram_user_id": None, "telegram_bind_expires_at": None},
                {
                    "id": 3,
                    "username": "op",
                    "display_name": "Op",
                    "telegram_user_id": 99,
                    "ops_ai_digest_enabled": True,
                    "ops_ai_digest_hour": 10,
                },
            ]
        )
        conn.execute = AsyncMock()
        pool = MagicMock()
        pool.acquire = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        with patch("services.ops_bind.get_pool", new=AsyncMock(return_value=pool)):
            row = await bind_operator_telegram_by_token("opsbind_ABCDEFGH12", 99)
        self.assertEqual(row["id"], 3)
        first_sql_args = conn.fetchrow.await_args_list[0].args
        self.assertEqual(first_sql_args[1], "ABCDEFGH12")


if __name__ == "__main__":
    unittest.main()
