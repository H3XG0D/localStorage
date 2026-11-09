import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules


with TelebotModules("games.pvp", "games.table_wizard", "games.v2_tables", "games.v2_runtime", "games.baccara", "games.blackjack", "games.house_cub", "games.site_links"):
    pvp = importlib.import_module("games.pvp")


class Bot:
    def __init__(self):
        self.handlers = []
        self.edit_message_text = AsyncMock()
        self.reply_to = AsyncMock()
        self.send_message = AsyncMock()
        self.send_dice = AsyncMock(
            return_value=SimpleNamespace(dice=SimpleNamespace(emoji="🎲", value=3))
        )

    def message_handler(self, **kwargs):
        def decorator(handler):
            self.handlers.append((kwargs, handler))
            return handler
        return decorator

    def callback_query_handler(self, **kwargs):
        return lambda handler: handler

    def register_message_handler(self, handler, **kwargs):
        self.handlers.append((kwargs, handler))

    def dice_handler(self):
        return next(handler for kwargs, handler in self.handlers if kwargs.get("content_types") == ["dice"])


class PvpDiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        pvp.active_games.clear()
        pvp._roll_game_ids.clear()
        pvp._game_locks.clear()
        self.bot = Bot()
        self.client = SimpleNamespace(
            get_active_game_chat_binding=AsyncMock(return_value={"chat_id": -100123}),
            persist_game_state=AsyncMock(return_value={"game": {"state_version": 8, "status": "active"}}),
            record_pvp_dice_roll=AsyncMock(side_effect=self._record_roll),
            get_pending_cub=AsyncMock(return_value={"success": True, "pending": None}),
            v2_tables_get=AsyncMock(return_value={"tables": []}),
            get_casino_settings=AsyncMock(return_value={"enabled_games": {"pvp_dice": True}, "min_bet_rub": 10, "max_bet_rub": 1000}),
            get_active_pvp_games=AsyncMock(return_value=[]),
        )
        pvp.register_pvp_handlers(self.bot, self.client)
        self.wait = AsyncMock()
        self.wait_patcher = patch.object(pvp, "wait_dice_landed", self.wait)
        self.wait_patcher.start()

    async def _record_roll(self, *, game_id, telegram_id, value):
        game = pvp.active_games[game_id]
        creator = list(game.get("creator_rolls") or [])
        opponent = list(game.get("opponent_rolls") or [])
        if telegram_id == game.get("creator_id"):
            creator = creator + [value]
        else:
            opponent = opponent + [value]
        needed = 2 if game.get("game_type") == "2cub" else 1
        status = "finished" if len(creator) >= needed and len(opponent) >= needed else "active"
        return {
            "success": True,
            "game": {
                "state_version": int(game.get("state_version") or 0) + 1,
                "status": status,
                "game_state": {"creator_rolls": creator, "opponent_rolls": opponent},
            },
        }

    def tearDown(self):
        self.wait_patcher.stop()
        pvp.active_games.clear()
        pvp._roll_game_ids.clear()
        pvp._game_locks.clear()

    async def test_dice_reply_records_creator_roll_and_updates_counter(self):
        game_id = "game-1"
        pvp.active_games[game_id] = {
            "game_type": "cub", "status": "rolling", "chat_id": -100123,
            "roll_msg_id": 73, "creator_id": 10, "opponent_id": 20,
            "creator_name": "Creator", "opponent_name": "Opponent", "bet": 50,
            "creator_rolls": [], "opponent_rolls": [], "state_version": 7,
        }
        pvp._index_roll_message(game_id, pvp.active_games[game_id])
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100123),
            from_user=SimpleNamespace(id=10),
            reply_to_message=SimpleNamespace(message_id=73),
            dice=SimpleNamespace(emoji="🎲", value=6),
        )

        await self.bot.dice_handler()(message)

        self.assertEqual(pvp.active_games[game_id]["creator_rolls"], [6])
        self.client.record_pvp_dice_roll.assert_awaited()
        self.client.persist_game_state.assert_not_awaited()
        text = self.bot.edit_message_text.await_args.args[0]
        self.assertIn("[✅]: 6", text)

    async def test_dice_reply_to_lobby_card_still_records_by_user_id(self):
        pvp.active_games["game-1"] = {
            "game_type": "cub", "status": "rolling", "chat_id": -100123,
            "message_id": 72, "roll_msg_id": 73, "creator_id": 10, "opponent_id": 20,
            "creator_name": "Creator", "opponent_name": "Opponent", "bet": 50,
            "creator_rolls": [], "opponent_rolls": [], "state_version": 7,
        }
        pvp._index_roll_message("game-1", pvp.active_games["game-1"])
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100123, type="supergroup"), from_user=SimpleNamespace(id=10, is_bot=False),
            reply_to_message=SimpleNamespace(message_id=72), dice=SimpleNamespace(emoji="🎲", value=6),
        )

        await self.bot.dice_handler()(message)

        self.assertEqual(pvp.active_games["game-1"]["creator_rolls"], [6])
        self.client.record_pvp_dice_roll.assert_awaited()

    async def test_dice_without_reply_records_by_user_id(self):
        pvp.active_games["game-1"] = {
            "game_type": "cub", "status": "rolling", "chat_id": -100123,
            "roll_msg_id": 73, "creator_id": 10, "opponent_id": 20,
            "creator_name": "Creator", "opponent_name": "Opponent", "bet": 50,
            "creator_rolls": [], "opponent_rolls": [], "state_version": 7,
        }
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100123, type="supergroup"),
            from_user=SimpleNamespace(id=10, is_bot=False),
            reply_to_message=None,
            dice=SimpleNamespace(emoji="🎲", value=6),
        )

        await self.bot.dice_handler()(message)

        self.assertEqual(pvp.active_games["game-1"]["creator_rolls"], [6])
        self.bot.reply_to.assert_not_awaited()

    async def test_spectator_dice_without_reply_is_ignored(self):
        pvp.active_games["game-1"] = {
            "game_type": "cub", "status": "rolling", "chat_id": -100123,
            "roll_msg_id": 73, "creator_id": 10, "opponent_id": 20,
            "creator_name": "Creator", "opponent_name": "Opponent", "bet": 50,
            "creator_rolls": [], "opponent_rolls": [], "state_version": 7,
        }
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100123, type="supergroup"),
            from_user=SimpleNamespace(id=99, is_bot=False),
            reply_to_message=None,
            dice=SimpleNamespace(emoji="🎲", value=6),
        )

        await self.bot.dice_handler()(message)

        self.assertEqual(pvp.active_games["game-1"]["creator_rolls"], [])
        self.client.persist_game_state.assert_not_awaited()
        self.client.record_pvp_dice_roll.assert_not_awaited()
        self.bot.reply_to.assert_not_awaited()

    async def test_robot_throws_after_player_die_lands(self):
        pvp.active_games["game-1"] = {
            "game_type": "2cub", "status": "rolling", "chat_id": -100123,
            "roll_msg_id": 73, "creator_id": 10, "opponent_id": None,
            "counterparty_kind": "pvp_robot",
            "creator_name": "Creator", "opponent_name": "Робот", "bet": 50,
            "creator_rolls": [], "opponent_rolls": [], "state_version": 7,
        }
        order: list[str] = []

        async def wait():
            order.append("wait")

        async def send_dice(**kwargs):
            order.append("send_dice")
            return SimpleNamespace(dice=SimpleNamespace(emoji="🎲", value=3))

        self.wait.side_effect = wait
        self.bot.send_dice.side_effect = send_dice
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100123, type="supergroup"),
            from_user=SimpleNamespace(id=10, is_bot=False),
            reply_to_message=None,
            dice=SimpleNamespace(emoji="🎲", value=6),
        )

        await self.bot.dice_handler()(message)

        self.assertEqual(pvp.active_games["game-1"]["creator_rolls"], [6])
        self.assertEqual(pvp.active_games["game-1"]["opponent_rolls"], [3])
        self.assertEqual(order, ["wait", "send_dice", "wait"])
        self.bot.send_dice.assert_awaited()

    async def test_hydrated_game_records_dice_after_cache_reset(self):
        self.client.get_active_pvp_games = AsyncMock(return_value=[{
            "game_id": "hydrated", "game_type": "pvp_dice", "creator_id": 10,
            "opponent_id": 20, "counterparty_kind": "player", "stake_rub": "50.00",
            "status": "active", "state_version": 7,
            "game_state": {
                "game_type": "2cub", "chat_id": -100123, "message_id": 72, "roll_msg_id": 73,
                "creator_name": "Creator", "opponent_name": "Opponent", "creator_rolls": [], "opponent_rolls": [],
            },
        }])

        self.assertEqual(await pvp.hydrate_active_pvp_games(self.client), 1)
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100123), from_user=SimpleNamespace(id=10),
            reply_to_message=SimpleNamespace(message_id=73), dice=SimpleNamespace(emoji="🎲", value=6),
        )
        await self.bot.dice_handler()(message)

        self.assertEqual(pvp.active_games["hydrated"]["creator_rolls"], [6])
        self.assertIn("[1/2]: 6", self.bot.edit_message_text.await_args.args[0])

    def test_hydrated_rolling_game_is_listed_as_own_active_game(self):
        game = {"creator_id": 10, "opponent_id": 20, "status": "rolling"}
        pvp.active_games["hydrated"] = game

        self.assertEqual(pvp.own_active_games(10), [("hydrated", game)])

    async def test_same_prompt_id_in_another_chat_does_not_mutate_game(self):
        game = {
            "game_type": "cub", "status": "rolling", "chat_id": -100123, "roll_msg_id": 73,
            "creator_id": 10, "opponent_id": 20, "creator_name": "Creator", "opponent_name": "Opponent",
            "bet": 50, "creator_rolls": [], "opponent_rolls": [], "state_version": 7,
        }
        pvp.active_games["game-1"] = game
        pvp._index_roll_message("game-1", game)
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100999), from_user=SimpleNamespace(id=10),
            reply_to_message=SimpleNamespace(message_id=73), dice=SimpleNamespace(emoji="🎲", value=6),
        )

        await self.bot.dice_handler()(message)

        self.assertEqual(game["creator_rolls"], [])
        self.client.persist_game_state.assert_not_awaited()
        self.client.record_pvp_dice_roll.assert_not_awaited()

    async def test_private_dice_without_house_cub_explains_cub_vs_group(self):
        message = SimpleNamespace(
            chat=SimpleNamespace(id=10, type="private"),
            from_user=SimpleNamespace(id=10, is_bot=False),
            reply_to_message=None,
            dice=SimpleNamespace(emoji="🎲", value=6),
        )

        await self.bot.dice_handler()(message)

        text = self.bot.reply_to.await_args.args[1]
        self.assertIn("/cub", text)
        self.assertIn("игровом чате", text)
        self.assertNotIn("подтверждённом игровом чате", text)

    async def test_private_dice_on_grouped_game_stays_in_group(self):
        pvp.active_games["game-1"] = {
            "game_type": "cub", "status": "rolling", "chat_id": -100123,
            "roll_msg_id": 73, "creator_id": 10, "opponent_id": 20,
            "creator_name": "Creator", "opponent_name": "Opponent", "bet": 50,
            "creator_rolls": [], "opponent_rolls": [], "state_version": 7,
            "game_chat_id": -100123,
        }
        message = SimpleNamespace(
            chat=SimpleNamespace(id=10, type="private"),
            from_user=SimpleNamespace(id=10, is_bot=False),
            reply_to_message=None,
            dice=SimpleNamespace(emoji="🎲", value=6),
        )

        await self.bot.dice_handler()(message)

        self.assertEqual(pvp.active_games["game-1"]["creator_rolls"], [])
        self.client.record_pvp_dice_roll.assert_not_awaited()
        self.assertIn("игровом чате", self.bot.reply_to.await_args.args[1])

    async def test_private_dice_records_via_api_when_cache_is_cold(self):
        self.client.get_active_pvp_games = AsyncMock(return_value=[{
            "game_id": "backend-game", "game_type": "pvp_dice", "creator_id": 10,
            "opponent_id": 20, "status": "active",
        }])
        self.client.record_pvp_dice_roll = AsyncMock(return_value={"success": True, "game": {"status": "active"}})
        message = SimpleNamespace(
            chat=SimpleNamespace(id=10, type="private"),
            from_user=SimpleNamespace(id=10, is_bot=False),
            reply_to_message=None,
            dice=SimpleNamespace(emoji="🎲", value=1),
        )

        await self.bot.dice_handler()(message)

        self.client.record_pvp_dice_roll.assert_awaited_once()
        self.assertEqual(self.client.record_pvp_dice_roll.await_args.kwargs["game_id"], "backend-game")
        self.assertEqual(self.client.record_pvp_dice_roll.await_args.kwargs["value"], 1)
        self.bot.reply_to.assert_not_awaited()

    async def test_hydrate_active_without_roll_msg_id(self):
        self.client.get_active_pvp_games = AsyncMock(return_value=[{
            "game_id": "web-join", "game_type": "pvp_dice", "creator_id": 10,
            "opponent_id": 20, "counterparty_kind": "player", "stake_rub": "50.00",
            "status": "active", "state_version": 4,
            "game_state": {
                "game_type": "cub", "chat_id": -100123, "message_id": 72,
                "creator_name": "Creator", "opponent_name": "Opponent",
                "creator_rolls": [], "opponent_rolls": [],
            },
        }])
        self.assertEqual(await pvp.hydrate_active_pvp_games(self.client), 1)
        self.assertEqual(pvp.active_games["web-join"]["status"], "rolling")
        self.assertIsNone(pvp.active_games["web-join"].get("roll_msg_id"))

    async def test_sync_sends_roll_prompt_when_cache_still_waiting(self):
        pvp.active_games["web-join"] = {
            "game_type": "cub", "status": "waiting", "chat_id": -100123, "message_id": 72,
            "creator_id": 10, "opponent_id": None, "creator_rolls": [], "opponent_rolls": [],
            "state_version": 2, "bet": 50, "creator_name": "C", "opponent_name": "?",
        }
        self.bot.send_message.return_value = SimpleNamespace(message_id=80)
        self.client.get_active_pvp_games = AsyncMock(return_value=[{
            "game_id": "web-join", "game_type": "pvp_dice", "creator_id": 10,
            "opponent_id": 20, "counterparty_kind": "player", "stake_rub": "50.00",
            "status": "active", "state_version": 5,
            "game_state": {
                "game_type": "cub", "chat_id": -100123, "message_id": 72,
                "creator_name": "Creator", "opponent_name": "Opponent",
                "creator_rolls": [], "opponent_rolls": [],
            },
        }])
        self.assertEqual(await pvp.sync_active_pvp_from_backend(self.bot, self.client), 1)
        self.bot.send_message.assert_awaited()
        self.assertEqual(pvp.active_games["web-join"]["roll_msg_id"], 80)
        self.assertIn("30 с", self.bot.send_message.await_args.args[1])

    def test_adopt_waiting_web_dice_without_group_card(self):
        adopted = pvp.adopt_waiting_dice_from_durable({
            "game_id": "web-61d780262c3b",
            "game_type": "pvp_dice",
            "status": "waiting",
            "creator_id": 940002,
            "stake_rub": "25.00",
            "state_version": 2,
            "rounds": 1,
        })
        self.assertIsNotNone(adopted)
        game_id, game = adopted
        self.assertEqual(game_id, "web-61d780262c3b")
        self.assertEqual(game["status"], "waiting")
        self.assertEqual(pvp.own_active_games(940002), [(game_id, game)])

    async def test_join_waiting_dice_from_dm_holds_and_prompts_roll(self):
        self.client.get_active_pvp_games = AsyncMock(return_value=[{
            "game_id": "web-61d780262c3b",
            "game_type": "pvp_dice",
            "status": "waiting",
            "creator_id": 940002,
            "stake_rub": "25.00",
            "state_version": 2,
            "rounds": 1,
        }])
        self.client.join_and_hold_game = AsyncMock(return_value={"game": {"state_version": 3, "status": "active"}})
        self.bot.send_message.return_value = SimpleNamespace(message_id=91)
        call = SimpleNamespace(
            message=SimpleNamespace(chat=SimpleNamespace(id=77, type="private")),
            from_user=SimpleNamespace(id=77, username="joiner", first_name="Joiner"),
        )

        await pvp.join_waiting_dice_from_dm(self.bot, self.client, call, "web-61d780262c3b")

        self.client.join_and_hold_game.assert_awaited_once_with(game_id="web-61d780262c3b", opponent_id=77)
        game = pvp.active_games["web-61d780262c3b"]
        self.assertEqual(game["status"], "rolling")
        self.assertEqual(game["opponent_id"], 77)
        self.assertEqual(game["roll_msg_id"], 91)
        self.assertEqual(game["chat_id"], 77)
        last = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("Вы в игре", last)
        self.assertIn("этот чат", last)

    def test_adopt_prefers_pinned_group_over_dm(self):
        adopted = pvp.adopt_waiting_dice_from_durable({
            "game_id": "web-61d780262c3b",
            "game_type": "pvp_dice",
            "status": "waiting",
            "creator_id": 940002,
            "stake_rub": "25.00",
            "state_version": 2,
            "rounds": 1,
            "game_chat_id": -100123,
        }, chat_id=77)
        self.assertIsNotNone(adopted)
        _, game = adopted
        self.assertEqual(game["chat_id"], -100123)
        self.assertEqual(game["game_chat_id"], -100123)

    async def test_join_waiting_dice_from_dm_grouped_prompts_group(self):
        self.client.get_active_pvp_games = AsyncMock(return_value=[{
            "game_id": "web-61d780262c3b",
            "game_type": "pvp_dice",
            "status": "waiting",
            "creator_id": 940002,
            "stake_rub": "25.00",
            "state_version": 2,
            "rounds": 1,
            "game_chat_id": -100123,
        }])
        self.client.join_and_hold_game = AsyncMock(return_value={"game": {"state_version": 3, "status": "active"}})
        self.bot.send_message.return_value = SimpleNamespace(message_id=91)
        call = SimpleNamespace(
            message=SimpleNamespace(chat=SimpleNamespace(id=77, type="private")),
            from_user=SimpleNamespace(id=77, username="joiner", first_name="Joiner"),
        )

        await pvp.join_waiting_dice_from_dm(self.bot, self.client, call, "web-61d780262c3b")

        game = pvp.active_games["web-61d780262c3b"]
        self.assertEqual(game["chat_id"], -100123)
        chats = [call.args[0] for call in self.bot.send_message.await_args_list]
        self.assertIn(-100123, chats)
        self.assertIn("игровом чате", self.bot.send_message.await_args_list[-1].args[1])

    async def test_private_dice_api_skips_grouped_backend_game(self):
        self.client.get_active_pvp_games = AsyncMock(return_value=[{
            "game_id": "backend-game", "game_type": "pvp_dice", "creator_id": 10,
            "opponent_id": 20, "status": "active", "game_chat_id": -100123,
        }])
        message = SimpleNamespace(
            chat=SimpleNamespace(id=10, type="private"),
            from_user=SimpleNamespace(id=10, is_bot=False),
            reply_to_message=None,
            dice=SimpleNamespace(emoji="🎲", value=1),
        )

        await self.bot.dice_handler()(message)

        self.client.record_pvp_dice_roll.assert_not_awaited()
        self.assertIn("/cub", self.bot.reply_to.await_args.args[1])

    async def test_private_cub_stake_opens_wizard_not_house(self):
        handler = next(
            handler for kwargs, handler in self.bot.handlers
            if kwargs.get("commands") == ["cub"]
        )
        message = SimpleNamespace(
            text="/cub 100",
            chat=SimpleNamespace(id=10, type="private"),
            from_user=SimpleNamespace(id=10),
        )
        with patch.object(pvp, "start_wizard_for_command", AsyncMock()) as wizard:
            await handler(message)
        wizard.assert_awaited_once()
        self.assertEqual(wizard.await_args.args[3], "cub")
        self.assertFalse(hasattr(self.client, "open_cub") and self.client.open_cub.await_count)

