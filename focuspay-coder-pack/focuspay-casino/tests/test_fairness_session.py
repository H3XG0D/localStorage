import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules

with TelebotModules("games.fairness", "games.card_fairness"):
    fairness = importlib.import_module("games.fairness")
    card_fairness = importlib.import_module("games.card_fairness")


class HandlerBot:
    def __init__(self):
        self.callback_handlers = []
        self.message_handlers = []
        self.send_message = AsyncMock()
        self.edit_message_text = AsyncMock()
        self.answer_callback_query = AsyncMock()

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


class CardFairnessCopyTests(unittest.TestCase):
    def test_waiting_text_shows_the_same_commit_client_seed_and_nonce(self):
        text = card_fairness.waiting_fairness_text(
            {"rng_commit": "a" * 64, "client_seed": "alice", "nonce": 3}
        )
        self.assertIn("a" * 64, text)
        self.assertIn("alice", text)
        self.assertIn("3", text)

    def test_result_fairness_text_is_a_prefilled_clickable_link(self):
        with patch.object(card_fairness.config, "CASINO_FAIRNESS_URL", "http://127.0.0.1:18081/casino/fairness"):
            text = card_fairness.result_fairness_text(
                game_type="baccara",
                game={
                    "settlement_game_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "rng_commit": "ab" * 32,
                    "client_seed": "focuspay",
                    "nonce": 3,
                },
                seed="cd" * 32,
            )
        self.assertIn('href="http://127.0.0.1:18081/casino/fairness?', text)
        self.assertIn("server_seed=", text)
        self.assertIn("commit=", text)
        self.assertIn("game_id=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", text)
        self.assertIn("nonce=3", text)
        self.assertIn("&amp;", text)
        self.assertIn("Проверить раунд", text)
        self.assertNotIn("Проверка: страница", text)

    def test_staging_builds_tunnel_link_when_env_url_is_empty(self):
        with patch.object(card_fairness.config, "CASINO_FAIRNESS_URL", ""):
            with patch.object(card_fairness.config, "ENVIRONMENT", "staging"):
                url = card_fairness.verify_url(
                    game_type="baccara",
                    game_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    commit="ab" * 32,
                    client_seed="focuspay",
                    nonce=3,
                    server_seed="cd" * 32,
                )
        self.assertTrue(url.startswith("http://127.0.0.1:18081/casino/fairness?"))
        self.assertIn("server_seed=" + "cd" * 32, url)


class FairnessCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_rotate_command_calls_backend_and_shows_previous_seed(self):
        bot = HandlerBot()
        client = AsyncMock()
        client.rotate_fairness_seeds.return_value = {
            "commit_hash": "b" * 64,
            "client_seed": "alice",
            "nonce": 0,
            "previous_server_seed": "ab" * 32,
            "previous_commit": "a" * 64,
        }
        fairness.register_fairness_handlers(bot, client)
        handler = next(
            handler
            for kwargs, handler in bot.message_handlers
            if "fairness" in kwargs.get("commands", [])
        )
        await handler(
            SimpleNamespace(
                text="/fairness rotate",
                chat=SimpleNamespace(id=11),
                from_user=SimpleNamespace(id=11),
            )
        )
        client.rotate_fairness_seeds.assert_awaited_once_with(telegram_id=11)
        sent = bot.send_message.await_args.args[1]
        self.assertIn("ab" * 32, sent)
        self.assertIn("b" * 64, sent)
