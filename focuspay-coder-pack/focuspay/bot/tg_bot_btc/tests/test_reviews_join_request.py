"""Тесты автоприёма заявок в канал отзывов FocusPay."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.reviews_join_request import (
    is_eligible_for_reviews,
    reviews_join_request_handler,
)
from services.config_rates import is_reviews_chat
from services.reviews_join_actions import (
    bot_reviews_start_url,
    try_approve_reviews_join,
)
from telegram.error import BadRequest


class ReviewsEligibilityTests(unittest.TestCase):
    def test_bot_user_allowed(self):
        self.assertTrue(
            is_eligible_for_reviews(123, bot_user_row={"user_id": 123}, admin_ids=frozenset())
        )

    def test_unknown_user_denied(self):
        self.assertFalse(
            is_eligible_for_reviews(999, bot_user_row=None, admin_ids=frozenset())
        )

    def test_admin_allowed_without_bot_user(self):
        self.assertTrue(
            is_eligible_for_reviews(
                1, bot_user_row=None, admin_ids=frozenset({1, 2})
            )
        )


class ReviewsChatMatchTests(unittest.TestCase):
    def test_matches_channel_username(self):
        self.assertTrue(is_reviews_chat(-100111, username="focuspayr"))
        self.assertTrue(is_reviews_chat(-100111, username="@FocusPayR"))

    def test_ignores_other_username(self):
        with patch("services.config_rates.reviews_chat_id", return_value=0):
            self.assertFalse(is_reviews_chat(-100111, username="otherchannel"))

    def test_matches_numeric_id(self):
        with patch("services.config_rates.reviews_chat_id", return_value=-100555):
            self.assertTrue(is_reviews_chat(-100555, username=None))
            self.assertFalse(is_reviews_chat(-100111, username=None))


class ReviewsJoinHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_user_not_declined_and_gets_dm(self):
        req = MagicMock()
        req.from_user.id = 999
        req.chat.id = -100222333444
        req.chat.username = "focuspayr"
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
                "handlers.reviews_join_request.is_reviews_chat",
                return_value=True,
            ),
            patch(
                "handlers.reviews_join_request.get_bot_user",
                new=AsyncMock(return_value=None),
            ),
        ):
            await reviews_join_request_handler(update, context)

        req.decline.assert_not_called()
        req.approve.assert_not_called()
        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], 888777666)
        self.assertIn("сохранена", kwargs["text"])
        self.assertIn("reviews", kwargs["reply_markup"].inline_keyboard[0][0].url)

    async def test_eligible_user_approved_via_helper(self):
        req = MagicMock()
        req.from_user.id = 123
        req.chat.id = -100222333444
        req.chat.username = "focuspayr"
        req.user_chat_id = 123
        req.decline = AsyncMock()

        update = MagicMock()
        update.chat_join_request = req

        context = MagicMock()
        context.bot = MagicMock()

        with (
            patch(
                "handlers.reviews_join_request.is_reviews_chat",
                return_value=True,
            ),
            patch(
                "handlers.reviews_join_request.get_bot_user",
                new=AsyncMock(return_value={"user_id": 123}),
            ),
            patch(
                "handlers.reviews_join_request.try_approve_reviews_join",
                new=AsyncMock(return_value="approved"),
            ) as approve_mock,
        ):
            await reviews_join_request_handler(update, context)

        req.decline.assert_not_called()
        approve_mock.assert_awaited_once_with(context.bot, 123, chat_id=-100222333444)

    async def test_ignores_non_reviews_chat(self):
        req = MagicMock()
        req.from_user.id = 123
        req.chat.id = -100999
        req.chat.username = "other"
        req.approve = AsyncMock()
        req.decline = AsyncMock()

        update = MagicMock()
        update.chat_join_request = req
        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()

        with (
            patch(
                "handlers.reviews_join_request.is_reviews_chat",
                return_value=False,
            ),
            patch(
                "handlers.reviews_join_request.get_bot_user",
                new=AsyncMock(),
            ) as get_user,
        ):
            await reviews_join_request_handler(update, context)

        get_user.assert_not_called()
        req.approve.assert_not_called()
        req.decline.assert_not_called()
        context.bot.send_message.assert_not_called()


class TryApproveReviewsJoinTests(unittest.IsolatedAsyncioTestCase):
    async def test_approved_on_success(self):
        bot = MagicMock()
        bot.approve_chat_join_request = AsyncMock(return_value=True)

        with patch(
            "services.reviews_join_actions.reviews_chat_id",
            return_value=-100222333444,
        ):
            result = await try_approve_reviews_join(bot, 123)

        self.assertEqual(result, "approved")
        bot.approve_chat_join_request.assert_awaited_once_with(
            chat_id=-100222333444, user_id=123
        )

    async def test_approved_with_username_chat_id(self):
        bot = MagicMock()
        bot.approve_chat_join_request = AsyncMock(return_value=True)

        with patch(
            "services.reviews_join_actions.reviews_chat_id",
            return_value="@focuspayr",
        ):
            result = await try_approve_reviews_join(bot, 123)

        self.assertEqual(result, "approved")
        bot.approve_chat_join_request.assert_awaited_once_with(
            chat_id="@focuspayr", user_id=123
        )

    async def test_no_request_on_hide_requester_missing(self):
        bot = MagicMock()
        bot.approve_chat_join_request = AsyncMock(
            side_effect=BadRequest("Bad Request: HIDE_REQUESTER_MISSING")
        )

        with patch(
            "services.reviews_join_actions.reviews_chat_id",
            return_value=-100222333444,
        ):
            result = await try_approve_reviews_join(bot, 123)

        self.assertEqual(result, "no_request")

    async def test_channels_blocked(self):
        bot = MagicMock()
        bot.approve_chat_join_request = AsyncMock(
            side_effect=BadRequest("Bad Request: USER_CHANNELS_TOO_MUCH")
        )
        bot.send_message = AsyncMock()

        with patch(
            "services.reviews_join_actions.reviews_chat_id",
            return_value=-100222333444,
        ):
            result = await try_approve_reviews_join(bot, 123)

        self.assertEqual(result, "channels_blocked")
        bot.send_message.assert_awaited_once()


class BotReviewsStartUrlTests(unittest.TestCase):
    def test_builds_deep_link(self):
        self.assertEqual(
            bot_reviews_start_url("focuspay1_bot"),
            "https://t.me/focuspay1_bot?start=reviews",
        )


if __name__ == "__main__":
    unittest.main()
