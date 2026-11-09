import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from tests.telebot_stub import TelebotModules

from games.card_streets import dealing_label, street_count, visible_hands


class CardStreetsUnitTests(unittest.TestCase):
    def test_street_count_and_visible(self):
        hands = {"1": ["7♠", "K♣", "2♦"], "2": ["9♥", "9♦"]}
        self.assertEqual(street_count(hands), 3)
        self.assertEqual(street_count(hands, game_type="blackjack"), 2)
        self.assertEqual(visible_hands(hands, 1)["1"], ["7♠"])
        self.assertEqual(visible_hands(hands, 2)["2"], ["9♥", "9♦"])
        self.assertEqual(dealing_label(2), "Раздача: вторая карта…")
        self.assertEqual(dealing_label(1), "Раздача: первая карта…")


with TelebotModules("games.v2_runtime", "games.v2_tables", "games.v2_chat_ledger"):
    runtime = __import__("games.v2_runtime", fromlist=["v2_runtime"])
    ledger = __import__("games.v2_chat_ledger", fromlist=["v2_chat_ledger"])


class CardTextRevealTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        from games.drama import drain_drama, reset_state

        await runtime.drain_ready_watchers()
        await drain_drama()
        reset_state()

    def test_baccarat_card_text_reveals_dealt_cards_and_scores(self):
        table = {
            "table_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "game_type": "baccara",
            "stake_rub": "50.00",
            "status": "running",
            "game_state": {
                "hands": {"1": ["7♠", "K♣"], "2": ["9♥", "9♦"]},
                "rng_commit": "ab" * 32,
            },
            "roster": [
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11, "display_name": "Алекс"},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Робот"}},
            ],
        }
        with patch.object(runtime, "verify_url", return_value=""):
            full = runtime._card_text(table)
        self.assertIn("7♠", full)
        self.assertIn("K♣", full)
        self.assertIn("9♥", full)
        self.assertIn("<b>7</b>", full)
        self.assertIn("<b>8</b>", full)

    async def test_baccarat_reveal_publishes_full_board_in_one_edit(self):
        table = {
            "table_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "game_type": "baccara",
            "stake_rub": "50.00",
            "status": "running",
            "game_state": {"hands": {"1": ["7♠", "K♣"], "2": ["9♥", "9♦"]}},
            "roster": [
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "player", "telegram_id": 22},
            ],
        }
        bot = SimpleNamespace(edit_message_text=AsyncMock(), send_message=AsyncMock())
        client = AsyncMock()
        with patch.object(runtime, "_edit_board", AsyncMock()) as edit:
            await runtime.start_card_reveal(bot, client, table)
        edit.assert_awaited_once()
        text = edit.await_args.kwargs["text"]
        self.assertIn("7♠ K♣", text)
        self.assertIn("9♥ 9♦", text)

    async def test_publish_waits_for_reveal(self):
        from games.drama import run_beats, wait_drama

        waited: list[str] = []

        async def fake_wait(key, timeout=None):
            waited.append(key)
            return True

        table = {
            "table_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "game_type": "baccara",
            "game_chat_id": -100,
            "game_state": {"play_chats": [{"chat_id": -100, "card_msg_id": 1, "trash_msg_ids": []}]},
            "roster": [],
        }
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=9)), delete_message=AsyncMock())
        client = SimpleNamespace()
        ledger.reset_ledger_state()
        with patch.object(runtime, "wait_drama", fake_wait), patch.object(runtime, "_annotate_roster_names", AsyncMock(return_value=table)):
            await runtime.publish_settled_table(bot, client, table, {"outcome_kind": "winner", "table_id": table["table_id"]})
        self.assertTrue(any(key.startswith("v2-reveal:") for key in waited))
