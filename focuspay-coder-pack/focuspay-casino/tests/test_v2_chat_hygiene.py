import asyncio
import importlib
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules


with TelebotModules(
    "games.v2_chat_ledger", "games.v2_runtime", "games.v2_tables", "games.site_links",
):
    ledger = importlib.import_module("games.v2_chat_ledger")
    runtime = importlib.import_module("games.v2_runtime")
    v2_tables = importlib.import_module("games.v2_tables")


TABLE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class Keyboard:
    def __init__(self, *args, **kwargs):
        self.keyboard = []

    def add(self, *buttons):
        self.keyboard.append(list(buttons))


class Button:
    def __init__(self, text, callback_data=None, **kwargs):
        self.text = text
        self.callback_data = callback_data
        self.url = kwargs.get("url")


class TableClient:
    def __init__(self, table):
        self.table = table

    async def v2_tables_get(self, path):
        return {"tables": [dict(self.table)]}

    async def v2_table_operation(self, table_id, operation, **kwargs):
        if operation == "persist-state":
            state = dict(self.table.get("game_state") or {})
            state.update(kwargs["game_state"])
            self.table["game_state"] = state
            self.table["state_version"] = int(self.table.get("state_version") or 0) + 1
            return {"table": dict(self.table)}
        if operation == "commit-outcome":
            self.table["status"] = "outcome_committed"
            self.table["state_version"] = int(self.table.get("state_version") or 0) + 1
            return {"table": dict(self.table)}
        if operation == "settle-committed-outcome":
            self.table["status"] = "finished"
            self.table["state_version"] = int(self.table.get("state_version") or 0) + 1
            return {
                "outcome_kind": "winner",
                "table_id": table_id,
                "winner_seat_nos": [1],
                "pot_rub": "50.00",
                "commission_rub": "2.50",
                "payouts": [{"seat_no": 1, "amount_rub": "47.50"}],
                "table": dict(self.table),
            }
        raise AssertionError(operation)

    async def v2_table_cards(self, table_id, operation, **payload):
        if operation == "reveal":
            return {"rng_seed": "ab" * 32}
        raise AssertionError(operation)

    async def get_active_game_chat_binding(self):
        return None


class V2ChatHygieneTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_types = runtime.types
        runtime.types = SimpleNamespace(InlineKeyboardMarkup=Keyboard, InlineKeyboardButton=Button)
        runtime.SCORE_BEAT_SECONDS = 0
        import games.card_streets as card_streets
        import games.drama as drama

        self._street_pause = card_streets.STREET_PAUSE_SECONDS
        self._result_beat = card_streets.RESULT_BEAT_SECONDS
        self._min_edit = drama.MIN_EDIT_INTERVAL
        card_streets.STREET_PAUSE_SECONDS = 0
        card_streets.RESULT_BEAT_SECONDS = 0
        drama.MIN_EDIT_INTERVAL = 0
        drama.reset_state()
        ledger.reset_ledger_state()
        self.bot = SimpleNamespace(
            edit_message_text=AsyncMock(),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=200)),
            delete_message=AsyncMock(),
            send_dice=AsyncMock(return_value=SimpleNamespace(
                message_id=80, dice=SimpleNamespace(emoji="🎲", value=4),
            )),
            answer_callback_query=AsyncMock(),
            get_chat=AsyncMock(return_value=SimpleNamespace(first_name="Шеруд", username=None)),
        )

    async def asyncTearDown(self):
        await runtime.drain_ready_watchers()
        from games.drama import drain_drama, reset_state
        import games.card_streets as card_streets
        import games.drama as drama

        await drain_drama()
        reset_state()
        card_streets.STREET_PAUSE_SECONDS = getattr(self, "_street_pause", 2.0)
        card_streets.RESULT_BEAT_SECONDS = getattr(self, "_result_beat", 1.0)
        drama.MIN_EDIT_INTERVAL = getattr(self, "_min_edit", 1.2)
        runtime.READY_TICK_INTERVAL = 3.0
        runtime.SCORE_BEAT_SECONDS = 2.0
        runtime.types = self.original_types
        ledger.reset_ledger_state()

    def _open_table(self):
        return {
            "table_id": TABLE_ID,
            "game_type": "pvp_dice",
            "creator_id": 11,
            "stake_rub": "25.00",
            "max_seats": 3,
            "max_players": 3,
            "status": "open",
            "state_version": 2,
            "game_chat_id": -100123,
            "free_seats": [3],
            "game_state": {
                "chat_id": -100123,
                "card_msg_id": 71,
                "draw_policy": "tie_break",
                "play_chats": [{"chat_id": -100123, "card_msg_id": 71, "trash_msg_ids": []}],
                "roster_names": {"1": {"telegram_id": 11, "first_name": "Шеруд"}},
            },
            "roster": [
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Дилер"}},
            ],
        }

    def test_ledger_add_and_collect(self):
        chats = [{"chat_id": -100, "card_msg_id": 1, "roll_msg_id": None, "trash_msg_ids": []}]
        chats = ledger.add_trash(chats, chat_id=-100, message_id=80)
        chats = ledger.add_trash(chats, chat_id=-100, message_id=81)
        chats = ledger.add_trash(chats, chat_id=-100, message_id=80)
        self.assertEqual(chats[0]["trash_msg_ids"], [80, 81])
        table = {
            "table_id": TABLE_ID,
            "game_chat_id": -100,
            "game_state": {
                "card_msg_id": 1,
                "listing_chat_id": -100,
                "listing_msg_id": 1,
                "play_chats": chats,
            },
        }
        ids = ledger.collect_trash(table)
        self.assertEqual(ids, [(-100, 1), (-100, 80), (-100, 81)])

    def test_lobby_card_lists_seats_and_free(self):
        text = runtime._lobby_card_text(self._open_table())
        self.assertIn("Мест 3 · свободно 1", text)
        self.assertIn("25.00", text)
        self.assertIn("Шеруд", text)
        self.assertIn("tg://user?id=11", text)
        self.assertIn("Дилер", text)
        self.assertIn("3. — свободно", text)
        self.assertNotIn("Людей:", text)

    def test_settlement_is_compact(self):
        text = runtime.format_v2_settlement(
            {
                "outcome_kind": "winner",
                "table_id": TABLE_ID,
                "pot_rub": "50.00",
                "commission_rub": "2.50",
                "winner_seat_nos": [1],
                "payouts": [{"seat_no": 1, "amount_rub": "47.50"}],
            },
            table=self._open_table(),
        )
        self.assertIn("Победил:", text)
        self.assertIn("Шеруд", text)
        self.assertIn("47.50", text)
        self.assertIn("банк 50.00", text)
        self.assertNotIn("место 1 ·", text)

    async def test_commit_settle_sends_one_result_and_deletes_trash(self):
        table = self._open_table()
        table["status"] = "running"
        table["game_state"]["play_chats"][0]["trash_msg_ids"] = [80, 81]
        client = TableClient(table)
        with patch.object(runtime, "table_url", return_value="http://site/casino/tables/" + TABLE_ID):
            with patch.object(runtime, "verify_url", return_value=""):
                await runtime._commit_settle(self.bot, client, table, kind="winner", winner_seat_nos=[1])
        self.assertEqual(self.bot.send_message.await_count, 1)
        result = self.bot.send_message.await_args.args[1]
        self.assertIn("Победил:", result)
        self.assertIn("47.50", result)
        labels = [
            button.text
            for row in self.bot.send_message.await_args.kwargs["reply_markup"].keyboard
            for button in row
        ]
        self.assertIn("Проверить игру", labels)
        deleted = {(call.args[0], call.args[1]) for call in self.bot.delete_message.await_args_list}
        self.assertEqual(deleted, {(-100123, 71), (-100123, 80), (-100123, 81)})

    async def test_delete_forbidden_edits_card(self):
        table = self._open_table()
        table["status"] = "running"
        client = TableClient(table)
        self.bot.delete_message.side_effect = RuntimeError("not enough rights")
        with patch.object(runtime, "table_url", return_value="http://site/casino/tables/" + TABLE_ID):
            await runtime.publish_settled_table(
                self.bot, client, table,
                {
                    "outcome_kind": "winner",
                    "table_id": TABLE_ID,
                    "pot_rub": "50.00",
                    "commission_rub": "2.50",
                    "payouts": [{"seat_no": 1, "amount_rub": "47.50"}],
                },
            )
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.bot.edit_message_text.assert_awaited()
        self.assertIn("Победил:", self.bot.edit_message_text.await_args.args[0])
        self.assertEqual(self.bot.edit_message_text.await_args.args[1], -100123)
        self.assertEqual(self.bot.edit_message_text.await_args.args[2], 71)

    async def test_outbox_finalizes_remembered_table_once(self):
        table = self._open_table()
        table["status"] = "finished"
        ledger.remember_table(table)
        client = SimpleNamespace(
            v2_recovery_or_outbox=AsyncMock(return_value={
                "items": [
                    {
                        "outbox_id": 1,
                        "claim_token": "tok",
                        "recipient_id": 11,
                        "payload": {
                            "table_id": TABLE_ID,
                            "outcome_kind": "winner",
                            "pot_rub": "50.00",
                            "commission_rub": "2.50",
                            "payouts": [{"seat_no": 1, "amount_rub": "47.50"}],
                        },
                    },
                    {
                        "outbox_id": 2,
                        "claim_token": "tok2",
                        "recipient_id": 22,
                        "payload": {
                            "table_id": TABLE_ID,
                            "outcome_kind": "winner",
                            "pot_rub": "50.00",
                            "commission_rub": "2.50",
                            "payouts": [{"seat_no": 1, "amount_rub": "47.50"}],
                        },
                    },
                ],
            }),
        )
        with patch.object(runtime, "table_url", return_value="http://site/casino/tables/" + TABLE_ID):
            await runtime.run_v2_outbox_pass(self.bot, client, worker_id="w1")
        group_sends = [call for call in self.bot.send_message.await_args_list if call.args[0] == -100123]
        self.assertEqual(len(group_sends), 1)
        self.assertEqual(self.bot.delete_message.await_count, 1)
        self.assertEqual(client.v2_recovery_or_outbox.await_count, 3)

    async def test_join_toast_does_not_send_message(self):
        original_types = v2_tables.types
        v2_tables.types = SimpleNamespace(InlineKeyboardMarkup=Keyboard, InlineKeyboardButton=Button)
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            answer_callback_query=AsyncMock(),
            callback_handlers=[],
            callback_query_handler=lambda **kwargs: (lambda handler: bot.callback_handlers.append((kwargs["func"], handler)) or handler),
        )
        client = SimpleNamespace(
            v2_tables_get=AsyncMock(return_value={"tables": [self._open_table()]}),
            v2_table_operation=AsyncMock(return_value={"table": self._open_table()}),
            get_active_pvp_games=AsyncMock(return_value=[]),
        )
        try:
            v2_tables.register_v2_table_handlers(bot, client)
            handler = next(
                handler for predicate, handler in bot.callback_handlers
                if predicate(SimpleNamespace(data=f"v2join:{TABLE_ID}"))
            )
            with patch("games.v2_runtime.after_table_join", AsyncMock()):
                await handler(SimpleNamespace(
                    id="join",
                    data=f"v2join:{TABLE_ID}",
                    from_user=SimpleNamespace(id=22),
                    message=SimpleNamespace(chat=SimpleNamespace(id=-100123)),
                ))
            bot.send_message.assert_not_awaited()
            self.assertIn("Вы заняли место", bot.answer_callback_query.await_args.args[1])
        finally:
            v2_tables.types = original_types

    def test_lobby_card_shows_countdown(self):
        table = self._open_table()
        table["status"] = "ready"
        table["game_state"]["starts_at"] = "2026-09-02T04:25:37+00:00"
        frozen = datetime(2026, 9, 2, 4, 25, 30, tzinfo=timezone.utc)
        with patch.object(runtime, "_utc_now", return_value=frozen):
            text = runtime._lobby_card_text(table)
        self.assertIn("Старт через 7 с", text)
        self.assertNotIn(runtime.DELAY_NOTICE, text)

    def test_lobby_card_shows_delay_notice(self):
        table = self._open_table()
        table["status"] = "ready"
        table["game_state"]["starts_at"] = "2026-09-02T04:25:37+00:00"
        frozen = datetime(2026, 9, 2, 4, 26, 10, tzinfo=timezone.utc)
        with patch.object(runtime, "_utc_now", return_value=frozen):
            text = runtime._lobby_card_text(table)
        self.assertIn(runtime.DELAY_NOTICE, text)

    async def test_after_join_ready_edits_countdown_and_does_not_start(self):
        table = self._open_table()
        table["status"] = "ready"
        table["game_state"]["starts_at"] = "2026-09-02T04:25:37+00:00"
        client = TableClient(table)
        started = AsyncMock()
        frozen = datetime(2026, 9, 2, 4, 25, 30, tzinfo=timezone.utc)
        with patch.object(runtime, "start_table_round", started), patch.object(
            runtime, "_utc_now", return_value=frozen
        ):
            await runtime.after_table_join(
                self.bot, client, {"table": table, "auto_started": True}
            )
        started.assert_not_awaited()
        edited = self.bot.edit_message_text.await_args.args[0]
        self.assertIn("Старт через 7 с", edited)
        watch = runtime._READY_WATCH.get(TABLE_ID)
        self.assertIsNotNone(watch)
        self.assertFalse(watch["task"].done())

    async def test_ready_watch_does_not_spawn_second_task(self):
        table = self._open_table()
        table["status"] = "ready"
        client = TableClient(table)
        runtime._ensure_ready_watch(self.bot, client, table)
        first = runtime._READY_WATCH[TABLE_ID]["task"]
        runtime._ensure_ready_watch(self.bot, client, table)
        self.assertIs(runtime._READY_WATCH[TABLE_ID]["task"], first)

    async def test_ready_watch_starts_round_when_promoted(self):
        table = self._open_table()
        table["status"] = "ready"
        client = TableClient(table)
        runtime.READY_TICK_INTERVAL = 0.01
        started = AsyncMock()
        with patch.object(runtime, "start_table_round", started):
            runtime._ensure_ready_watch(self.bot, client, table)
            await asyncio.sleep(0.03)
            table["status"] = "running"
            await asyncio.sleep(0.05)
        started.assert_awaited()
        self.assertNotIn(TABLE_ID, runtime._READY_WATCH)

    async def test_ready_watch_logs_delay_and_edits_notice(self):
        table = self._open_table()
        table["status"] = "ready"
        table["game_state"]["starts_at"] = "2026-09-02T04:25:37+00:00"
        client = TableClient(table)
        runtime.READY_TICK_INTERVAL = 0.01
        frozen = datetime(2026, 9, 2, 4, 26, 10, tzinfo=timezone.utc)
        with patch.object(runtime, "_utc_now", return_value=frozen), self.assertLogs(
            runtime.logger, level="WARNING"
        ) as captured:
            runtime._ensure_ready_watch(self.bot, client, table)
            await asyncio.sleep(0.05)
        await runtime.drain_ready_watchers()
        self.assertTrue(any("start delayed" in line.lower() for line in captured.output))
        edited = self.bot.edit_message_text.await_args.args[0]
        self.assertIn(runtime.DELAY_NOTICE, edited)

    async def test_refresh_marks_missing_active_table_gone(self):
        table = self._open_table()
        table["status"] = "running"
        client = SimpleNamespace(v2_tables_get=AsyncMock(return_value={"tables": []}))
        fresh = await runtime._refresh(client, table)
        self.assertEqual(fresh["status"], runtime.GONE_STATUS)
        self.assertEqual(fresh["table_id"], TABLE_ID)

    async def test_roll_watch_edit_fail_does_not_send(self):
        table = self._open_table()
        table["status"] = "running"
        table["game_state"]["phase"] = "rolling"
        table["game_state"]["rolls"] = {}
        table["game_state"]["seat_nos"] = [1, 2]
        client = TableClient(table)
        runtime.READY_TICK_INTERVAL = 0.01
        self.bot.edit_message_text.side_effect = RuntimeError("message to edit not found")
        runtime._ensure_roll_watch(self.bot, client, table)
        await asyncio.sleep(0.05)
        await runtime.drain_ready_watchers()
        self.assertEqual(self.bot.send_message.await_count, 0)
        self.assertNotIn(TABLE_ID, runtime._ROLL_WATCH)

    async def test_roll_watch_stops_when_table_leaves_active(self):
        table = self._open_table()
        table["status"] = "running"
        table["game_state"]["phase"] = "rolling"
        table["game_state"]["rolls"] = {}
        table["game_state"]["seat_nos"] = [1, 2]
        client = TableClient(table)

        async def empty_active(_path):
            return {"tables": []}

        client.v2_tables_get = empty_active
        runtime.READY_TICK_INTERVAL = 0.01
        runtime._ensure_roll_watch(self.bot, client, table)
        await asyncio.sleep(0.05)
        await runtime.drain_ready_watchers()
        self.assertEqual(self.bot.send_message.await_count, 0)
        self.assertNotIn(TABLE_ID, runtime._ROLL_WATCH)

    async def test_outbox_settled_stops_roll_watch_without_resend(self):
        table = self._open_table()
        table["status"] = "running"
        table["game_state"]["phase"] = "rolling"
        table["game_state"]["rolls"] = {}
        table["game_state"]["seat_nos"] = [1, 2]
        ledger.remember_table(table)
        client = TableClient(table)
        runtime.READY_TICK_INTERVAL = 0.01
        self.bot.edit_message_text.side_effect = RuntimeError("message to edit not found")
        runtime._ensure_roll_watch(self.bot, client, table)
        await asyncio.sleep(0.03)
        outbox = SimpleNamespace(
            v2_recovery_or_outbox=AsyncMock(return_value={
                "items": [
                    {
                        "outbox_id": 1,
                        "claim_token": "tok",
                        "recipient_id": 11,
                        "payload": {
                            "table_id": TABLE_ID,
                            "outcome_kind": "winner",
                            "pot_rub": "40.00",
                            "commission_rub": "2.00",
                            "payouts": [{"seat_no": 1, "amount_rub": "38.00"}],
                        },
                    }
                ],
            }),
        )
        with patch.object(runtime, "table_url", return_value="http://site/casino/tables/" + TABLE_ID):
            await runtime.run_v2_outbox_pass(self.bot, outbox, worker_id="w1")
        await asyncio.sleep(0.05)
        await runtime.drain_ready_watchers()
        group_sends = [call for call in self.bot.send_message.await_args_list if call.args[0] == -100123]
        self.assertEqual(len(group_sends), 1)
        self.assertIn("Победил:", group_sends[0].args[1])
        self.assertNotIn("Киньте", group_sends[0].args[1])
        self.assertNotIn(TABLE_ID, runtime._ROLL_WATCH)


if __name__ == "__main__":
    unittest.main()
