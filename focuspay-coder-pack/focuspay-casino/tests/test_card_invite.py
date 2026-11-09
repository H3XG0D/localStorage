import importlib
import unittest
from unittest.mock import AsyncMock

from tests.telebot_stub import TelebotModules


with TelebotModules("games.pvp", "games.table_wizard", "games.v2_tables", "games.v2_runtime", "games.baccara", "games.blackjack", "games.house_cub"):
    baccara = importlib.import_module("games.baccara")
    card_invite = importlib.import_module("games.card_invite")


class CardInviteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        baccara.active_games.clear()
        baccara._game_locks.clear()
        baccara.game_counter = 0

    def tearDown(self):
        baccara.active_games.clear()
        baccara._game_locks.clear()
        baccara.game_counter = 0

    async def test_hydrate_waiting_web_baccarat_into_menu_cache(self):
        client = AsyncMock()
        client.get_active_pvp_games = AsyncMock(return_value=[{
            "game_id": "web-03e1a2745423",
            "game_type": "baccara",
            "status": "waiting",
            "state_version": 2,
            "creator_id": 940002,
            "stake_rub": "100.00",
            "created_at": "2026-08-29T09:15:00+00:00",
            "rng_commit": "b" * 64,
            "game_chat_id": -100123,
        }])
        client.persist_game_state = AsyncMock(return_value={"game": {"state_version": 3}})

        game = await card_invite.hydrate_invited_card_game(
            client,
            {
                "game_id": "web-03e1a2745423",
                "game_type": "baccara",
                "chat_id": -100123,
                "stake_rub": "100",
            },
            77,
            module=baccara,
        )

        self.assertEqual(game["settlement_game_id"], "web-03e1a2745423")
        self.assertEqual(game["status"], "waiting")
        self.assertEqual(card_invite.find_gid(baccara.active_games, "web-03e1a2745423"), game["game_id"])
        self.assertEqual(card_invite.join_callback_data("baccara", "web-03e1a2745423"), "bak_wjoin_web-03e1a2745423")
        self.assertTrue(card_invite.is_site_duel_id("web-03e1a2745423"))
        self.assertFalse(card_invite.is_site_duel_id("web-demo-baccara-waiting"))

    async def test_startup_hydrate_skips_dice_and_restores_persisted_baccarat(self):
        client = AsyncMock()
        client.get_active_pvp_games = AsyncMock(return_value=[
            {"game_id": "dice-1", "game_type": "pvp_dice", "status": "waiting", "game_state": {}},
            {
                "game_id": "web-03e1a2745423",
                "game_type": "baccara",
                "status": "waiting",
                "state_version": 4,
                "creator_id": 940002,
                "stake_rub": "100.00",
                "game_state": {
                    "game_id": 3,
                    "settlement_game_id": "web-03e1a2745423",
                    "status": "waiting",
                    "creator_id": 940002,
                    "bet": "100.00",
                    "cards_creator": [],
                    "cards_opponent": [],
                },
            },
        ])

        hydrated = await card_invite.hydrate_waiting_card_games(
            client, modules={"baccara": baccara, "blackjack": importlib.import_module("games.blackjack")},
        )

        self.assertEqual(hydrated, 1)
        self.assertEqual(baccara.active_games[3]["settlement_game_id"], "web-03e1a2745423")
        self.assertEqual(baccara.game_counter, 3)
