import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.telebot_stub import TelebotModules


with TelebotModules(
    "games.roulette_table",
    "games.roulette_card",
    "games.jackpot",
    "games.jackpot_card",
    "games.site_links",
    "games.live_card",
    "games.live_table_hydrate",
):
    roulette_card = importlib.import_module("games.roulette_card")
    jackpot_card = importlib.import_module("games.jackpot_card")
    hydrate = importlib.import_module("games.live_table_hydrate")


def _roulette_snap():
    return {
        "round_id": "rt-c60240d82c3d",
        "status": "open",
        "closes_at": "2026-09-02T07:10:57+00:00",
        "player_count": 2,
        "players": [
            {"user_id": 8760743763, "display_name": "A", "bet": "17", "stake_rub": 50},
            {"user_id": 8718118115, "display_name": "B", "bet": "black", "stake_rub": 20},
        ],
    }


class SnapshotNeedsCardTests(unittest.TestCase):
    def test_open_with_players(self):
        self.assertTrue(hydrate.snapshot_needs_card(_roulette_snap()))

    def test_idle_open_without_bets_is_skipped(self):
        self.assertFalse(hydrate.snapshot_needs_card({"status": "open", "players": []}))

    def test_settled_is_skipped(self):
        self.assertFalse(hydrate.snapshot_needs_card({"status": "settled", "players": [{"user_id": 1}]}))


class LiveTableHydrateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await roulette_card.drain_state()
        await jackpot_card.drain_state()

    async def test_hydrate_sends_open_roulette_card_to_bound_chat(self):
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=44)),
            edit_message_text=AsyncMock(),
            delete_message=AsyncMock(),
        )
        client = SimpleNamespace(
            get_active_game_chat_binding=AsyncMock(return_value={"chat_id": -1004058942735}),
            get_roulette_table=AsyncMock(return_value=_roulette_snap()),
            get_jackpot=AsyncMock(return_value={"status": "open", "players": []}),
        )
        restored = await hydrate.hydrate_live_table_cards(bot, client)
        self.assertEqual(restored, 1)
        bot.send_message.assert_awaited()
        self.assertEqual(bot.send_message.await_args.args[0], -1004058942735)
        self.assertIn("игроков 2", bot.send_message.await_args.args[1])
        self.assertIn("black", bot.send_message.await_args.args[1])
        card = roulette_card.peek(-1004058942735)
        self.assertIsNotNone(card)
        self.assertEqual(card["round_id"], "rt-c60240d82c3d")

    async def test_hydrate_skips_when_no_binding(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        client = SimpleNamespace(
            get_active_game_chat_binding=AsyncMock(return_value=None),
            get_roulette_table=AsyncMock(return_value=_roulette_snap()),
        )
        self.assertEqual(await hydrate.hydrate_live_table_cards(bot, client), 0)
        bot.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
