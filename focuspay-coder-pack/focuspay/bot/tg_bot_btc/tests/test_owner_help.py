""" /help и /dash: молчать вне группы отчётов, отказ только внутри неё. """
from __future__ import annotations

import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.owner_dashboard import owner_dash_handler, owner_help_handler


def _update(chat_id: int, user_id: int, username: str | None = "alice"):
    user = SimpleNamespace(id=user_id, username=username)
    msg = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(
        message=msg,
        effective_message=msg,
        effective_user=user,
        effective_chat=SimpleNamespace(id=chat_id, title="FocusPay"),
    ), msg


def _patches(*, reports_chat: bool, admin_ids: list[int], reports_user: bool):
    stack = ExitStack()
    stack.enter_context(
        patch(
            "handlers.owner_dashboard.reply_wrong_reports_group",
            new=AsyncMock(return_value=False),
        )
    )
    stack.enter_context(
        patch(
            "handlers.owner_dashboard.config_rates.is_reports_group_chat",
            return_value=reports_chat,
        )
    )
    stack.enter_context(
        patch("handlers.owner_dashboard.config_rates.TELEGRAM_ADMIN_IDS", admin_ids)
    )
    stack.enter_context(
        patch(
            "handlers.owner_dashboard.config_rates.is_reports_user",
            return_value=reports_user,
        )
    )
    return stack


class OwnerHelpSilenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_help_silent_in_community_chat(self):
        update, msg = _update(chat_id=-1004058942735, user_id=4242)
        with _patches(reports_chat=False, admin_ids=[111], reports_user=False):
            await owner_help_handler(update, SimpleNamespace(args=[]))
        msg.reply_text.assert_not_awaited()

    async def test_help_deny_only_in_reports_group(self):
        update, msg = _update(chat_id=-5272708942, user_id=4242)
        with _patches(reports_chat=True, admin_ids=[111], reports_user=False):
            await owner_help_handler(update, SimpleNamespace(args=[]))
        msg.reply_text.assert_awaited_once()
        self.assertIn("Нет доступа", msg.reply_text.await_args.args[0])

    async def test_help_shows_text_for_reports_user(self):
        update, msg = _update(chat_id=-5272708942, user_id=111)
        with _patches(reports_chat=True, admin_ids=[111], reports_user=True):
            await owner_help_handler(update, SimpleNamespace(args=[]))
        msg.reply_text.assert_awaited_once()
        text = msg.reply_text.await_args.args[0]
        self.assertIn("/dash", text)
        self.assertNotIn("Нет доступа", text)

    async def test_dash_silent_in_community_chat(self):
        update, msg = _update(chat_id=-1004058942735, user_id=4242)
        with _patches(reports_chat=False, admin_ids=[111], reports_user=False):
            await owner_dash_handler(update, SimpleNamespace(args=[]))
        msg.reply_text.assert_not_awaited()

    async def test_help_real_guard_silent_for_stranger(self):
        update, msg = _update(chat_id=-1004058942735, user_id=4242)
        with (
            patch(
                "handlers.owner_dashboard.config_rates.is_reports_group_chat",
                return_value=False,
            ),
            patch(
                "services.reports_group_guard.config_rates.is_reports_group_chat",
                return_value=False,
            ),
            patch("handlers.owner_dashboard.config_rates.TELEGRAM_ADMIN_IDS", [111]),
            patch(
                "handlers.owner_dashboard.config_rates.is_reports_user",
                return_value=False,
            ),
        ):
            await owner_help_handler(update, SimpleNamespace(args=[]))
        msg.reply_text.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
