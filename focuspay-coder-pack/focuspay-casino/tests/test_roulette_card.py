import importlib
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules


with TelebotModules(
    "games.roulette_table",
    "games.roulette_card",
    "games.site_links",
    "games.live_card",
):
    roulette_card = importlib.import_module("games.roulette_card")
    roulette_table = importlib.import_module("games.roulette_table")
    chat_reaper = importlib.import_module("games.chat_reaper")


def _snapshot(**overrides):
    data = {
        "round_id": "ed42ffe8-aaaa-bbbb-cccc-dddddddddddd",
        "status": "open",
        "collect_seconds": 25,
        "closes_at": (datetime.now(timezone.utc) + timedelta(seconds=24)).isoformat(),
        "player_count": 1,
        "players": [
            {
                "user_id": 8443902979,
                "display_name": "absoluteop",
                "bet": "red",
                "title_ru": "красное",
                "odds_ru": "1:1",
                "stake_rub": 50,
            }
        ],
    }
    data.update(overrides)
    return data


def _bot():
    return SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=101)),
        edit_message_text=AsyncMock(),
        delete_message=AsyncMock(),
        reply_to=AsyncMock(return_value=SimpleNamespace(message_id=50)),
    )


class RouletteCardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await roulette_card.drain_state()
        from games.drama import drain_drama, reset_state

        await drain_drama()
        reset_state()
        chat_reaper.reset_state()

    def test_card_text_lists_all_bets_and_timer(self):
        text = roulette_card.card_text(
            _snapshot(
                players=[
                    {
                        "user_id": 1,
                        "display_name": "Ann",
                        "bet": "red",
                        "title_ru": "красное",
                        "odds_ru": "1:1",
                        "stake_rub": 50,
                    },
                    {
                        "user_id": 2,
                        "display_name": "Bob",
                        "bet": "black",
                        "title_ru": "чёрное",
                        "odds_ru": "1:1",
                        "stake_rub": 25,
                    },
                ],
                player_count=2,
            )
        )
        self.assertIn("Ставка принята", text)
        self.assertIn("раунд #ED42FFE8", text)
        self.assertIn("Ann", text)
        self.assertIn("Bob", text)
        self.assertIn("красное 50 ₽", text)
        self.assertIn("чёрное 25 ₽", text)
        self.assertIn("Банк: 75 ₽ · игроков 2", text)
        self.assertIn("До спина", text)
        self.assertNotIn("<code>", text)

    async def test_second_bet_edits_same_message(self):
        bot = _bot()
        client = SimpleNamespace(get_roulette_table=AsyncMock(return_value=_snapshot()))
        first = _snapshot()
        await roulette_card.upsert(bot, client, -100, first, telegram_id=1)
        bot.send_message.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.args[0], -100)
        self.assertIn("Ставка принята", bot.send_message.await_args.args[1])
        bot.edit_message_text.assert_not_awaited()
        second = _snapshot(
            players=first["players"]
            + [
                {
                    "user_id": 2,
                    "display_name": "Bob",
                    "bet": "black",
                    "title_ru": "чёрное",
                    "odds_ru": "1:1",
                    "stake_rub": 10,
                }
            ],
            player_count=2,
        )
        await roulette_card.upsert(bot, client, -100, second, telegram_id=2)
        self.assertEqual(bot.send_message.await_count, 1)
        bot.edit_message_text.assert_awaited()
        edited = bot.edit_message_text.await_args.args[0]
        self.assertIn("Bob", edited)
        self.assertEqual(bot.edit_message_text.await_args.args[1], -100)
        self.assertEqual(bot.edit_message_text.await_args.args[2], 101)

    async def test_ticker_spin_beats_then_shows_pocket(self):
        import asyncio

        import games.drama as drama

        drama.MIN_EDIT_INTERVAL = 0
        roulette_card.SPIN_BEATS = tuple((phase, 0.0) for phase, _delay in roulette_card.SPIN_BEATS)
        bot = _bot()
        open_snap = _snapshot()
        settled = _snapshot(status="settled", closes_at=None, pocket=31, color="black")
        client = SimpleNamespace(
            get_roulette_table=AsyncMock(return_value=settled)
        )
        board = roulette_card._board()
        board.interval = 0
        await roulette_card.upsert(bot, client, -7, open_snap, telegram_id=1)
        for _ in range(80):
            card = roulette_card.peek(-7)
            task = None if card is None else card.get("task")
            if task is None or (hasattr(task, "done") and task.done()):
                break
            await asyncio.sleep(0.01)
        texts = [call.args[0] for call in bot.edit_message_text.await_args_list]
        self.assertTrue(any("Ставки закрыты" in text or "крутится" in text.lower() for text in texts))
        self.assertTrue(any("31" in text for text in texts) or "31" in bot.edit_message_text.await_args.args[0])
        tracked = {(item[1], item[2]) for item in chat_reaper.pending()}
        self.assertIn((-7, 101), tracked)

    async def test_drop_deletes_card(self):
        bot = _bot()
        client = SimpleNamespace(get_roulette_table=AsyncMock(return_value=_snapshot()))
        await roulette_card.upsert(bot, client, -3, _snapshot(), telegram_id=1)
        await roulette_card.drop(bot, -3)
        bot.delete_message.assert_awaited_with(-3, 101)
        self.assertIsNone(roulette_card.peek(-3))

    async def test_edit_retries_without_keyboard_when_group_rejects_web_app(self):
        bot = _bot()
        bot.edit_message_text = AsyncMock(
            side_effect=[
                RuntimeError("Bad Request: BUTTON_TYPE_INVALID"),
                SimpleNamespace(),
            ]
        )
        client = SimpleNamespace(get_roulette_table=AsyncMock(return_value=_snapshot()))
        first = _snapshot()
        with patch.object(
            roulette_table.config,
            "CASINO_MINIAPP_URL",
            "https://example.test/casino/tg",
        ):
            await roulette_card.upsert(bot, client, -100, first, telegram_id=1)
            second = _snapshot(
                players=first["players"]
                + [
                    {
                        "user_id": 2,
                        "display_name": "Bob",
                        "bet": "black",
                        "title_ru": "чёрное",
                        "odds_ru": "1:1",
                        "stake_rub": 20,
                    }
                ],
                player_count=2,
            )
            await roulette_card.upsert(bot, client, -100, second, telegram_id=2)
        self.assertEqual(bot.edit_message_text.await_count, 2)
        retry = bot.edit_message_text.await_args_list[1]
        self.assertNotIn("reply_markup", retry.kwargs)
        self.assertIn("Bob", retry.args[0])
        self.assertIn("игроков 2", retry.args[0])


class RouletteTableCardHookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await roulette_card.drain_state()
        from games.drama import drain_drama, reset_state

        await drain_drama()
        reset_state()
        chat_reaper.reset_state()

    async def test_handle_uses_shared_card_not_per_user_reply(self):
        bot = _bot()
        client = AsyncMock()
        client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -5562276559})
        client.get_casino_settings = AsyncMock(
            return_value={"enabled_games": {"roulette": True}, "min_bet_rub": 10, "max_bet_rub": 100000}
        )
        client.get_roulette_table = AsyncMock(return_value=_snapshot())
        client.place_roulette_table_bet = AsyncMock(return_value=_snapshot())
        guard = roulette_table.ActiveGameChatGuard(client)
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=8443902979),
            chat=SimpleNamespace(id=-5562276559, type="supergroup"),
            text="/roulette red 50",
            message_id=88,
        )
        await roulette_table.handle_roulette_command(bot, client, message, guard=guard)
        bot.send_message.assert_awaited_once()
        bot.reply_to.assert_not_awaited()
        bot.delete_message.assert_awaited()


if __name__ == "__main__":
    unittest.main()
