import importlib
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules


with TelebotModules("games.table_wizard", "games.v2_tables", "games.v2_runtime", "games.pvp", "games.house_cub", "games.site_links"):
    wizard = importlib.import_module("games.table_wizard")


class Keyboard:
    def __init__(self, *args, **kwargs):
        self.keyboard = []

    def add(self, *buttons):
        self.keyboard.append(list(buttons))


class Button:
    def __init__(self, text, callback_data=None, **kwargs):
        self.text = text
        self.callback_data = callback_data


class TableWizardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_types = wizard.types
        wizard.types = SimpleNamespace(InlineKeyboardMarkup=Keyboard, InlineKeyboardButton=Button)
        wizard._sessions.clear()
        wizard._awaiting_custom.clear()

    def tearDown(self):
        wizard.types = self.original_types
        wizard._sessions.clear()
        wizard._awaiting_custom.clear()

    def test_entry_denied_reason_is_visible(self):
        from telegram_reliability import EntryDenied
        reason = 'Боту запрещено отправлять сообщения. Ставка не принята.'
        self.assertIn(reason, wizard._v2_create_error_text(EntryDenied(reason)))

    async def test_finalize_creates_v2_table_with_draw_policy(self):
        bot = SimpleNamespace(
            edit_message_text=AsyncMock(),
            send_message=AsyncMock(),
        )
        client = AsyncMock()
        client.create_v2_table = AsyncMock(return_value={"table": {"table_id": "tbl", "status": "open", "state_version": 0, "game_state": {}, "game_type": "pvp_dice"}})
        client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -100123})
        call = SimpleNamespace(
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=3),
        )
        entry = {
            "family": "cub", "game_key": "cub", "rolls": 1, "max_players": 3, "bot_count": 0,
            "draw_policy": "tie_split", "stake": Decimal("50"), "chat_id": None,
        }
        with patch("games.v2_runtime.publish_created_table", AsyncMock()) as publish:
            with patch.object(wizard.config, "CASINO_MINIAPP_URL", "http://127.0.0.1:18081/casino/tg"):
                await wizard._finalize(bot, client, call, entry)
        kwargs = client.create_v2_table.await_args.kwargs
        self.assertEqual(kwargs["draw_policy"], "tie_split")
        self.assertEqual(kwargs["max_players"], 3)
        self.assertEqual(kwargs["bot_count"], 0)
        self.assertEqual(kwargs["game_type"], "pvp_dice")
        self.assertEqual(kwargs["game_chat_id"], 7)
        publish.assert_awaited_once()
        self.assertEqual(publish.await_args.kwargs.get("existing_message"), (7, 3))
        bot.edit_message_text.assert_not_awaited()
        from games.v2_runtime import format_v2_settlement
        text = format_v2_settlement({
            "outcome_kind": "winner", "table_id": "abc", "pot_rub": "1",
            "payouts": [{"seat_no": 1, "amount_rub": "1"}],
        })
        self.assertIn("Победил:", text)
        self.assertIn("место 1", text)

    async def test_dm_cub_two_seats_one_bot_creates_v2_table(self):
        bot = SimpleNamespace(edit_message_text=AsyncMock(), send_message=AsyncMock())
        client = AsyncMock()
        client.create_v2_table = AsyncMock(return_value={
            "auto_started": True,
            "table": {
                "table_id": "tbl", "status": "running", "state_version": 1,
                "game_state": {"bot_count": 1, "rounds": 1}, "game_type": "pvp_dice",
                "game_chat_id": 7,
            },
        })
        call = SimpleNamespace(
            from_user=SimpleNamespace(id=7, first_name="Алекс", username="alex"),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=3),
        )
        entry = {
            "family": "cub", "game_key": "cub", "rolls": 1, "max_players": 2, "bot_count": 1,
            "draw_policy": "tie_break", "stake": Decimal("50"), "chat_id": 7,
        }
        with patch("games.v2_runtime.publish_created_table", AsyncMock()) as publish:
            await wizard._finalize(bot, client, call, entry)
        client.open_cub.assert_not_awaited()
        kwargs = client.create_v2_table.await_args.kwargs
        self.assertEqual(kwargs["game_type"], "pvp_dice")
        self.assertEqual(kwargs["bot_count"], 1)
        self.assertEqual(kwargs["game_chat_id"], 7)
        self.assertEqual(kwargs["rounds"], 1)
        publish.assert_awaited_once()

    async def test_start_wizard_from_menu_uses_player_not_bot_author(self):
        bot = SimpleNamespace(send_message=AsyncMock(), reply_to=AsyncMock())
        client = AsyncMock()
        client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -100123})
        message = SimpleNamespace(
            chat=SimpleNamespace(id=7, type="private"),
            from_user=SimpleNamespace(id=999001),
        )
        await wizard.start_wizard(bot, client, message, user=SimpleNamespace(id=7))
        bot.send_message.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.args[0], 7)
        bot.reply_to.assert_not_awaited()


    def test_create_conflict_explains_missing_card_bots(self):
        response = SimpleNamespace(json=lambda: {"detail": "V2 bot capacity is unavailable"})
        text = wizard._v2_create_error_text(SimpleNamespace(response=response))
        self.assertIn("бота", text)
        self.assertNotIn("позже", text)

    async def test_finalize_create_error_uses_callback_alert(self):
        bot = SimpleNamespace(
            edit_message_text=AsyncMock(),
            send_message=AsyncMock(),
            answer_callback_query=AsyncMock(),
        )
        client = AsyncMock()
        client.create_v2_table = AsyncMock(side_effect=RuntimeError("no bots"))
        call = SimpleNamespace(
            id="confirm",
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=3),
        )
        entry = {
            "family": "cub", "game_key": "cub", "rolls": 1, "max_players": 3, "bot_count": 0,
            "draw_policy": "tie_split", "stake": Decimal("50"), "chat_id": None,
        }
        ok = await wizard._finalize(bot, client, call, entry)
        self.assertFalse(ok)
        bot.send_message.assert_not_awaited()
        bot.edit_message_text.assert_not_awaited()
        args, kwargs = bot.answer_callback_query.await_args
        self.assertEqual(args[0], "confirm")
        self.assertIn("Не удалось создать стол", args[1])
        self.assertTrue(kwargs.get("show_alert"))

    async def test_finalize_retry_reuses_original_create_request(self):
        bot = SimpleNamespace(answer_callback_query=AsyncMock(), delete_message=AsyncMock())
        client = SimpleNamespace(create_v2_table=AsyncMock(side_effect=[
            TimeoutError("response lost after commit"), {"table": {"table_id": "same"}},
        ]))
        call = SimpleNamespace(id="first", from_user=SimpleNamespace(id=7),
                               message=SimpleNamespace(chat=SimpleNamespace(id=7), message_id=3))
        entry = {"family": "cub", "game_key": "cub", "max_players": 2,
                 "bot_count": 1, "draw_policy": "tie_split", "stake": Decimal("50"), "chat_id": 7}
        with patch("games.v2_runtime.publish_created_table", new_callable=AsyncMock):
            self.assertFalse(await wizard._finalize(bot, client, call, entry))
            call.id = "second"
            self.assertTrue(await wizard._finalize(bot, client, call, entry))
        first, second = client.create_v2_table.await_args_list
        self.assertEqual(first.kwargs, second.kwargs)

    async def test_confirm_token_is_single_use_after_success(self):
        bot = SimpleNamespace(
            callback_handlers=[],
            answer_callback_query=AsyncMock(),
            edit_message_text=AsyncMock(),
            send_message=AsyncMock(),
            delete_message=AsyncMock(),
        )

        def callback_query_handler(*, func):
            def decorator(handler):
                bot.callback_handlers.append((func, handler))
                return handler
            return decorator

        def message_handler(**kwargs):
            def decorator(handler):
                return handler
            return decorator

        bot.callback_query_handler = callback_query_handler
        bot.message_handler = message_handler
        client = AsyncMock()
        client.create_v2_table = AsyncMock(return_value={"table": {
            "table_id": "same", "status": "open", "state_version": 0,
            "game_state": {}, "game_type": "pvp_dice",
        }})
        client.get_active_game_chat_binding = AsyncMock(return_value=None)
        with patch.object(wizard.config, "CASINO_MINIAPP_URL", "http://127.0.0.1:18081/casino/tg"):
            wizard.register_table_wizard_handlers(bot, client)
        token = wizard._issue(
            7, step="confirm", family="cub", game_key="cub", rolls=1,
            max_players=2, bot_count=0, draw_policy="tie_split",
            stake=Decimal("50"), chat_id=7,
        )
        handler = next(
            handler for predicate, handler in bot.callback_handlers
            if predicate(SimpleNamespace(data=f"tw:{token}"))
        )
        call = SimpleNamespace(
            id="confirm-1", data=f"tw:{token}",
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=9),
        )
        with patch("games.v2_runtime.publish_created_table", new_callable=AsyncMock) as publish:
            with patch.object(wizard.config, "CASINO_MINIAPP_URL", "http://127.0.0.1:18081/casino/tg"):
                await handler(call)
                self.assertNotIn(token, wizard._sessions)
                second = SimpleNamespace(
                    id="confirm-2", data=f"tw:{token}",
                    from_user=SimpleNamespace(id=7),
                    message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=9),
                )
                await handler(second)
        client.create_v2_table.assert_awaited_once()
        publish.assert_awaited_once()
        texts = [str(args[1]) if len(args) > 1 else "" for args, _ in bot.answer_callback_query.await_args_list]
        self.assertTrue(any("уже использовано" in text or "устарел" in text for text in texts))

    async def test_finalize_missing_stake_uses_callback_alert(self):
        bot = SimpleNamespace(send_message=AsyncMock(), answer_callback_query=AsyncMock())
        call = SimpleNamespace(
            id="confirm",
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=3),
        )
        entry = {
            "family": "cub", "game_key": "cub", "rolls": 1, "max_players": 3, "bot_count": 0,
            "draw_policy": "tie_break", "stake": None, "chat_id": None,
        }
        ok = await wizard._finalize(bot, AsyncMock(), call, entry)
        self.assertFalse(ok)
        bot.send_message.assert_not_awaited()
        self.assertIn("Ставка не задана", bot.answer_callback_query.await_args.args[1])
        self.assertTrue(bot.answer_callback_query.await_args.kwargs.get("show_alert"))

    def test_bots_keyboard_does_not_crash_when_max_players_already_in_fields(self):
        entry = {"family": "cub", "game_key": "cub", "max_players": 3, "step": "players", "owner_id": 7}
        markup = wizard._bots_keyboard(7, int(entry["max_players"]), **wizard._carry(entry, "max_players"))
        self.assertEqual(len(markup.keyboard), 3)

    async def test_rolls_callback_asks_how_many_players(self):
        bot = SimpleNamespace(
            callback_handlers=[],
            edit_message_text=AsyncMock(),
            answer_callback_query=AsyncMock(),
            send_message=AsyncMock(),
        )

        def callback_query_handler(*, func):
            def decorator(handler):
                bot.callback_handlers.append((func, handler))
                return handler
            return decorator

        def message_handler(**kwargs):
            def decorator(handler):
                return handler
            return decorator

        bot.callback_query_handler = callback_query_handler
        bot.message_handler = message_handler
        client = AsyncMock()
        wizard.register_table_wizard_handlers(bot, client)
        token = wizard._issue(7, step="rolls", family="cub", rolls=2, chat_id=7)
        handler = next(handler for predicate, handler in bot.callback_handlers if predicate(SimpleNamespace(data=f"tw:{token}")))
        call = SimpleNamespace(
            id="rolls-1",
            data=f"tw:{token}",
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=9),
        )
        await handler(call)
        bot.edit_message_text.assert_awaited()
        self.assertIn("игроков", bot.edit_message_text.await_args.args[0])
        self.assertIn("x2", bot.edit_message_text.await_args.args[0])
        bot.answer_callback_query.assert_awaited()

    async def test_players_callback_skips_bots_asks_draw(self):
        bot = SimpleNamespace(
            callback_handlers=[],
            edit_message_text=AsyncMock(),
            answer_callback_query=AsyncMock(),
            send_message=AsyncMock(),
        )

        def callback_query_handler(*, func):
            def decorator(handler):
                bot.callback_handlers.append((func, handler))
                return handler
            return decorator

        def message_handler(**kwargs):
            def decorator(handler):
                return handler
            return decorator

        bot.callback_query_handler = callback_query_handler
        bot.message_handler = message_handler
        client = AsyncMock()
        wizard.register_table_wizard_handlers(bot, client)
        token = wizard._issue(7, step="players", family="cub", rolls=1, game_key="cub", max_players=4, chat_id=7)
        handler = next(handler for predicate, handler in bot.callback_handlers if predicate(SimpleNamespace(data=f"tw:{token}")))
        call = SimpleNamespace(
            id="players-1",
            data=f"tw:{token}",
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=9),
        )
        await handler(call)
        text = bot.edit_message_text.await_args.args[0]
        self.assertIn("ничьей", text)
        self.assertNotIn("ботов добавить", text)

    async def test_baccara_players_skip_draw_and_keep_redeal(self):
        bot = SimpleNamespace(
            callback_handlers=[],
            answer_callback_query=AsyncMock(),
            edit_message_text=AsyncMock(),
            send_message=AsyncMock(),
        )

        def callback_query_handler(*, func):
            def decorator(handler):
                bot.callback_handlers.append((func, handler))
                return handler
            return decorator

        def message_handler(**kwargs):
            def decorator(handler):
                return handler
            return decorator

        bot.callback_query_handler = callback_query_handler
        bot.message_handler = message_handler
        client = AsyncMock()
        wizard.register_table_wizard_handlers(bot, client)
        token = wizard._issue(7, step="players", family="baccara", game_key="baccara", max_players=2, chat_id=7)
        handler = next(handler for predicate, handler in bot.callback_handlers if predicate(SimpleNamespace(data=f"tw:{token}")))
        call = SimpleNamespace(
            id="players-ba",
            data=f"tw:{token}",
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=9),
        )
        await handler(call)
        text = bot.edit_message_text.await_args.args[0]
        self.assertIn("Выберите ставку", text)
        self.assertIn("переброс лидеров", text)
        self.assertNotIn("Что делать при ничьей", text)

    def test_type_keyboard_lists_hub_games(self):
        markup = wizard._type_keyboard(7, chat_id=7)
        labels = [button.text for row in markup.keyboard for button in row]
        self.assertIn("🎲 Кубики", labels)
        self.assertIn("🃏 Baccara", labels)
        self.assertIn("🂡 Blackjack", labels)
        self.assertIn("🎡 Рулетка", labels)
        self.assertIn("🎡 Джекпот", labels)
        self.assertIn("🎯 Комнаты", labels)

    async def test_roulette_hub_opens_command_and_skips_v2_create(self):
        bot = SimpleNamespace(
            callback_handlers=[],
            answer_callback_query=AsyncMock(),
            edit_message_text=AsyncMock(),
            send_message=AsyncMock(),
        )

        def callback_query_handler(*, func):
            def decorator(handler):
                bot.callback_handlers.append((func, handler))
                return handler
            return decorator

        def message_handler(**kwargs):
            def decorator(handler):
                return handler
            return decorator

        bot.callback_query_handler = callback_query_handler
        bot.message_handler = message_handler
        client = AsyncMock()
        client.create_v2_table = AsyncMock()
        wizard.register_table_wizard_handlers(bot, client)
        token = wizard._issue(7, step="type", family="roulette", chat_id=7)
        handler = next(
            handler for predicate, handler in bot.callback_handlers
            if predicate(SimpleNamespace(data=f"tw:{token}"))
        )
        call = SimpleNamespace(
            id="hub-1",
            data=f"tw:{token}",
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=9),
        )
        with patch("games.roulette_table.handle_roulette_command", AsyncMock()) as roulette:
            await handler(call)
        roulette.assert_awaited_once()
        proxy = roulette.await_args.args[2]
        self.assertEqual(proxy.text, "/roulette")
        self.assertEqual(proxy.from_user.id, 7)
        client.create_v2_table.assert_not_awaited()

    async def test_rooms_hub_opens_create_flow_not_v2(self):
        bot = SimpleNamespace(edit_message_text=AsyncMock(), send_message=AsyncMock())
        client = AsyncMock()
        client.create_v2_table = AsyncMock()
        call = SimpleNamespace(
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=3),
        )
        with patch("games.rooms.start_room_create", AsyncMock()) as start:
            await wizard._dispatch_hub(bot, client, call, "rooms")
        start.assert_awaited_once()
        client.create_v2_table.assert_not_awaited()

    async def test_group_slash_command_deletes_player_message(self):
        bot = SimpleNamespace(send_message=AsyncMock(), reply_to=AsyncMock())
        client = AsyncMock()
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-5562276559, type="group"),
            from_user=SimpleNamespace(id=7),
            text="/baccara 100",
            message_id=44,
        )
        with patch.object(wizard.ActiveGameChatGuard, "allows_entry", AsyncMock(return_value=True)):
            with patch.object(wizard, "try_delete_user_message", AsyncMock()) as purge:
                await wizard.start_wizard_for_command(bot, client, message, "baccara")
        bot.send_message.assert_awaited()
        bot.reply_to.assert_not_awaited()
        purge.assert_awaited_once_with(bot, message)

    async def test_callback_wizard_does_not_delete_board_message(self):
        bot = SimpleNamespace(send_message=AsyncMock(), reply_to=AsyncMock())
        client = AsyncMock()
        board = SimpleNamespace(
            chat=SimpleNamespace(id=-5562276559, type="group"),
            message_id=90,
        )
        call_user = SimpleNamespace(id=7)
        with patch.object(wizard.ActiveGameChatGuard, "allows_entry", AsyncMock(return_value=True)):
            with patch.object(wizard, "try_delete_user_message", AsyncMock()) as purge:
                await wizard.start_wizard_for_command(
                    bot, client, board, "baccara", user=call_user
                )
        purge.assert_not_awaited()
        bot.send_message.assert_awaited()


if __name__ == "__main__":
    unittest.main()
