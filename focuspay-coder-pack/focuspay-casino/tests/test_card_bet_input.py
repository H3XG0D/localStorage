import asyncio
import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules


with TelebotModules("games.baccara", "games.blackjack", "games.table_wizard", "games.v2_tables", "games.v2_runtime", "games.site_links"):
    baccara = importlib.import_module("games.baccara")
    blackjack = importlib.import_module("games.blackjack")


class HandlerBot:
    def __init__(self):
        self.callback_handlers = []
        self.message_handlers = []
        self.send_message = AsyncMock(return_value=SimpleNamespace(message_id=71))
        self.answer_callback_query = AsyncMock()
        self.reply_to = AsyncMock()
        self.delete_message = AsyncMock()

    def callback_query_handler(self, *, func):
        def register(handler):
            self.callback_handlers.append((func, handler))
            return handler

        return register

    def message_handler(self, **kwargs):
        def register(handler):
            self.message_handlers.append((kwargs, handler))
            return handler

        return register


def callback_for(bot, data):
    return next(handler for predicate, handler in bot.callback_handlers if predicate(SimpleNamespace(data=data)))


def matching_text_handlers(bot, message):
    return [
        handler
        for kwargs, handler in bot.message_handlers
        if "commands" not in kwargs and kwargs.get("func", lambda _message: False)(message)
    ]


def ready_client(*, game_key: str, commit: str):
    client = AsyncMock()
    client.get_active_game_chat_binding.return_value = {"chat_id": -100123}
    client.get_casino_settings.return_value = {
        "enabled_games": {game_key: True},
        "min_bet_rub": 30,
        "max_bet_rub": 100000,
    }
    client.get_balance.return_value = 800
    client.prepare_cards.return_value = {"success": True, "rng_commit": commit}
    client.create_or_resume_game.return_value = {"state_version": 1, "status": "waiting"}
    client.persist_game_state.return_value = {"state_version": 2}
    return client


def group_chat():
    return SimpleNamespace(id=-100123, type="supergroup")


def private_chat(user_id=11):
    return SimpleNamespace(id=user_id, type="private")


def user(user_id=11):
    return SimpleNamespace(id=user_id, first_name="Player", username=None)


def create_call(*, data: str, chat, actor=None):
    actor = actor or user()
    return SimpleNamespace(
        id="callback-id",
        data=data,
        message=SimpleNamespace(chat=chat),
        from_user=actor,
    )


class CardBetInputTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        baccara.active_games.clear()
        blackjack.active_games.clear()

    async def test_group_create_opens_unified_wizard_not_text_stake(self):
        bot = HandlerBot()
        client = ready_client(game_key="baccara", commit="a" * 64)
        baccara.register_baccara_handlers(bot, client)

        await callback_for(bot, "bak_create")(create_call(data="bak_create", chat=group_chat()))

        client.create_or_resume_game.assert_not_awaited()
        sent = bot.send_message.await_args
        self.assertIn("На сколько игроков", sent.args[1])
        keyboard = sent.kwargs["reply_markup"]
        callback_data = [button.callback_data for row in keyboard.keyboard for button in row]
        self.assertTrue(any(data.startswith("tw:") for data in callback_data))
        group_text = SimpleNamespace(text="50", chat=group_chat(), from_user=user())
        self.assertEqual(matching_text_handlers(bot, group_text), [])

    async def test_group_preset_stake_creates_durable_game(self):
        bot = HandlerBot()
        client = ready_client(game_key="baccara", commit="a" * 64)
        baccara.register_baccara_handlers(bot, client)

        with patch.object(baccara.config, "CASINO_MINIAPP_URL", "http://127.0.0.1:18081/casino/tg"):
            await callback_for(bot, "bak_stake:50")(create_call(data="bak_stake:50", chat=group_chat()))

        client.create_or_resume_game.assert_awaited_once()
        client.prepare_cards.assert_awaited_once()
        created = next(call.args[1] for call in bot.send_message.await_args_list if "Игра Baccara" in call.args[1])
        self.assertIn("Игра Baccara", created)
        self.assertIn("Смотреть на сайте", created)
        self.assertIn("/casino/duels/baccara-", created)

    async def test_group_command_with_stake_creates_game(self):
        bot = HandlerBot()
        client = ready_client(game_key="baccara", commit="a" * 64)
        baccara.register_baccara_handlers(bot, client)
        command = SimpleNamespace(
            text="/baccara 50",
            chat=group_chat(),
            from_user=user(),
        )
        handler = next(
            handler
            for kwargs, handler in bot.message_handlers
            if kwargs.get("commands") == ["baccara"]
        )
        await handler(command)
        client.create_or_resume_game.assert_not_awaited()
        bot.reply_to.assert_not_awaited()
        self.assertIn("На сколько игроков", bot.send_message.await_args.args[1])

    async def test_private_custom_stake_creates_durable_game(self):
        bot = HandlerBot()
        client = ready_client(game_key="baccara", commit="a" * 64)
        baccara.register_baccara_handlers(bot, client)
        chat = private_chat()
        await callback_for(bot, "bak_stake:custom")(create_call(data="bak_stake:custom", chat=chat))
        message = SimpleNamespace(text="100", chat=chat, from_user=user())
        handlers = matching_text_handlers(bot, message)
        self.assertEqual(len(handlers), 1)
        await handlers[0](message)
        client.create_or_resume_game.assert_awaited_once()

    async def test_blackjack_group_preset_stake_creates_durable_game(self):
        bot = HandlerBot()
        client = ready_client(game_key="blackjack", commit="b" * 64)
        blackjack.register_blackjack_handlers(bot, client)
        with patch.object(blackjack.config, "CASINO_MINIAPP_URL", "http://127.0.0.1:18081/casino/tg"):
            await callback_for(bot, "bj_stake:50")(create_call(data="bj_stake:50", chat=group_chat()))
        client.create_or_resume_game.assert_awaited_once()
        created = next(call.args[1] for call in bot.send_message.await_args_list if "Игра Blackjack" in call.args[1])
        self.assertIn("Игра Blackjack", created)
        self.assertIn("Смотреть на сайте", created)
        self.assertIn("/casino/duels/blackjack-", created)


class GroupTextDispatchTests(unittest.IsolatedAsyncioTestCase):
    def test_registered_text_handlers_ignore_group_messages(self):
        bot = HandlerBot()
        client = ready_client(game_key="baccara", commit="a" * 64)
        baccara.register_baccara_handlers(bot, client)
        blackjack.register_blackjack_handlers(bot, client)
        group_text = SimpleNamespace(text="50", chat=group_chat(), from_user=user())
        for kwargs, _handler in bot.message_handlers:
            if "commands" in kwargs:
                continue
            matcher = kwargs.get("func")
            if matcher is None:
                continue
            self.assertFalse(matcher(group_text), kwargs)


if __name__ == "__main__":
    unittest.main()
