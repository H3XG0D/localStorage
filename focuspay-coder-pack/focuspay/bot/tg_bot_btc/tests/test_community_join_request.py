"""Тесты автоприёма заявок в focus чат."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.community_join_request import (
    community_join_request_handler,
    is_eligible_for_community,
)
from services.community_join_actions import (
    bot_community_start_url,
    try_approve_community_join,
)
from telegram.error import BadRequest


class CommunityEligibilityTests(unittest.TestCase):
    def test_bot_user_allowed(self):
        self.assertTrue(
            is_eligible_for_community(123, bot_user_row={"user_id": 123}, admin_ids=frozenset())
        )

    def test_unknown_user_denied(self):
        self.assertFalse(
            is_eligible_for_community(999, bot_user_row=None, admin_ids=frozenset())
        )

    def test_admin_allowed_without_bot_user(self):
        self.assertTrue(
            is_eligible_for_community(
                1, bot_user_row=None, admin_ids=frozenset({1, 2})
            )
        )


class CommunityJoinHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_user_not_declined_and_gets_dm(self):
        req = MagicMock()
        req.from_user.id = 999
        req.chat.id = -1004058942735
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
                "handlers.community_join_request.is_community_chat",
                return_value=True,
            ),
            patch(
                "handlers.community_join_request.get_bot_user",
                new=AsyncMock(return_value=None),
            ),
        ):
            await community_join_request_handler(update, context)

        req.decline.assert_not_called()
        req.approve.assert_not_called()
        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], 888777666)
        self.assertIn("сохранена", kwargs["text"])
        self.assertIn("community", kwargs["reply_markup"].inline_keyboard[0][0].url)

    async def test_eligible_user_approved_via_helper(self):
        req = MagicMock()
        req.from_user.id = 123
        req.chat.id = -1004058942735
        req.user_chat_id = 123
        req.decline = AsyncMock()

        update = MagicMock()
        update.chat_join_request = req

        context = MagicMock()
        context.bot = MagicMock()

        with (
            patch(
                "handlers.community_join_request.is_community_chat",
                return_value=True,
            ),
            patch(
                "handlers.community_join_request.get_bot_user",
                new=AsyncMock(return_value={"user_id": 123}),
            ),
            patch(
                "handlers.community_join_request.try_approve_community_join",
                new=AsyncMock(return_value="approved"),
            ) as approve_mock,
        ):
            await community_join_request_handler(update, context)

        req.decline.assert_not_called()
        approve_mock.assert_awaited_once_with(context.bot, 123, chat_id=-1004058942735)


class TryApproveCommunityJoinTests(unittest.IsolatedAsyncioTestCase):
    async def test_approved_on_success(self):
        bot = MagicMock()
        bot.approve_chat_join_request = AsyncMock(return_value=True)

        with patch(
            "services.community_join_actions.community_chat_id",
            return_value=-1004058942735,
        ):
            result = await try_approve_community_join(bot, 123)

        self.assertEqual(result, "approved")

    async def test_no_request_on_hide_requester_missing(self):
        bot = MagicMock()
        bot.approve_chat_join_request = AsyncMock(
            side_effect=BadRequest("Bad Request: HIDE_REQUESTER_MISSING")
        )

        with patch(
            "services.community_join_actions.community_chat_id",
            return_value=-1004058942735,
        ):
            result = await try_approve_community_join(bot, 123)

        self.assertEqual(result, "no_request")

    async def test_channels_blocked(self):
        bot = MagicMock()
        bot.approve_chat_join_request = AsyncMock(
            side_effect=BadRequest("Bad Request: USER_CHANNELS_TOO_MUCH")
        )
        bot.send_message = AsyncMock()

        with patch(
            "services.community_join_actions.community_chat_id",
            return_value=-1004058942735,
        ):
            result = await try_approve_community_join(bot, 123)

        self.assertEqual(result, "channels_blocked")
        bot.send_message.assert_awaited_once()


class BotCommunityStartUrlTests(unittest.TestCase):
    def test_builds_deep_link(self):
        self.assertEqual(
            bot_community_start_url("focuspay1_bot"),
            "https://t.me/focuspay1_bot?start=community",
        )


if __name__ == "__main__":
    unittest.main()
