import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.telebot_stub import TelebotModules


with TelebotModules("games.pvp", "games.table_wizard", "games.v2_tables", "games.v2_runtime", "games.baccara", "games.blackjack", "games.house_cub"):
    pvp = importlib.import_module("games.pvp")


class Keyboard:
    def __init__(self, *args, **kwargs):
        self.buttons = []

    def add(self, button):
        self.buttons.append(button)

    def row(self, *buttons):
        self.buttons.extend(buttons)


class Button:
    def __init__(self, text, **kwargs):
        self.text = text
        self.kwargs = kwargs


class Bot:
    def __init__(self):
        self.message_handlers = {}
        self.callback_handlers = []
        self.reply_to = AsyncMock()
        self.send_message = AsyncMock()
        self.delete_message = AsyncMock()
        self.edit_message_reply_markup = AsyncMock()
        self.edit_message_text = AsyncMock()
        self.answer_callback_query = AsyncMock()

    def register_message_handler(self, handler, *, commands):
        for command in commands:
            self.message_handlers[command] = handler

    def message_handler(self, **kwargs):
        def decorator(handler):
            for command in kwargs.get("commands", []):
                self.message_handlers[command] = handler
            return handler
        return decorator

    def callback_query_handler(self, **kwargs):
        def decorator(handler):
            self.callback_handlers.append((kwargs["func"], handler))
            return handler
        return decorator


class PvpLobbyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_types = pvp.types
        pvp.types = SimpleNamespace(InlineKeyboardMarkup=Keyboard, InlineKeyboardButton=Button)
        pvp.active_games.clear()
        pvp._game_locks.clear()
        pvp._private_lobby_tokens.clear()
        pvp._private_create_tokens.clear()
        pvp._private_create_amount_inputs.clear()
        self.bot = Bot()
        self.client = SimpleNamespace(
            get_active_game_chat_binding=AsyncMock(),
            join_and_hold_game=AsyncMock(return_value={"game": {"state_version": 3, "status": "active"}}),
            get_casino_settings=AsyncMock(return_value={
                "enabled_games": {"pvp_dice": True, "baccara": True}, "min_bet_rub": 10, "max_bet_rub": 1000,
            }),
            create_or_resume_game=AsyncMock(return_value={"game": {"state_version": 1}}),
            create_pvp_game_from_dm=AsyncMock(return_value={"success": True, "invitation": {"outbox_id": 1, "status": "pending"}}),
            create_v2_table=AsyncMock(return_value={"success": True, "table": {"table_id": "tbl", "status": "open", "state_version": 0, "game_state": {}, "game_type": "pvp_dice"}}),
            persist_game_state=AsyncMock(return_value={"game": {"state_version": 2}}),
            commit_game_outcome=AsyncMock(return_value={"game": {"state_version": 3}}),
            settle_committed_outcome=AsyncMock(return_value={"game": {"state_version": 4, "status": "cancelled"}}),
        )
        self.client.get_active_game_chat_binding.return_value = {"chat_id": -100123}
        pvp.register_pvp_handlers(self.bot, self.client)

    def tearDown(self):
        pvp.types = self.original_types
        pvp.active_games.clear()
        pvp._game_locks.clear()
        pvp._private_lobby_tokens.clear()
        pvp._private_create_tokens.clear()
        pvp._private_create_amount_inputs.clear()

    def _private_lobby_handler(self):
        return next(handler for predicate, handler in self.bot.callback_handlers if predicate(SimpleNamespace(data="dmjoin:token")))

    def _group_join_handler(self):
        return next(handler for predicate, handler in self.bot.callback_handlers if predicate(SimpleNamespace(data="join_game")))

    def _group_lobby_page_handler(self):
        return next(handler for predicate, handler in self.bot.callback_handlers if predicate(SimpleNamespace(data="agpage:0")))

    def _table_wizard_handler(self):
        return next(handler for predicate, handler in self.bot.callback_handlers if predicate(SimpleNamespace(data="tw:token")))

    def _issue_wizard_token(self, owner_id, **fields):
        handler = self._table_wizard_handler()
        return handler.__globals__["_issue"](owner_id, **fields)

    def _waiting_game(self, game_id="internal-game-id", creator_id=3):
        return {
            "game_id": game_id,
            "game_type": "cub",
            "creator_id": creator_id,
            "creator_name": "Creator",
            "opponent_id": None,
            "opponent_name": "Ожидание...",
            "bet": pvp.Decimal("25.00"),
            "chat_id": -100123,
            "message_id": 51,
            "roll_msg_id": None,
            "creator_rolls": [],
            "opponent_rolls": [],
            "status": "waiting",
            "state_version": 1,
        }

    async def test_invitation_pass_sends_completes_then_hydrates(self):
        calls = []
        payload = {
            "game_id": "game-1", "game_type": "pvp_dice", "rounds": 1,
            "chat_id": -100123, "stake_rub": "25", "creator_id": 7,
        }
        self.client.claim_pvp_invitations = AsyncMock(return_value={
            "success": True,
            "items": [{"outbox_id": 11, "claim_token": "claim-1", "payload": payload}],
        })

        async def send_message(*args, **kwargs):
            calls.append("send")
            return SimpleNamespace(message_id=99)

        async def complete_pvp_invitation(**kwargs):
            calls.append("complete")

        async def hydrate(client, actual_payload, telegram_message_id):
            calls.append("hydrate")

        self.bot.send_message.side_effect = send_message
        self.client.complete_pvp_invitation = AsyncMock(side_effect=complete_pvp_invitation)
        self.client.fail_pvp_invitation = AsyncMock()
        original_hydrate = pvp._hydrate_invited_game
        pvp._hydrate_invited_game = hydrate
        try:
            processed = await pvp.run_pvp_invitation_pass(self.bot, self.client, worker_id="worker-1")
        finally:
            pvp._hydrate_invited_game = original_hydrate

        self.assertEqual(processed, 1)
        self.assertEqual(calls, ["send", "complete", "hydrate"])
        self.client.complete_pvp_invitation.assert_awaited_once_with(
            outbox_id=11, claim_token="claim-1", telegram_message_id=99,
        )
        self.client.fail_pvp_invitation.assert_not_awaited()

    async def test_invitation_pass_marks_invitation_failed_when_sending_raises(self):
        payload = {
            "game_id": "game-1", "game_type": "pvp_dice", "rounds": 1,
            "chat_id": -100123, "stake_rub": "25", "creator_id": 7,
        }
        self.client.claim_pvp_invitations = AsyncMock(return_value={
            "success": True,
            "items": [{"outbox_id": 11, "claim_token": "claim-1", "payload": payload}],
        })
        self.bot.send_message.side_effect = RuntimeError("Telegram unavailable")
        self.client.complete_pvp_invitation = AsyncMock()
        self.client.fail_pvp_invitation = AsyncMock()

        processed = await pvp.run_pvp_invitation_pass(self.bot, self.client, worker_id="worker-1")

        self.assertEqual(processed, 1)
        self.client.complete_pvp_invitation.assert_not_awaited()
        self.client.fail_pvp_invitation.assert_awaited_once_with(
            outbox_id=11, claim_token="claim-1", error="Telegram unavailable",
        )

    async def test_private_create_opens_unified_wizard(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), from_user=SimpleNamespace(id=7))
        await self.bot.message_handlers["newgame"](message)
        self.bot.send_message.assert_awaited()
        keyboard = self.bot.send_message.await_args.kwargs["reply_markup"]
        type_callback = keyboard.keyboard[0][0].callback_data
        self.assertTrue(type_callback.startswith("tw:"))
        self.client.create_pvp_game_from_dm.assert_not_awaited()

    async def test_private_create_rejects_foreign_callback(self):
        token = self._issue_wizard_token(7, step="type", family="cub")
        call = SimpleNamespace(
            id="create-foreign", data=f"tw:{token}", from_user=SimpleNamespace(id=8),
            message=SimpleNamespace(chat=SimpleNamespace(id=8, type="private"), message_id=71),
        )
        await self._table_wizard_handler()(call)
        self.client.create_v2_table.assert_not_awaited()
        self.assertIn("устарел", self.bot.answer_callback_query.await_args.args[1])

    async def test_wizard_type_step_edits_in_bound_group(self):
        token = self._issue_wizard_token(7, step="type", family="cub", chat_id=-100123)
        call = SimpleNamespace(
            id="create-group", data=f"tw:{token}", from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat=SimpleNamespace(id=-100123, type="supergroup"), message_id=71),
        )
        await self._table_wizard_handler()(call)
        self.bot.edit_message_text.assert_awaited()
        self.client.create_v2_table.assert_not_awaited()

    async def test_pinned_waiting_game_can_join_after_active_binding_replaced(self):
        game = self._waiting_game()
        game["game_chat_id"] = -100777
        game["chat_id"] = -100777
        pvp.active_games["internal-game-id"] = game
        self.bot.send_message.return_value = SimpleNamespace(message_id=62)
        self.client.get_active_game_chat_binding.return_value = {"chat_id": -100123}
        call = SimpleNamespace(
            id="pinned-join", data="join_internal-game-id", from_user=SimpleNamespace(id=7, username="joiner", first_name="Joiner"),
            message=SimpleNamespace(chat=SimpleNamespace(id=-100777, type="supergroup"), message_id=51),
        )
        await self._group_join_handler()(call)
        self.client.join_and_hold_game.assert_awaited_once_with(game_id="internal-game-id", opponent_id=7)

    async def test_private_lobby_lists_only_foreign_waiting_supported_games(self):
        pvp.active_games["internal-game-id"] = self._waiting_game()
        pvp.active_games["own-game"] = self._waiting_game("own-game", creator_id=7)
        active = self._waiting_game("active-game")
        active["status"] = "rolling"
        pvp.active_games["active-game"] = active
        unsupported = self._waiting_game("unsupported-game")
        unsupported["game_type"] = "unknown"
        pvp.active_games["unsupported-game"] = unsupported
        message = SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), from_user=SimpleNamespace(id=7))

        await self.bot.message_handlers["allgames"](message)

        _, text = self.bot.reply_to.await_args.args
        self.assertIn("Ожидающие игры", text)
        self.assertNotIn("#INTERNAL", text)
        self.assertNotIn("own-game", text)
        keyboard = self.bot.reply_to.await_args.kwargs["reply_markup"]
        join_buttons = [button for button in keyboard.buttons if button.kwargs["callback_data"].startswith("dmjoin:")]
        self.assertEqual(len(join_buttons), 1)
        self.assertIn("1.", join_buttons[0].text)
        self.assertIn("Кубики", join_buttons[0].text)
        self.assertIn("Creator", join_buttons[0].text)
        callback_data = join_buttons[0].kwargs["callback_data"]
        self.assertTrue(callback_data.startswith("dmjoin:"))
        self.assertNotIn("internal-game-id", callback_data)

    async def test_private_lobby_callback_rejects_foreign_user(self):
        pvp.active_games["internal-game-id"] = self._waiting_game()
        token = pvp._issue_private_lobby_token(owner_id=7, game_id="internal-game-id", page=0)
        call = SimpleNamespace(
            id="callback-1",
            data=f"dmjoin:{token}",
            from_user=SimpleNamespace(id=8, username="other", first_name="Other"),
            message=SimpleNamespace(chat=SimpleNamespace(id=8, type="private"), message_id=61),
        )

        await self._private_lobby_handler()(call)

        self.client.join_and_hold_game.assert_not_awaited()
        self.bot.answer_callback_query.assert_awaited_once()
        self.assertIn("устарел", self.bot.answer_callback_query.await_args.args[1])

    async def test_private_lobby_callback_uses_callback_user_and_starts_public_game(self):
        pvp.active_games["internal-game-id"] = self._waiting_game()
        self.bot.send_message.return_value = SimpleNamespace(message_id=62)
        token = pvp._issue_private_lobby_token(owner_id=7, game_id="internal-game-id", page=0)
        call = SimpleNamespace(
            id="callback-1",
            data=f"dmjoin:{token}",
            from_user=SimpleNamespace(id=7, username="joiner", first_name="Joiner"),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=61),
        )

        await self._private_lobby_handler()(call)

        self.client.join_and_hold_game.assert_awaited_once_with(game_id="internal-game-id", opponent_id=7)
        self.assertEqual(pvp.active_games["internal-game-id"]["opponent_id"], 7)
        self.assertEqual(pvp.active_games["internal-game-id"]["status"], "rolling")
        self.bot.send_message.assert_awaited_once()

    async def test_private_lobby_callback_rejects_non_private_context(self):
        pvp.active_games["internal-game-id"] = self._waiting_game()
        token = pvp._issue_private_lobby_token(owner_id=7, game_id="internal-game-id", page=0)
        call = SimpleNamespace(
            id="callback-1",
            data=f"dmjoin:{token}",
            from_user=SimpleNamespace(id=7, username="joiner", first_name="Joiner"),
            message=SimpleNamespace(chat=SimpleNamespace(id=-100123, type="supergroup"), message_id=61),
        )

        await self._private_lobby_handler()(call)

        self.client.join_and_hold_game.assert_not_awaited()
        self.assertIn("личном чате", self.bot.answer_callback_query.await_args.args[1])

    async def test_private_lobby_callback_rejects_expired_token(self):
        pvp.active_games["internal-game-id"] = self._waiting_game()
        token = pvp._issue_private_lobby_token(owner_id=7, game_id="internal-game-id", page=0)
        pvp._private_lobby_tokens[token]["expires_at"] = 0
        call = SimpleNamespace(
            id="callback-1",
            data=f"dmjoin:{token}",
            from_user=SimpleNamespace(id=7, username="joiner", first_name="Joiner"),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=61),
        )

        await self._private_lobby_handler()(call)

        self.client.join_and_hold_game.assert_not_awaited()
        self.assertIn("устарел", self.bot.answer_callback_query.await_args.args[1])

    async def test_private_lobby_conflict_refreshes_stale_list(self):
        pvp.active_games["internal-game-id"] = self._waiting_game()
        conflict = RuntimeError("conflict")
        conflict.response = SimpleNamespace(status_code=409)
        self.client.join_and_hold_game.side_effect = conflict
        token = pvp._issue_private_lobby_token(owner_id=7, game_id="internal-game-id", page=0)
        call = SimpleNamespace(
            id="callback-1",
            data=f"dmjoin:{token}",
            from_user=SimpleNamespace(id=7, username="joiner", first_name="Joiner"),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=61),
        )

        await self._private_lobby_handler()(call)

        self.assertEqual(pvp.active_games["internal-game-id"]["status"], "waiting")
        self.bot.edit_message_text.assert_awaited_once()
        self.assertIn("уже недоступна", self.bot.answer_callback_query.await_args.args[1])

    async def test_private_lobby_without_available_games_does_not_expose_actions(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), from_user=SimpleNamespace(id=7))

        await self.bot.message_handlers["allgames"](message)

        self.bot.reply_to.assert_awaited_once()
        _, text = self.bot.reply_to.await_args.args
        self.assertIn("нет доступных", text)
        self.assertIsNone(self.bot.reply_to.await_args.kwargs["reply_markup"])
        self.bot.send_message.assert_not_awaited()

    async def test_new_game_uses_actual_message_chat_id(self):
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100123, type="supergroup"),
            from_user=SimpleNamespace(id=7, username="player", first_name="Player"),
            text="/2cub 10",
        )

        await self.bot.message_handlers["2cub"](message)

        self.bot.reply_to.assert_not_awaited()
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(self.bot.send_message.await_args.args[0], -100123)
        self.assertIn("На сколько игроков", self.bot.send_message.await_args.args[1])

    async def test_command_opens_wizard_without_holding_funds(self):
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100123, type="supergroup"),
            from_user=SimpleNamespace(id=7, username="player", first_name="Player"),
            text="/2cub 10",
        )

        await self.bot.message_handlers["2cub"](message)

        self.client.create_or_resume_game.assert_not_awaited()
        self.client.create_v2_table.assert_not_awaited()
        self.assertFalse(pvp.active_games)

    def test_pvp_commands_and_allgames_are_registered(self):
        self.assertIn("cub", self.bot.message_handlers)
        self.assertIn("2cub", self.bot.message_handlers)
        self.assertIn("allgames", self.bot.message_handlers)

    def _fill_waiting(self, count, *, prefix="game", creator_id=3):
        for index in range(count):
            pvp.active_games[f"{prefix}-{index}"] = self._waiting_game(f"{prefix}-{index}", creator_id=creator_id)

    async def test_private_lobby_paginates_and_numbers_bubbles(self):
        self._fill_waiting(pvp.PRIVATE_LOBBY_PAGE_SIZE + 1)
        message = SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), from_user=SimpleNamespace(id=7))

        await self.bot.message_handlers["allgames"](message)

        keyboard = self.bot.reply_to.await_args.kwargs["reply_markup"]
        join_buttons = [button for button in keyboard.buttons if button.kwargs["callback_data"].startswith("dmjoin:")]
        self.assertEqual(len(join_buttons), pvp.PRIVATE_LOBBY_PAGE_SIZE)
        self.assertTrue(join_buttons[0].text.startswith("1."))
        self.assertTrue(join_buttons[-1].text.startswith(f"{pvp.PRIVATE_LOBBY_PAGE_SIZE}."))
        nav = [button.text for button in keyboard.buttons]
        self.assertIn("Далее ▶️", nav)
        self.assertIn("🔄 Обновить", nav)
        self.assertNotIn("◀️ Назад", nav)
        _, text = self.bot.reply_to.await_args.args
        self.assertIn("Стр. 1/2", text)
        self.assertNotIn("game-0", text)

    async def test_group_allgames_renders_join_bubbles_not_a_text_list(self):
        pvp.active_games["internal-game-id"] = self._waiting_game()
        pvp.active_games["own-game"] = self._waiting_game("own-game", creator_id=7)
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100123, type="supergroup"),
            from_user=SimpleNamespace(id=7, username="joiner", first_name="Joiner"),
        )

        await self.bot.message_handlers["allgames"](message)

        _, text = self.bot.reply_to.await_args.args
        self.assertIn("Ожидающие игры", text)
        self.assertNotIn("#INTERNAL", text)
        self.assertNotIn("own-game", text)
        keyboard = self.bot.reply_to.await_args.kwargs["reply_markup"]
        join_buttons = [button for button in keyboard.buttons if button.kwargs["callback_data"].startswith("join_")]
        self.assertEqual(len(join_buttons), 1)
        self.assertEqual(join_buttons[0].kwargs["callback_data"], "join_internal-game-id")
        self.assertIn("1.", join_buttons[0].text)
        self.assertIn("Кубики", join_buttons[0].text)
        self.assertIn("25", join_buttons[0].text)

    async def test_group_allgames_paginates_then_edits_on_next(self):
        self._fill_waiting(pvp.PRIVATE_LOBBY_PAGE_SIZE + 1)
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100123, type="supergroup"),
            from_user=SimpleNamespace(id=7, username="joiner", first_name="Joiner"),
        )

        await self.bot.message_handlers["allgames"](message)

        keyboard = self.bot.reply_to.await_args.kwargs["reply_markup"]
        next_button = next(button for button in keyboard.buttons if button.text == "Далее ▶️")
        self.assertEqual(next_button.kwargs["callback_data"], "agpage:1")
        call = SimpleNamespace(
            id="page-1",
            data="agpage:1",
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat=SimpleNamespace(id=-100123, type="supergroup"), message_id=88),
        )

        await self._group_lobby_page_handler()(call)

        self.bot.edit_message_text.assert_awaited_once()
        edited_text = self.bot.edit_message_text.await_args.args[0]
        self.assertIn("Стр. 2/2", edited_text)
        edited_keyboard = self.bot.edit_message_text.await_args.kwargs["reply_markup"]
        join_buttons = [button for button in edited_keyboard.buttons if button.kwargs["callback_data"].startswith("join_")]
        self.assertEqual(len(join_buttons), 1)
        self.assertTrue(join_buttons[0].text.startswith("6."))
        self.assertIn("◀️ Назад", [button.text for button in edited_keyboard.buttons])

    def test_card_invitation_matches_baccarat_even_if_rounds_missing(self):
        self.assertEqual(pvp._pvp_key_for_canonical_type("baccara", 0), "baccara")
        self.assertEqual(pvp._pvp_key_for_canonical_type("baccara", 1), "baccara")
        self.assertEqual(pvp._pvp_key_for_canonical_type("blackjack", None), "blackjack")
        self.assertEqual(pvp._pvp_key_for_canonical_type("pvp_dice", 1), "cub")

    async def test_invitation_pass_posts_baccarat_web_join_not_dice_join(self):
        payload = {
            "game_id": "web-03e1a2745423", "game_type": "baccara", "rounds": 0,
            "chat_id": -100123, "stake_rub": "100", "creator_id": 7,
        }
        self.client.claim_pvp_invitations = AsyncMock(return_value={
            "success": True,
            "items": [{"outbox_id": 11, "claim_token": "claim-1", "payload": payload}],
        })
        self.client.get_active_pvp_games = AsyncMock(return_value=[{
            "game_id": "web-03e1a2745423",
            "game_type": "baccara",
            "status": "waiting",
            "state_version": 2,
            "creator_id": 7,
            "stake_rub": "100.00",
            "created_at": "2026-08-29T09:00:00+00:00",
            "rng_commit": "a" * 64,
        }])
        self.client.persist_game_state = AsyncMock(return_value={"game": {"state_version": 3}})
        self.bot.send_message.return_value = SimpleNamespace(message_id=99)
        self.client.complete_pvp_invitation = AsyncMock()
        self.client.fail_pvp_invitation = AsyncMock()

        processed = await pvp.run_pvp_invitation_pass(self.bot, self.client, worker_id="worker-1")

        self.assertEqual(processed, 1)
        keyboard = self.bot.send_message.await_args.kwargs["reply_markup"]
        self.assertEqual(keyboard.buttons[0].kwargs["callback_data"], "bak_wjoin_web-03e1a2745423")
        self.client.complete_pvp_invitation.assert_awaited_once()
        self.client.fail_pvp_invitation.assert_not_awaited()
        self.client.persist_game_state.assert_awaited()
        self.client.get_active_pvp_games.assert_awaited()

    async def test_group_join_posts_roll_in_group_even_if_cache_is_dm(self):
        game = self._waiting_game()
        game["chat_id"] = 940002
        game["message_id"] = 51
        pvp.active_games["internal-game-id"] = game
        self.bot.send_message.return_value = SimpleNamespace(message_id=62)
        call = SimpleNamespace(
            id="group-join",
            data="join_internal-game-id",
            from_user=SimpleNamespace(id=7, username="joiner", first_name="Joiner"),
            message=SimpleNamespace(chat=SimpleNamespace(id=-100123, type="supergroup"), message_id=51),
        )

        await self._group_join_handler()(call)

        self.client.join_and_hold_game.assert_awaited_once_with(game_id="internal-game-id", opponent_id=7)
        self.assertEqual(pvp.active_games["internal-game-id"]["chat_id"], -100123)
        self.assertEqual(self.bot.send_message.await_args.args[0], -100123)


if __name__ == "__main__":
    unittest.main()
