import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules


with TelebotModules("games.v2_tables", "games.v2_runtime", "games.pvp", "games.site_links"):
    v2_tables = importlib.import_module("games.v2_tables")


class Keyboard:
    def __init__(self, *args, **kwargs):
        self.keyboard = []

    def add(self, button):
        self.keyboard.append([button])


class Button:
    def __init__(self, text, **kwargs):
        self.text = text
        self.callback_data = kwargs.get("callback_data")
        self.url = kwargs.get("url")


class Bot:
    def __init__(self):
        self.send_message = AsyncMock()
        self.answer_callback_query = AsyncMock()
        self.callback_handlers = []

    def callback_query_handler(self, **kwargs):
        def decorator(handler):
            self.callback_handlers.append((kwargs["func"], handler))
            return handler
        return decorator


class V2TablesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_types = v2_tables.types
        v2_tables.types = SimpleNamespace(
            InlineKeyboardMarkup=Keyboard,
            InlineKeyboardButton=Button,
        )
        self.bot = Bot()
        self.bot.delete_message = AsyncMock()
        self.client = SimpleNamespace(
            v2_tables_get=AsyncMock(),
            v2_table_operation=AsyncMock(),
            get_active_pvp_games=AsyncMock(return_value=[]),
            persist_game_state=AsyncMock(return_value={"game": {"state_version": 3}}),
            join_and_hold_game=AsyncMock(return_value={"game": {"state_version": 4, "status": "active"}}),
        )

    def tearDown(self):
        v2_tables.types = self.original_types

    def _open_table(self):
        return {
            "table_id": "a" * 36,
            "game_type": "pvp_dice",
            "creator_id": 10,
            "stake_rub": "100.00",
            "max_players": 4,
            "max_seats": 4,
            "status": "open",
            "state_version": 2,
            "roster": [
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 10},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Bot"}},
            ],
            "free_seats": [3, 4],
        }

    def test_create_payload_enforces_telegram_limits(self):
        payload = v2_tables.create_payload(
            game_key="cub", creator_id=10, stake=100, max_players=6, bot_count=3, draw_policy="tie_split", rounds=2
        )
        self.assertEqual(payload["game_type"], "pvp_dice")
        self.assertEqual(payload["stake_rub"], "100.00")
        self.assertEqual(payload["draw_policy"], "tie_split")
        self.assertEqual(payload["rounds"], 2)
        with self.assertRaises(ValueError):
            v2_tables.create_payload(game_key="cub", creator_id=10, stake=100, max_players=6, bot_count=6)
        with self.assertRaises(ValueError):
            v2_tables.create_payload(game_key="cub", creator_id=10, stake=100, max_players=1, bot_count=0)

    def test_roster_controls_lobby_counts_and_participation(self):
        table = self._open_table()
        self.assertEqual(v2_tables._seat_counts(table), (1, 1, 2))
        self.assertTrue(v2_tables._is_joinable(table, 77))
        self.assertFalse(v2_tables._is_joinable(table, 10))
        self.assertIn("Людей: 1, ботов: 1, свободно: 2", v2_tables._lobby_text([table], 77))

    def test_empty_lobby_still_has_hub_and_refresh(self):
        text = v2_tables._lobby_text([], 77)
        keyboard = v2_tables._lobby_keyboard([], 77)
        callbacks = [button[0].callback_data for button in keyboard.keyboard]
        self.assertIn("Рулетка и джекпот", text)
        self.assertNotIn("нет доступных ожидающих", text)
        self.assertEqual(callbacks[0], "hub:roulette")
        self.assertEqual(callbacks[1], "hub:jackpot")
        self.assertIn("v2lobby:refresh", callbacks)

    def test_lobby_lists_open_room_join(self):
        room = {
            "room_id": "fr-aabbccddeeff",
            "status": "open",
            "stake_rub": 100.0,
            "seat_count": 3,
            "filled": 1,
            "free_seats": [1, 2],
            "my_seat": None,
            "rake_percent": 5.0,
        }
        text = v2_tables._lobby_text([], 77, [], [room])
        keyboard = v2_tables._lobby_keyboard([], 77, [], [room])
        callbacks = [button[0].callback_data for button in keyboard.keyboard if button[0].callback_data]
        self.assertIn("100.0 ₽", text)
        self.assertIn("1/3", text)
        self.assertIn("rm:join:fr-aabbccddeeff", callbacks)

    def _waiting_baccarat(self, creator_id=940002):
        return {
            "game_id": "web-03e1a2745423",
            "game_type": "baccara",
            "status": "waiting",
            "creator_id": creator_id,
            "opponent_id": None,
            "stake_rub": "100.00",
            "state_version": 2,
            "rounds": 0,
        }

    def test_dm_lobby_lists_waiting_web_baccarat_for_join(self):
        duel = self._waiting_baccarat()
        text = v2_tables._lobby_text([], 77, [duel])
        keyboard = v2_tables._lobby_keyboard([], 77, [duel])
        callbacks = [button[0].callback_data for button in keyboard.keyboard if button[0].callback_data]

        self.assertIn("WEB-03E1", text)
        self.assertIn("Baccara", text)
        self.assertIn("100.00", text)
        self.assertNotIn("нет доступных ожидающих", text)
        self.assertIn("bak_wjoin_web-03e1a2745423", callbacks)

    def test_dm_lobby_shows_own_waiting_web_baccarat_without_join(self):
        duel = self._waiting_baccarat()
        text = v2_tables._lobby_text([], 940002, [duel])
        keyboard = v2_tables._lobby_keyboard([], 940002, [duel])
        callbacks = [
            button[0].callback_data
            for button in (keyboard.keyboard if keyboard else [])
            if button and button[0].callback_data
        ]

        self.assertIn("ваша игра, ждёт соперника", text)
        self.assertNotIn("bak_wjoin_web-03e1a2745423", callbacks)

    def test_my_games_lists_own_waiting_web_baccarat(self):
        duel = self._waiting_baccarat()
        self.assertTrue(v2_tables._is_mine_duel(duel, 940002))
        self.assertFalse(v2_tables._is_joinable_duel(duel, 940002))
        self.assertIn("WEB-03E1", v2_tables._duel_line(duel, own=True))

    def test_own_waiting_duel_gets_site_url_when_miniapp_configured(self):
        original = v2_tables.config.CASINO_MINIAPP_URL
        v2_tables.config.CASINO_MINIAPP_URL = "http://127.0.0.1:18081/casino/tg"
        try:
            keyboard = v2_tables._lobby_keyboard([], 940002, [self._waiting_baccarat()])
            urls = [button[0].url for button in keyboard.keyboard if button[0].url]
        finally:
            v2_tables.config.CASINO_MINIAPP_URL = original

        self.assertEqual(urls, ["http://127.0.0.1:18081/casino/duels/web-03e1a2745423"])

    async def test_my_games_include_table_watch_url(self):
        original = v2_tables.config.CASINO_MINIAPP_URL
        v2_tables.config.CASINO_MINIAPP_URL = "http://127.0.0.1:18081/casino/tg"
        self.client.v2_tables_get.return_value = {"tables": [self._open_table()]}
        self.client.get_active_pvp_games.return_value = []
        original_warm = v2_tables._warm_duel_caches
        v2_tables._warm_duel_caches = AsyncMock()
        try:
            await v2_tables.send_v2_my_tables(self.bot, self.client, 10, 10)
        finally:
            v2_tables._warm_duel_caches = original_warm
            v2_tables.config.CASINO_MINIAPP_URL = original
        markup = self.bot.send_message.await_args.kwargs.get("reply_markup")
        urls = [button[0].url for button in markup.keyboard if button and button[0].url]
        self.assertIn("http://127.0.0.1:18081/casino/tables/" + "a" * 36, urls)

    async def test_send_my_tables_includes_waiting_duel(self):
        self.client.v2_tables_get.return_value = {"tables": []}
        self.client.get_active_pvp_games.return_value = [self._waiting_baccarat()]
        original_warm = v2_tables._warm_duel_caches
        v2_tables._warm_duel_caches = AsyncMock()
        try:
            await v2_tables.send_v2_my_tables(self.bot, self.client, 940002, 940002)
        finally:
            v2_tables._warm_duel_caches = original_warm

        text = self.bot.send_message.await_args.args[1]
        self.assertIn("WEB-03E1", text)
        self.assertIn("Baccara", text)
        self.assertNotIn("нет активных игр", text)

    async def test_join_uses_current_state_version(self):
        table = self._open_table()
        self.client.v2_tables_get.return_value = {"tables": [table]}
        v2_tables.register_v2_table_handlers(self.bot, self.client)
        handler = next(
            handler for predicate, handler in self.bot.callback_handlers
            if predicate(SimpleNamespace(data=f"v2join:{table['table_id']}"))
        )
        call = SimpleNamespace(
            id="join",
            data=f"v2join:{table['table_id']}",
            from_user=SimpleNamespace(id=77),
            message=SimpleNamespace(chat=SimpleNamespace(id=77, type="private")),
        )

        await handler(call)

        kwargs = self.client.v2_table_operation.await_args.kwargs
        self.assertEqual(self.client.v2_table_operation.await_args.args[:2], (table["table_id"], "seats"))
        self.assertEqual(kwargs["telegram_id"], 77)
        self.assertEqual(kwargs["expected_state_version"], 2)
        self.bot.send_message.assert_not_awaited()
        args, kwargs_cb = self.bot.answer_callback_query.await_args
        self.assertEqual(args[0], "join")
        self.assertIn("Вы заняли место", args[1])
        self.assertNotIn("show_alert", kwargs_cb)

    def _join_handler(self, data: str):
        v2_tables.register_v2_table_handlers(self.bot, self.client)
        return next(
            handler for predicate, handler in self.bot.callback_handlers
            if predicate(SimpleNamespace(data=data))
        )

    def _join_call(self, data: str, *, call_id="join", user_id=77, chat_id=None, message_id=101):
        chat = chat_id if chat_id is not None else user_id
        return SimpleNamespace(
            id=call_id,
            data=data,
            from_user=SimpleNamespace(id=user_id),
            message=SimpleNamespace(
                chat=SimpleNamespace(id=chat, type="private" if chat > 0 else "supergroup"),
                message_id=message_id,
            ),
        )

    async def test_join_failure_uses_callback_alert(self):
        table = self._open_table()
        self.client.v2_tables_get.return_value = {"tables": [table]}
        self.client.v2_table_operation.side_effect = v2_tables.httpx.HTTPStatusError(
            "conflict",
            request=v2_tables.httpx.Request("POST", "http://v2/seats"),
            response=v2_tables.httpx.Response(409),
        )
        handler = self._join_handler(f"v2join:{table['table_id']}")

        await handler(self._join_call(f"v2join:{table['table_id']}"))

        self.bot.send_message.assert_not_awaited()
        self.bot.answer_callback_query.assert_awaited_once()
        args, kwargs = self.bot.answer_callback_query.await_args
        self.assertEqual(args[0], "join")
        self.assertIn("стол уже заполнен", args[1])
        self.assertTrue(kwargs.get("show_alert"))

    async def test_join_missing_table_mentions_refund(self):
        self.client.v2_tables_get.return_value = {"tables": []}
        handler = self._join_handler(f"v2join:{'a' * 36}")

        await handler(self._join_call(f"v2join:{'a' * 36}"))

        self.bot.send_message.assert_not_awaited()
        args, kwargs = self.bot.answer_callback_query.await_args
        self.assertIn("отменён или истёк", args[1])
        self.assertIn("ставка вернулась", args[1])
        self.assertTrue(kwargs.get("show_alert"))

    async def test_join_unknown_error_uses_callback_alert(self):
        table = self._open_table()
        self.client.v2_tables_get.return_value = {"tables": [table]}
        self.client.v2_table_operation.side_effect = RuntimeError("backend down")
        handler = self._join_handler(f"v2join:{table['table_id']}")

        await handler(self._join_call(f"v2join:{table['table_id']}"))

        self.bot.send_message.assert_not_awaited()
        args, kwargs = self.bot.answer_callback_query.await_args
        self.assertIn("Попробуйте позже", args[1])
        self.assertTrue(kwargs.get("show_alert"))

    async def test_duel_join_failure_uses_callback_alert(self):
        handler = self._join_handler("dueljoin:web-03e1a2745423")
        with patch("games.pvp.join_waiting_dice_from_dm", AsyncMock(side_effect=ValueError("full"))):
            await handler(self._join_call("dueljoin:web-03e1a2745423"))

        self.bot.send_message.assert_not_awaited()
        args, kwargs = self.bot.answer_callback_query.await_args
        self.assertIn("дуэль уже занята", args[1])
        self.assertTrue(kwargs.get("show_alert"))

    async def test_add_bot_uses_bots_operation(self):
        table = self._open_table()
        self.client.v2_tables_get.return_value = {"tables": [table]}
        self.client.v2_table_operation.return_value = {"table": table, "auto_started": False}
        v2_tables.register_v2_table_handlers(self.bot, self.client)
        handler = next(
            handler for predicate, handler in self.bot.callback_handlers
            if predicate(SimpleNamespace(data=f"v2bot:{table['table_id']}"))
        )
        call = SimpleNamespace(
            id="bot",
            data=f"v2bot:{table['table_id']}",
            from_user=SimpleNamespace(id=10),
            message=SimpleNamespace(chat=SimpleNamespace(id=10, type="private")),
        )
        with patch("games.v2_runtime.after_table_join", AsyncMock()):
            await handler(call)
        self.assertEqual(self.client.v2_table_operation.await_args.args[:2], (table["table_id"], "bots"))
        self.assertEqual(self.client.v2_table_operation.await_args.kwargs["telegram_id"], 10)
        self.bot.send_message.assert_not_awaited()
        args, kwargs = self.bot.answer_callback_query.await_args
        self.assertIn("Бот сел", args[1])
        self.assertTrue(kwargs.get("show_alert"))

    async def test_add_bot_failure_uses_callback_alert(self):
        table = self._open_table()
        self.client.v2_tables_get.return_value = {"tables": [table]}
        self.client.v2_table_operation.side_effect = ValueError("full")
        handler = self._join_handler(f"v2bot:{table['table_id']}")

        await handler(self._join_call(f"v2bot:{table['table_id']}", call_id="bot", user_id=10))

        self.bot.send_message.assert_not_awaited()
        args, kwargs = self.bot.answer_callback_query.await_args
        self.assertIn("посадить бота", args[1])
        self.assertTrue(kwargs.get("show_alert"))

    async def test_leave_success_uses_callback_alert(self):
        table = self._open_table()
        self.client.v2_tables_get.return_value = {"tables": [table]}
        handler = self._join_handler(f"v2leave:{table['table_id']}")

        await handler(self._join_call(f"v2leave:{table['table_id']}", call_id="leave", user_id=10))

        self.bot.send_message.assert_not_awaited()
        self.assertEqual(self.client.v2_table_operation.await_args.args[:2], (table["table_id"], "leave"))
        args, kwargs = self.bot.answer_callback_query.await_args
        self.assertIn("вышли", args[1])
        self.assertTrue(kwargs.get("show_alert"))

    async def test_cancel_failure_uses_callback_alert(self):
        table = self._open_table()
        self.client.v2_tables_get.return_value = {"tables": [table]}
        self.client.v2_table_operation.side_effect = ValueError("gone")
        handler = self._join_handler(f"v2cancel:{table['table_id']}")

        await handler(self._join_call(f"v2cancel:{table['table_id']}", call_id="cancel", user_id=10))

        self.bot.send_message.assert_not_awaited()
        args, kwargs = self.bot.answer_callback_query.await_args
        self.assertIn("уже недоступно", args[1])
        self.assertTrue(kwargs.get("show_alert"))

    async def test_rejected_cancel_preserves_active_card(self):
        import httpx

        table = self._open_table()
        table["game_state"] = {"play_chats": [{"chat_id": -100123, "card_msg_id": 71}]}
        self.client.v2_tables_get.return_value = {"tables": [table]}
        handler = self._join_handler(f"v2cancel:{table['table_id']}")
        for status in (403, 409, 500):
            with self.subTest(status=status):
                self.bot.delete_message.reset_mock()
                response = httpx.Response(status, request=httpx.Request("POST", "http://backend/cancel"))
                self.client.v2_table_operation.side_effect = httpx.HTTPStatusError(
                    "rejected", request=response.request, response=response,
                )
                with patch.object(v2_tables, "_discard_callback_card", new_callable=AsyncMock) as discard:
                    await handler(self._join_call(
                        f"v2cancel:{table['table_id']}", user_id=77,
                        chat_id=-100123, message_id=71,
                    ))
                    discard.assert_not_awaited()
                self.bot.delete_message.assert_not_awaited()

    async def test_cancel_deletes_group_card(self):
        table = self._open_table()
        table["game_state"] = {
            "play_chats": [{"chat_id": -100123, "card_msg_id": 71}],
            "listing_chat_id": -100123,
            "listing_msg_id": 80,
        }
        self.client.v2_tables_get.return_value = {"tables": [table]}
        handler = self._join_handler(f"v2cancel:{table['table_id']}")

        await handler(self._join_call(
            f"v2cancel:{table['table_id']}",
            call_id="cancel",
            user_id=10,
            chat_id=-100123,
            message_id=71,
        ))

        deleted = {(call.args[0], call.args[1]) for call in self.bot.delete_message.await_args_list}
        self.assertEqual(deleted, {(-100123, 71), (-100123, 80)})
        args, kwargs = self.bot.answer_callback_query.await_args
        self.assertIn("отменён", args[1])
        self.assertTrue(kwargs.get("show_alert"))

    async def test_join_gone_deletes_stale_card(self):
        self.client.v2_tables_get.return_value = {"tables": []}
        handler = self._join_handler(f"v2join:{'a' * 36}")

        await handler(self._join_call(
            f"v2join:{'a' * 36}",
            chat_id=-100123,
            message_id=71,
        ))

        self.bot.delete_message.assert_awaited_once_with(-100123, 71)

    async def test_cancel_uses_remembered_card_when_active_row_has_no_ids(self):
        table = self._open_table()
        table["game_state"] = {}
        remembered = {
            **table,
            "game_state": {"play_chats": [{"chat_id": -100123, "card_msg_id": 71}]},
        }
        self.client.v2_tables_get.return_value = {"tables": [table]}
        handler = self._join_handler(f"v2cancel:{table['table_id']}")
        with patch("games.v2_runtime.recall_table", return_value=remembered):
            await handler(self._join_call(
                f"v2cancel:{table['table_id']}",
                call_id="cancel",
                user_id=10,
                chat_id=-100123,
                message_id=99,
            ))
        deleted = {(call.args[0], call.args[1]) for call in self.bot.delete_message.await_args_list}
        self.assertIn((-100123, 71), deleted)
        self.assertIn((-100123, 99), deleted)


if __name__ == "__main__":
    unittest.main()
