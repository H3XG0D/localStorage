"""Тесты автоприёма заявок в новости FocusPay."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.news_join_request import (
    is_eligible_for_news,
    news_join_request_handler,
)
from services.news_join_actions import (
    bot_news_start_url,
    try_approve_news_join,
)
from telegram.error import BadRequest


class NewsEligibilityTests(unittest.TestCase):
    def test_bot_user_allowed(self):
        self.assertTrue(
            is_eligible_for_news(123, bot_user_row={"user_id": 123}, admin_ids=frozenset())
        )

    def test_unknown_user_denied(self):
        self.assertFalse(
            is_eligible_for_news(999, bot_user_row=None, admin_ids=frozenset())
        )

    def test_admin_allowed_without_bot_user(self):
        self.assertTrue(
            is_eligible_for_news(1, bot_user_row=None, admin_ids=frozenset({1, 2}))
        )


class NewsJoinHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_user_not_declined_and_gets_dm(self):
        req = MagicMock()
        req.from_user.id = 999
        req.chat.id = -100111222333
        req.user_chat_id = 888777666
        req.decline = AsyncMock()
        req.approve = AsyncMock()

        update = MagicMock()
        update.chat_join_request = req

        bot = MagicMock()
        bot.username = "focuspay1_bot"
        bot.send_message = AsyncMock()

        context = MagicMock()
        context.bot = bot

        with (
            patch(
                "handlers.news_join_request.is_news_chat",
                return_value=True,
            ),
            patch(
                "handlers.news_join_request.get_bot_user",
                new=AsyncMock(return_value=None),
            ),
        ):
            await news_join_request_handler(update, context)

        req.decline.assert_not_called()
        req.approve.assert_not_called()
        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], 888777666)
        self.assertIn("сохранена", kwargs["text"])
        self.assertIn("news", kwargs["reply_markup"].inline_keyboard[0][0].url)

    async def test_eligible_user_approved_via_helper(self):
        req = MagicMock()
        req.from_user.id = 123
        req.chat.id = -100111222333
        req.user_chat_id = 123
        req.decline = AsyncMock()

        update = MagicMock()
        update.chat_join_request = req

        context = MagicMock()
        context.bot = MagicMock()

        with (
            patch(
                "handlers.news_join_request.is_news_chat",
                return_value=True,
            ),
            patch(
                "handlers.news_join_request.get_bot_user",
                new=AsyncMock(return_value={"user_id": 123}),
            ),
            patch(
                "handlers.news_join_request.try_approve_news_join",
                new=AsyncMock(return_value="approved"),
            ) as approve_mock,
        ):
            await news_join_request_handler(update, context)

        req.decline.assert_not_called()
        approve_mock.assert_awaited_once_with(context.bot, 123, chat_id=-100111222333)

    async def test_ignores_non_news_chat(self):
        req = MagicMock()
        req.from_user.id = 123
        req.chat.id = -100999
        req.approve = AsyncMock()
        req.decline = AsyncMock()

        update = MagicMock()
        update.chat_join_request = req
        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()

        with (
            patch(
                "handlers.news_join_request.is_news_chat",
                return_value=False,
            ),
            patch(
                "handlers.news_join_request.get_bot_user",
                new=AsyncMock(),
            ) as get_user,
        ):
            await news_join_request_handler(update, context)

        get_user.assert_not_called()
        req.approve.assert_not_called()
        req.decline.assert_not_called()
        context.bot.send_message.assert_not_called()


class TryApproveNewsJoinTests(unittest.IsolatedAsyncioTestCase):
    async def test_approved_on_success(self):
        bot = MagicMock()
        bot.approve_chat_join_request = AsyncMock(return_value=True)

        with patch(
            "services.news_join_actions.news_chat_id",
            return_value=-100111222333,
        ):
            result = await try_approve_news_join(bot, 123)

        self.assertEqual(result, "approved")

    async def test_no_request_on_hide_requester_missing(self):
        bot = MagicMock()
        bot.approve_chat_join_request = AsyncMock(
            side_effect=BadRequest("Bad Request: HIDE_REQUESTER_MISSING")
        )

        with patch(
            "services.news_join_actions.news_chat_id",
            return_value=-100111222333,
        ):
            result = await try_approve_news_join(bot, 123)

        self.assertEqual(result, "no_request")

    async def test_channels_blocked(self):
        bot = MagicMock()
        bot.approve_chat_join_request = AsyncMock(
            side_effect=BadRequest("Bad Request: USER_CHANNELS_TOO_MUCH")
        )
        bot.send_message = AsyncMock()

        with patch(
            "services.news_join_actions.news_chat_id",
            return_value=-100111222333,
        ):
            result = await try_approve_news_join(bot, 123)

        self.assertEqual(result, "channels_blocked")
        bot.send_message.assert_awaited_once()


class BotNewsStartUrlTests(unittest.TestCase):
    def test_builds_deep_link(self):
        self.assertEqual(
            bot_news_start_url("focuspay1_bot"),
            "https://t.me/focuspay1_bot?start=news",
        )


if __name__ == "__main__":
    unittest.main()
