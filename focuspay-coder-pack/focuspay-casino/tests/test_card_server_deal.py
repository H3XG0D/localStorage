import importlib
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.telebot_stub import TelebotModules


with TelebotModules("games.baccara", "games.blackjack", "games.table_wizard", "games.v2_tables", "games.v2_runtime"):
    baccara = importlib.import_module("games.baccara")
    blackjack = importlib.import_module("games.blackjack")


class HandlerBot:
    def __init__(self):
        self.callback_handlers = []
        self.message_handlers = []
        self.send_message = AsyncMock(
            return_value=SimpleNamespace(message_id=71, chat=SimpleNamespace(id=11))
        )
        self.edit_message_text = AsyncMock()
        self.answer_callback_query = AsyncMock()
        self.reply_to = AsyncMock()

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


def join_call(*, data, user_id):
    return SimpleNamespace(
        id="callback-id",
        data=data,
        message=SimpleNamespace(chat=SimpleNamespace(id=-100123)),
        from_user=SimpleNamespace(id=user_id, first_name="Opp", username=None),
    )


class CardServerDealTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        baccara.active_games.clear()
        blackjack.active_games.clear()

    def tearDown(self):
        baccara.active_games.clear()
        blackjack.active_games.clear()

    def _waiting_baccara(self):
        return {
            "game_id": 1,
            "settlement_game_id": "baccara-1",
            "creator_id": 11,
            "creator_name": "Creator",
            "opponent_id": None,
            "opponent_name": None,
            "bet": 30,
            "deck_creator": [],
            "deck_opponent": [],
            "cards_creator": [],
            "cards_opponent": [],
            "decision_creator": None,
            "decision_opponent": None,
            "msg_id_creator": None,
            "msg_id_opponent": None,
            "chat_id_creator": -100123,
            "chat_id_opponent": None,
            "status": "waiting",
            "created_at": datetime.utcnow(),
            "started_at": None,
            "state_version": 1,
            "rng_commit": "a" * 64,
        }

    async def test_baccara_join_deals_two_cards_from_backend_not_a_local_deck(self):
        bot = HandlerBot()
        client = AsyncMock()
        client.get_active_game_chat_binding.return_value = {"chat_id": -100123}
        client.join_and_hold_game.return_value = {"state_version": 2, "status": "active"}
        client.persist_game_state.return_value = {"state_version": 3, "status": "active"}
        client.deal_cards.side_effect = [
            {"cards": ["A♠", "9♥"], "rng_commit": "a" * 64},
            {"cards": ["K♦", "2♣"], "rng_commit": "a" * 64},
        ]
        baccara.register_baccara_handlers(bot, client)
        baccara.active_games[1] = self._waiting_baccara()

        await callback_for(bot, "bak_join_1")(join_call(data="bak_join_1", user_id=22))

        self.assertEqual(client.deal_cards.await_count, 2)
        self.assertEqual(client.deal_cards.await_args_list[0].kwargs["hand_size"], 2)
        self.assertEqual(client.deal_cards.await_args_list[0].kwargs["telegram_id"], 11)
        self.assertEqual(client.deal_cards.await_args_list[1].kwargs["telegram_id"], 22)
        game = baccara.active_games[1]
        self.assertEqual(game["cards_creator"], ["A♠", "9♥"])
        self.assertEqual(game["cards_opponent"], ["K♦", "2♣"])
        self.assertEqual(game["deck_creator"], [])
        self.assertEqual(game["deck_opponent"], [])

    async def test_web_baccarat_join_callback_adopts_durable_id(self):
        bot = HandlerBot()
        client = AsyncMock()
        client.get_active_game_chat_binding.return_value = {"chat_id": -100123}
        client.get_active_pvp_games.return_value = [{
            "game_id": "web-03e1a2745423",
            "game_type": "baccara",
            "status": "waiting",
            "state_version": 1,
            "creator_id": 11,
            "stake_rub": "100.00",
            "created_at": datetime.utcnow().isoformat(),
        }]
        client.join_and_hold_game.return_value = {"state_version": 2, "status": "active"}
        client.persist_game_state.return_value = {"state_version": 3, "status": "active"}
        client.deal_cards.side_effect = [
            {"cards": ["A♠", "9♥"], "rng_commit": "a" * 64},
            {"cards": ["K♦", "2♣"], "rng_commit": "a" * 64},
        ]
        baccara.register_baccara_handlers(bot, client)
        baccara.game_counter = 0

        await callback_for(bot, "bak_wjoin_web-03e1a2745423")(
            join_call(data="bak_wjoin_web-03e1a2745423", user_id=22)
        )

        client.join_and_hold_game.assert_awaited_once_with(game_id="web-03e1a2745423", opponent_id=22)
        cached = next(iter(baccara.active_games.values()))
        self.assertEqual(cached["cards_creator"], ["A♠", "9♥"])
        self.assertEqual(cached["status"], "playing")

    async def test_web_baccarat_join_announces_when_backend_already_settled(self):
        bot = HandlerBot()
        client = AsyncMock()
        client.get_active_game_chat_binding.return_value = {"chat_id": -100123}
        client.get_active_pvp_games.return_value = [{
            "game_id": "web-f31b85ae252f",
            "game_type": "baccara",
            "status": "waiting",
            "state_version": 1,
            "creator_id": 11,
            "stake_rub": "50.00",
            "created_at": datetime.utcnow().isoformat(),
        }]
        client.persist_game_state.return_value = {"state_version": 3, "status": "active"}
        client.join_and_hold_game.return_value = {
            "state_version": 7,
            "status": "finished",
            "game": {
                "status": "finished",
                "state_version": 7,
                "outcome": {
                    "kind": "winner",
                    "winner_id": 11,
                    "creator_cards": ["2♣", "Q♣"],
                    "opponent_cards": ["4♦", "7♣", "K♠"],
                    "creator_score": 2,
                    "opponent_score": 1,
                },
            },
        }
        client.settle_committed_outcome.return_value = {
            "state_version": 7,
            "status": "finished",
            "payout_rub": "97.50",
            "game": {"status": "finished", "state_version": 7},
        }
        client.reveal_cards.return_value = {"rng_seed": "ab" * 32}
        baccara.register_baccara_handlers(bot, client)
        baccara.game_counter = 0

        await callback_for(bot, "bak_wjoin_web-f31b85ae252f")(
            join_call(data="bak_wjoin_web-f31b85ae252f", user_id=22)
        )

        client.deal_cards.assert_not_awaited()
        self.assertEqual(baccara.active_games, {})
        self.assertTrue(bot.send_message.await_count >= 2)
        sent = "\n".join(str(call.args[1]) for call in bot.send_message.await_args_list if len(call.args) > 1)
        self.assertIn("Результаты Baccara", sent)
        self.assertIn("2♣", sent)

    async def test_baccara_hit_asks_backend_for_the_next_card(self):
        bot = HandlerBot()
        client = AsyncMock()
        client.persist_game_state.return_value = {"state_version": 4, "status": "active"}
        client.deal_cards.return_value = {"cards": ["A♠", "9♥", "3♦"], "rng_commit": "a" * 64}
        baccara.register_baccara_handlers(bot, client)
        baccara.active_games[1] = {
            **self._waiting_baccara(),
            "opponent_id": 22,
            "opponent_name": "Opp",
            "cards_creator": ["A♠", "9♥"],
            "cards_opponent": ["K♦", "2♣"],
            "status": "playing",
            "started_at": datetime.utcnow(),
            "chat_id_creator": 11,
            "msg_id_creator": 71,
            "state_version": 3,
        }

        await callback_for(bot, "bak_hit_1")(
            join_call(data="bak_hit_1", user_id=11)
        )

        client.deal_cards.assert_awaited_once()
        self.assertEqual(client.deal_cards.await_args.kwargs["hand_size"], 3)
        self.assertEqual(baccara.active_games[1]["cards_creator"], ["A♠", "9♥", "3♦"])

    async def test_blackjack_join_deals_one_card_each_from_backend(self):
        bot = HandlerBot()
        client = AsyncMock()
        client.get_active_game_chat_binding.return_value = {"chat_id": -100123}
        client.join_and_hold_game.return_value = {"state_version": 2, "status": "active"}
        client.persist_game_state.return_value = {"state_version": 3, "status": "active"}
        client.deal_cards.side_effect = [
            {"cards": ["10♠"], "rng_commit": "b" * 64},
            {"cards": ["7♥"], "rng_commit": "b" * 64},
        ]
        blackjack.register_blackjack_handlers(bot, client)
        blackjack.active_games[1] = {
            "game_id": 1,
            "settlement_game_id": "blackjack-1",
            "creator_id": 11,
            "creator_name": "Creator",
            "opponent_id": None,
            "opponent_name": None,
            "bet": 30,
            "deck_creator": [],
            "deck_opponent": [],
            "cards_creator": [],
            "cards_opponent": [],
            "ace_values_creator": [],
            "ace_values_opponent": [],
            "status_creator": None,
            "status_opponent": None,
            "msg_id_creator": None,
            "msg_id_opponent": None,
            "chat_id_creator": -100123,
            "chat_id_opponent": None,
            "pending_ace_creator": False,
            "pending_ace_opponent": False,
            "status": "waiting",
            "created_at": datetime.utcnow(),
            "started_at": None,
            "state_version": 1,
            "rng_commit": "b" * 64,
        }

        await callback_for(bot, "bj_join_1")(join_call(data="bj_join_1", user_id=22))

        self.assertEqual(client.deal_cards.await_count, 2)
        self.assertEqual(client.deal_cards.await_args_list[0].kwargs["hand_size"], 1)
        self.assertEqual(blackjack.active_games[1]["cards_creator"], ["10♠"])
        self.assertEqual(blackjack.active_games[1]["cards_opponent"], ["7♥"])
