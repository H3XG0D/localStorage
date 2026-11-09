import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from games.chat_guard import ActiveGameChatGuard, GAME_CHAT_REQUIRED_MESSAGE


class ActiveGameChatGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = SimpleNamespace(
            get_active_game_chat_binding=AsyncMock(return_value={"chat_id": -100123})
        )
        self.bot = SimpleNamespace(
            reply_to=AsyncMock(),
            answer_callback_query=AsyncMock(),
            delete_message=AsyncMock(),
        )
        self.guard = ActiveGameChatGuard(self.client)

    async def test_allows_only_backend_bound_chat(self):
        self.assertTrue(await self.guard.allows_chat(-100123))
        self.assertFalse(await self.guard.allows_chat(-100456))
        self.client.get_active_game_chat_binding.assert_awaited()

    async def test_fails_closed_when_binding_is_missing_or_unavailable(self):
        self.client.get_active_game_chat_binding.return_value = None
        self.assertFalse(await self.guard.allows_chat(-100123))

        self.client.get_active_game_chat_binding.side_effect = RuntimeError("unavailable")
        self.assertFalse(await self.guard.allows_chat(-100123))

    async def test_allows_player_private_chat_even_when_binding_is_a_group(self):
        message = SimpleNamespace(
            chat=SimpleNamespace(id=777, type="private"),
            from_user=SimpleNamespace(id=777),
        )
        callback = SimpleNamespace(
            id="callback-id",
            from_user=SimpleNamespace(id=777),
            message=SimpleNamespace(chat=SimpleNamespace(id=777, type="private")),
        )
        self.assertTrue(await self.guard.require_message(self.bot, message))
        self.bot.reply_to.assert_not_awaited()
        self.assertTrue(await self.guard.require_callback(self.bot, callback))
        self.bot.answer_callback_query.assert_not_awaited()

    async def test_denied_message_and_callback_receive_their_native_feedback(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=-100456))
        callback = SimpleNamespace(
            id="callback-id",
            message=SimpleNamespace(chat=SimpleNamespace(id=-100456)),
        )

        self.assertFalse(await self.guard.require_message(self.bot, message))
        self.bot.reply_to.assert_awaited_once_with(message, GAME_CHAT_REQUIRED_MESSAGE)

        self.assertFalse(await self.guard.require_callback(self.bot, callback))
        self.bot.answer_callback_query.assert_awaited_once_with(
            "callback-id", GAME_CHAT_REQUIRED_MESSAGE, show_alert=True
        )

    async def test_allows_string_bound_id_and_dict_callback_chat(self):
        self.client.get_active_game_chat_binding.return_value = {"chat_id": "-100123"}
        self.assertTrue(await self.guard.allows_chat(-100123))
        callback = SimpleNamespace(
            id="callback-id",
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat={"id": -100123, "type": "supergroup"}),
        )
        self.assertTrue(await self.guard.require_callback(self.bot, callback))
        self.bot.answer_callback_query.assert_not_awaited()

    async def test_allows_migrated_supergroup_alias_of_bound_group(self):
        self.client.get_active_game_chat_binding.return_value = {"chat_id": -5562276559}
        self.assertTrue(await self.guard.allows_chat(-1005562276559))
        callback = SimpleNamespace(
            id="callback-id",
            from_user=SimpleNamespace(id=7),
            message={"chat": {"id": -1005562276559, "type": "supergroup"}, "message_id": 4},
        )
        self.assertTrue(await self.guard.require_callback(self.bot, callback))
        self.bot.answer_callback_query.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
