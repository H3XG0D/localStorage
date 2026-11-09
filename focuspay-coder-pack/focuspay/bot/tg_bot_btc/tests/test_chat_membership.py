"""Членство покупателя в focus-чате / отзывах / новостях для проверки клиента."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import BadRequest, Forbidden

from services.account_review import _build_checklist_html
from services.chat_membership import (
    format_membership_checklist_lines,
    public_chat_membership,
    user_in_chat,
)


class UserInChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_unconfigured(self):
        self.assertEqual(await user_in_chat(MagicMock(), 0, 1), "unconfigured")
        self.assertEqual(await user_in_chat(MagicMock(), None, 1), "unconfigured")

    async def test_member_in(self):
        bot = MagicMock()
        bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))
        self.assertEqual(await user_in_chat(bot, -1001, 42), "in")

    async def test_admin_in(self):
        bot = MagicMock()
        bot.get_chat_member = AsyncMock(return_value=MagicMock(status="administrator"))
        self.assertEqual(await user_in_chat(bot, "@focuspayr", 42), "in")

    async def test_left_out(self):
        bot = MagicMock()
        bot.get_chat_member = AsyncMock(return_value=MagicMock(status="left"))
        self.assertEqual(await user_in_chat(bot, -1001, 42), "out")

    async def test_user_not_participant_out(self):
        bot = MagicMock()
        bot.get_chat_member = AsyncMock(
            side_effect=BadRequest("Bad Request: USER_NOT_PARTICIPANT")
        )
        self.assertEqual(await user_in_chat(bot, -1001, 42), "out")

    async def test_forbidden_unknown(self):
        bot = MagicMock()
        bot.get_chat_member = AsyncMock(side_effect=Forbidden("bot is not a member"))
        self.assertEqual(await user_in_chat(bot, -1001, 42), "unknown")

    async def test_no_bot_unknown(self):
        self.assertEqual(await user_in_chat(None, -1001, 42), "unknown")


class FormatMembershipLinesTests(unittest.TestCase):
    def test_mixed_statuses(self):
        lines = format_membership_checklist_lines(
            {"community": "in", "reviews": "out", "news": "unconfigured"}
        )
        self.assertEqual(
            lines,
            [
                "✅ Focus-чат: в группе",
                "❌ Отзывы: нет",
                "❔ Новости: чат не привязан",
            ],
        )

    def test_empty(self):
        self.assertEqual(format_membership_checklist_lines(None), [])
        self.assertEqual(format_membership_checklist_lines({}), [])


class PublicChatMembershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_queries_all_three_chats(self):
        bot = MagicMock()
        bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))
        with (
            patch(
                "services.config_rates.community_chat_id",
                return_value=-100111,
            ),
            patch(
                "services.config_rates.reviews_chat_id",
                return_value="@focuspayr",
            ),
            patch(
                "services.config_rates.news_chat_id",
                return_value=0,
            ),
        ):
            result = await public_chat_membership(bot, 99)

        self.assertEqual(result["community"], "in")
        self.assertEqual(result["reviews"], "in")
        self.assertEqual(result["news"], "unconfigured")
        self.assertEqual(bot.get_chat_member.await_count, 2)


class ChecklistMembershipTests(unittest.TestCase):
    def test_checklist_includes_membership_lines(self):
        lines = _build_checklist_html(
            bot_user={"username": "buyer", "first_name": "Ivan"},
            reasons=[],
            has_avatar=True,
            avatar_count=1,
            is_premium=False,
            first_name="Ivan",
            wallet_reuse=False,
            has_ref=True,
            membership={"community": "out", "reviews": "in", "news": "unknown"},
        )
        joined = "\n".join(lines)
        self.assertIn("❌ Focus-чат: нет", joined)
        self.assertIn("✅ Отзывы: подписан", joined)
        self.assertIn("❔ Новости: неизвестно", joined)


if __name__ == "__main__":
    unittest.main()
