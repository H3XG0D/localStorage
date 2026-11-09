import asyncio
import importlib
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules


with TelebotModules("games.v2_runtime", "games.v2_tables", "games.v2_chat_ledger"):
    runtime = importlib.import_module("games.v2_runtime")
    ledger = importlib.import_module("games.v2_chat_ledger")


TABLE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
COMMIT = "ab" * 32


class Keyboard:
    def __init__(self, *args, **kwargs):
        self.keyboard = []

    def add(self, *buttons):
        self.keyboard.append(list(buttons))


class Button:
    def __init__(self, text, callback_data=None, **kwargs):
        self.text = text
        self.callback_data = callback_data


class TableClient:
    def __init__(self, table, decks):
        self.table = table
        self.decks = decks
        self.deals = []

    def _snapshot(self):
        return deepcopy(self.table)

    async def v2_tables_get(self, path):
        return {"tables": [self._snapshot()]}

    async def v2_table_operation(self, table_id, operation, **kwargs):
        if operation == "persist-state":
            state = dict(self.table.get("game_state") or {})
            state.update(kwargs["game_state"])
            self.table["game_state"] = state
            self.table["state_version"] = int(self.table.get("state_version") or 0) + 1
            return {"table": self._snapshot()}
        if operation == "commit-outcome":
            kind = kwargs.get("outcome_kind")
            self.table["status"] = "tie_break_running" if kind == "tie_break" else "outcome_committed"
            self.table["state_version"] = int(self.table.get("state_version") or 0) + 1
            return {"table": self._snapshot()}
        if operation == "settle-committed-outcome":
            self.table["status"] = "settled"
            self.table["state_version"] = int(self.table.get("state_version") or 0) + 1
            return {
                "outcome_kind": "winner",
                "table_id": table_id,
                "pot_rub": "100.00",
                "commission_rub": "5.00",
                "payouts": [{"seat_no": 1, "amount_rub": "95.00"}],
                "table": self._snapshot(),
            }
        raise AssertionError(operation)

    async def v2_table_cards(self, table_id, operation, **payload):
        if operation == "prepare":
            return {"rng_commit": COMMIT, "client_seed": "focuspay", "nonce": 1}
        if operation == "deal":
            self.deals.append(dict(payload))
            side = str(payload.get("shoe_side") or "")
            cards = list(self.decks.get(side, ["A♠", "9♥"]))
            size = int(payload.get("hand_size") or len(cards))
            return {"cards": cards[:size]}
        if operation == "reveal":
            return {"rng_seed": "cd" * 32}
        raise AssertionError(operation)

    async def get_active_game_chat_binding(self):
        return None


class V2CardBoardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_types = runtime.types
        runtime.types = SimpleNamespace(InlineKeyboardMarkup=Keyboard, InlineKeyboardButton=Button)
        runtime._table_roll_locks.clear()
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
        self.wait = AsyncMock()
        self.wait_patcher = patch.object(runtime, "wait_dice_landed", self.wait)
        self.wait_patcher.start()
        self.bot = SimpleNamespace(
            edit_message_text=AsyncMock(),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=99)),
            delete_message=AsyncMock(),
            send_dice=AsyncMock(return_value=SimpleNamespace(
                message_id=80, dice=SimpleNamespace(emoji="🎲", value=4),
            )),
            answer_callback_query=AsyncMock(),
            reply_to=AsyncMock(),
            get_chat=AsyncMock(side_effect=lambda telegram_id: SimpleNamespace(
                first_name={11: "Алекс", 22: "Борис"}.get(telegram_id, "Игрок"),
                username=None,
            )),
        )

    def tearDown(self):
        self.wait_patcher.stop()
        runtime.types = self.original_types
        import games.card_streets as card_streets
        import games.drama as drama

        card_streets.STREET_PAUSE_SECONDS = self._street_pause
        card_streets.RESULT_BEAT_SECONDS = self._result_beat
        drama.MIN_EDIT_INTERVAL = self._min_edit
        runtime.SCORE_BEAT_SECONDS = 2.0

    async def asyncTearDown(self):
        await runtime.drain_ready_watchers()
        from games.drama import drain_drama, reset_state

        await drain_drama()
        reset_state()
        runtime.SCORE_BEAT_SECONDS = 2.0

    def _table(self, *, game_type, roster, extra_state=None):
        state = {
            "chat_id": -100123,
            "card_msg_id": 71,
            "draw_policy": "tie_break",
            "rng_commit": COMMIT,
            "client_seed": "focuspay",
            "nonce": 1,
        }
        if extra_state:
            state.update(extra_state)
        return {
            "table_id": TABLE_ID,
            "game_type": game_type,
            "creator_id": 11,
            "stake_rub": "50.00",
            "max_seats": len(roster),
            "status": "running",
            "state_version": 4,
            "game_chat_id": -100123,
            "game_state": state,
            "roster": roster,
        }

    def test_card_text_shows_scores_names_rules_not_commit_dump(self):
        table = self._table(
            game_type="baccara",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Робот"}},
            ],
            extra_state={"phase": "settled", "hands": {"1": ["7♠", "K♣"], "2": ["9♥", "9♦"]}},
        )
        with patch.object(runtime, "verify_url", return_value=""):
            text = runtime._card_text(table)
        self.assertIn("Ближе к 9", text)
        self.assertIn("7♠ K♣", text)
        self.assertIn("9♥ 9♦", text)
        self.assertIn("<b>7</b>", text)
        self.assertIn("<b>8</b>", text)
        self.assertIn("Робот", text)
        self.assertNotIn(COMMIT, text)
        self.assertNotIn("Колода зафиксирована: <code>", text)

    async def test_blackjack_reminder_is_claimed_once_and_shows_deadline(self):
        deadline = (datetime.now(timezone.utc) + timedelta(seconds=12)).isoformat()
        table = self._table(
            game_type="blackjack",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "player", "telegram_id": 22},
            ],
            extra_state={
                "phase": "hitting",
                "hands": {"1": ["9♠", "8♣"], "2": ["10♥", "7♦"]},
                "decisions": {"2": "stand"},
                "stood_seats": [2],
                "seat_nos": [1, 2],
                "roll_deadline_at": deadline,
            },
        )
        client = TableClient(table, {})

        claimed = await runtime._maybe_send_blackjack_reminder(self.bot, client, table)
        await runtime._maybe_send_blackjack_reminder(self.bot, client, claimed)

        self.assertEqual(self.bot.send_message.await_count, 1)
        self.assertEqual(self.bot.send_message.await_args.args[0], 11)
        self.assertIn("автоматически «Оставить»", self.bot.send_message.await_args.args[1])
        self.assertEqual(
            claimed["game_state"]["blackjack_reminder_deadline_at"],
            deadline,
        )
        self.assertIn("До авто-«Оставить»", runtime._card_text(claimed, viewer_id=11))

    async def test_blackjack_reminder_falls_back_to_group_when_dm_blocked(self):
        deadline = (datetime.now(timezone.utc) + timedelta(seconds=12)).isoformat()
        table = self._table(
            game_type="blackjack",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
            ],
            extra_state={
                "phase": "hitting",
                "hands": {"1": ["9♠", "8♣"]},
                "seat_nos": [1],
                "roll_deadline_at": deadline,
            },
        )
        table = {**table, "game_chat_id": -100123}
        client = TableClient(table, {})
        blocked = RuntimeError("Forbidden: bot was blocked by the user")
        blocked.error_code = 403
        blocked.description = "Forbidden: bot was blocked by the user"
        self.bot.send_message = AsyncMock(side_effect=[blocked, None])

        claimed = await runtime._maybe_send_blackjack_reminder(self.bot, client, table)
        await runtime._maybe_send_blackjack_reminder(self.bot, client, claimed)

        self.assertEqual(self.bot.send_message.await_count, 2)
        self.assertEqual(self.bot.send_message.await_args_list[0].args[0], 11)
        self.assertEqual(self.bot.send_message.await_args_list[1].args[0], -100123)
        self.assertIn("/start", self.bot.send_message.await_args_list[1].args[1])
        self.assertEqual(claimed["dm_unavailable_fallback_sent_at"], deadline)

    def test_settlement_names_the_winner(self):
        table = self._table(
            game_type="baccara",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11, "display_name": "Алекс"},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Робот"}},
            ],
        )
        text = runtime.format_v2_settlement(
            {
                "outcome_kind": "winner",
                "table_id": TABLE_ID,
                "pot_rub": "80.00",
                "commission_rub": "4.00",
                "payouts": [{"seat_no": 2, "amount_rub": "76.00"}],
            },
            table=table,
        )
        self.assertIn("Победил:", text)
        self.assertIn("Робот", text)
        self.assertIn("76.00", text)
        self.assertIn("80.00", text)
        self.assertNotIn("Исход:", text)
        self.assertNotIn("Алекс: 0 ₽", text)

    def test_group_hides_blackjack_but_reveals_baccarat(self):
        roster = [
            {'seat_no': 1, 'participant_kind': 'player', 'telegram_id': 11},
            {'seat_no': 2, 'participant_kind': 'bot', 'bot': {'display_name': 'Робот'}},
        ]
        state = {'phase': 'hitting', 'hands': {'1': ['7♠', 'K♣'], '2': ['9♥', '9♦']}}
        blackjack = runtime._card_text(self._table(
            game_type='blackjack', roster=roster, extra_state=state,
        ))
        baccarat = runtime._card_text(self._table(
            game_type='baccara', roster=roster, extra_state=state,
        ))
        self.assertNotIn('7♠', blackjack)
        self.assertNotIn('9♥', blackjack)
        self.assertIn('7♠ K♣', baccarat)
        self.assertIn('9♥ 9♦', baccarat)

    def test_seat_name_uses_roster_from_user(self):
        table = self._table(
            game_type="baccara",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Робот"}},
            ],
            extra_state={"roster_names": {"1": {"telegram_id": 11, "first_name": "Катя", "username": "katya"}}},
        )
        with patch.object(runtime, "verify_url", return_value=""):
            text = runtime._card_text(table)
        self.assertIn("@katya", text)
        self.assertNotIn("Катя", text)
        self.assertIn("Робот", text)

    def test_lobby_card_shows_telegram_username_not_glyph_name(self):
        table = self._table(
            game_type="pvp_dice",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "player", "telegram_id": 22},
            ],
            extra_state={
                "roster_names": {
                    "1": {
                        "telegram_id": 11,
                        "first_name": "GlyphName",
                        "username": "pochemutigovorishsomnoyfromhell",
                    },
                    "2": {"telegram_id": 22, "first_name": "Focus", "username": "focuspayadmin"},
                },
            },
        )
        table["status"] = "open"
        table["max_seats"] = 4
        text = runtime._lobby_card_text(table)
        self.assertIn("@pochemutigovorishsomnoyfromhell", text)
        self.assertIn("@focuspayadmin", text)
        self.assertIn("tg://user?id=11", text)
        self.assertIn("tg://user?id=22", text)
        self.assertNotIn("GlyphName", text)
        self.assertNotIn(">Focus<", text)

    def test_roll_text_uses_names_not_telegram_id(self):
        table = self._table(
            game_type="pvp_dice",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11, "display_name": "Алекс"},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Робот"}},
            ],
            extra_state={"phase": "rolling", "rolls": {}, "rounds": 1, "seat_nos": [1, 2]},
        )
        text = runtime._roll_text(table)
        self.assertIn("Алекс", text)
        self.assertIn("Робот", text)
        self.assertNotIn("id 11", text)

    async def test_publish_full_private_table_does_not_touch_bound_group(self):
        table = self._table(
            game_type="baccara",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Робот"}},
            ],
        )
        table["game_chat_id"] = 11
        table["game_state"]["chat_id"] = 11
        table["game_state"].pop("card_msg_id", None)
        client = TableClient(table, {})
        client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -100123})
        with patch.object(runtime, "start_table_round", AsyncMock()):
            await runtime.publish_created_table(
                self.bot, client, table,
                result={"auto_started": True},
                actor=SimpleNamespace(id=11, first_name="Алекс", username="alex"),
            )
        chats = [call.args[0] for call in self.bot.send_message.await_args_list]
        self.assertEqual(chats, [11])
        self.assertEqual(client.table["game_state"]["roster_names"]["1"]["first_name"], "Алекс")
        self.assertEqual(client.table["game_state"]["play_chats"][0]["chat_id"], 11)

    async def test_publish_open_private_table_lists_in_bound_group(self):
        table = self._table(
            game_type="baccara",
            roster=[{"seat_no": 1, "participant_kind": "player", "telegram_id": 11}],
        )
        table["status"] = "open"
        table["max_seats"] = 3
        table["game_chat_id"] = 11
        table["game_state"]["chat_id"] = 11
        table["game_state"].pop("card_msg_id", None)
        client = TableClient(table, {})
        client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -100123})
        await runtime.publish_created_table(
            self.bot, client, table,
            actor=SimpleNamespace(id=11, first_name="Алекс"),
        )
        chats = [call.args[0] for call in self.bot.send_message.await_args_list]
        self.assertEqual(chats, [11, -100123])
        listing = self.bot.send_message.await_args_list[1]
        self.assertIn("Войти", listing.args[1])
        labels = [button.text for row in listing.kwargs["reply_markup"].keyboard for button in row]
        self.assertEqual(labels, ["Войти", "❌ Отменить стол"])
        self.assertEqual(client.table["game_state"]["listing_chat_id"], -100123)

    def test_open_lobby_keyboard_lets_creator_cancel(self):
        table = self._table(
            game_type="blackjack",
            roster=[{"seat_no": 1, "participant_kind": "player", "telegram_id": 11}],
        )
        table["status"] = "open"
        table["max_seats"] = 2
        labels = [
            button.text
            for row in runtime._join_keyboard(table).keyboard
            for button in row
        ]
        self.assertIn("✅ Занять место", labels)
        self.assertIn("❌ Отменить стол", labels)
        callbacks = [
            button.callback_data
            for row in runtime._join_keyboard(table).keyboard
            for button in row
        ]
        self.assertIn(f"v2cancel:{TABLE_ID}", callbacks)

    def test_blackjack_listing_keeps_table_and_creator(self):
        table = self._table(
            game_type="blackjack",
            roster=[{"seat_no": 1, "participant_kind": "player", "telegram_id": 11}],
            extra_state={"roster_names": {"1": {"telegram_id": 11, "first_name": "Алекс", "username": "alex"}}},
        )
        table["status"] = "open"
        table["max_seats"] = 4
        text = runtime._listing_text(table)
        self.assertIn(f"Стол #{TABLE_ID[:8].upper()}", text)
        self.assertIn("50.00", text)
        self.assertIn("@alex", text)
        self.assertIn("Войти", text)
        self.assertIn("личке", text)

    async def test_publish_group_table_names_creator_on_first_card(self):
        table = self._table(
            game_type="blackjack",
            roster=[{"seat_no": 1, "participant_kind": "player", "telegram_id": 11}],
        )
        table["status"] = "open"
        table["max_seats"] = 4
        table["game_state"].pop("roster_names", None)
        table["game_state"].pop("card_msg_id", None)
        client = TableClient(table, {})
        await runtime.publish_created_table(
            self.bot, client, table,
            actor=SimpleNamespace(id=11, first_name="Алекс", username="alex"),
        )
        first = self.bot.send_message.await_args_list[0].args[1]
        self.assertIn("@alex", first)
        self.assertIn("tg://user?id=11", first)
        self.assertNotIn("1. — свободно", first)
        self.assertEqual(client.table["game_state"]["roster_names"]["1"]["username"], "alex")

    async def test_publish_open_blackjack_lists_creator_in_bound_group(self):
        table = self._table(
            game_type="blackjack",
            roster=[{"seat_no": 1, "participant_kind": "player", "telegram_id": 11}],
        )
        table["status"] = "open"
        table["max_seats"] = 4
        table["game_chat_id"] = 11
        table["game_state"]["chat_id"] = 11
        table["game_state"].pop("card_msg_id", None)
        client = TableClient(table, {})
        client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -100123})
        await runtime.publish_created_table(
            self.bot, client, table,
            actor=SimpleNamespace(id=11, first_name="Алекс", username="alex"),
        )
        chats = [call.args[0] for call in self.bot.send_message.await_args_list]
        self.assertEqual(chats, [11, -100123])
        listing = self.bot.send_message.await_args_list[1].args[1]
        self.assertIn("@alex", listing)
        self.assertIn(f"Стол #{TABLE_ID[:8].upper()}", listing)
        self.assertIn("Войти", listing)

    async def test_edit_board_fans_out_to_play_chats(self):
        table = self._table(
            game_type="baccara",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Робот"}},
            ],
            extra_state={
                "play_chats": [
                    {"chat_id": 11, "card_msg_id": 71},
                    {"chat_id": -100123, "card_msg_id": 80},
                ],
            },
        )
        client = TableClient(table, {})
        await runtime._edit_board(self.bot, client, table, text="board")
        edit_chats = [call.args[1] for call in self.bot.edit_message_text.await_args_list]
        self.assertEqual(sorted(edit_chats), [-100123, 11])
        self.assertEqual(self.bot.send_message.await_count, 0)

    async def test_join_from_group_converts_listing_to_play_chat(self):
        table = self._table(
            game_type="baccara",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11, "display_name": "Алекс"},
                {"seat_no": 2, "participant_kind": "player", "telegram_id": 22},
            ],
            extra_state={
                "chat_id": 11,
                "card_msg_id": 71,
                "play_chats": [{"chat_id": 11, "card_msg_id": 71}],
                "listing_chat_id": -100123,
                "listing_msg_id": 5,
            },
        )
        table["status"] = "open"
        table["game_chat_id"] = 11
        table["max_seats"] = 3
        table["free_seats"] = [3]
        client = TableClient(table, {})
        await runtime.after_table_join(
            self.bot, client, {"table": table},
            join_chat_id=-100123,
            user=SimpleNamespace(id=22, first_name="Борис", username="boris"),
        )
        self.assertEqual(client.table["game_state"]["roster_names"]["2"]["first_name"], "Борис")
        play_ids = [row["chat_id"] for row in client.table["game_state"]["play_chats"]]
        self.assertIn(11, play_ids)
        self.assertIn(-100123, play_ids)
        group = next(row for row in client.table["game_state"]["play_chats"] if row["chat_id"] == -100123)
        self.assertEqual(group["card_msg_id"], 5)
        self.assertIn(-100123, [call.args[1] for call in self.bot.edit_message_text.await_args_list])
        self.assertEqual(self.bot.send_message.await_count, 0)

    async def test_baccarat_edits_one_board_and_passes_shoe_side(self):
        table = self._table(
            game_type="baccara",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Робот"}},
            ],
        )
        client = TableClient(table, {
            "seat1": ["7♠", "K♣"],
            "seat2": ["9♥", "9♦"],
        })

        await runtime._deal_initial_cards(self.bot, client, table)

        self.assertGreaterEqual(self.bot.edit_message_text.await_count, 1)
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.assertGreaterEqual(self.bot.delete_message.await_count, 1)
        sides = [row.get("shoe_side") for row in client.deals]
        self.assertEqual(sides, ["seat1", "seat2"])
        edits = [call.args[0] for call in self.bot.edit_message_text.await_args_list]
        result = self.bot.send_message.await_args.args[1]
        self.assertIn("7♠ K♣", result)
        self.assertIn("9♥ 9♦", result)
        self.assertIn("<b>7</b>", result)
        self.assertIn("<b>8</b>", result)
        self.assertIn("Победил:", result)
        self.assertTrue("Алекс" in result or "Робот" in result)
        self.assertFalse(any("Переброс" in text for text in edits))

    async def test_baccarat_tie_break_stays_on_same_card(self):
        table = self._table(
            game_type="baccara",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "player", "telegram_id": 22},
            ],
        )
        client = TableClient(table, {
            "seat1": ["3♠", "3♣"],
            "seat2": ["3♥", "3♦"],
            "seat1_tb1": ["7♠", "K♣"],
            "seat2_tb1": ["9♥", "K♦"],
        })

        await runtime._deal_initial_cards(self.bot, client, table)

        self.assertEqual(self.bot.send_message.await_count, 1)
        self.assertGreaterEqual(self.bot.edit_message_text.await_count, 1)
        self.assertGreaterEqual(self.bot.delete_message.await_count, 1)
        sides = [row.get("shoe_side") for row in client.deals]
        self.assertEqual(sides[:2], ["seat1", "seat2"])
        self.assertIn("seat1_tb1", sides)
        self.assertIn("seat2_tb1", sides)
        texts = [call.args[0] for call in self.bot.edit_message_text.await_args_list]
        self.assertTrue(any("Ничья 6–6. Переброс лидеров." in text for text in texts))
        result = self.bot.send_message.await_args.args[1]
        self.assertIn("<b>7</b>", result)
        self.assertIn("<b>9</b>", result)

    async def test_blackjack_hit_buttons_only_in_private_board(self):
        table = self._table(
            game_type="blackjack",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Робот"}},
            ],
        )
        client = TableClient(table, {
            "seat1": ["5♥", "6♦", "10♠"],
            "seat2": ["10♠", "9♣"],
        })

        await runtime._deal_initial_cards(self.bot, client, table)

        # Group card is edited; personal DM board is also sent to the human.
        self.assertGreaterEqual(self.bot.send_message.await_count, 1)
        self.assertEqual(self.bot.send_message.await_args_list[0].args[0], 11)
        sides = [row.get("shoe_side") for row in client.deals]
        self.assertEqual(sides, ["seat1", "seat2"])
        group_edits = [
            call for call in self.bot.edit_message_text.await_args_list
            if call.args and call.args[0] and "добор — в личке" in call.args[0]
        ]
        self.assertTrue(group_edits)
        last = group_edits[-1]
        self.assertIn("Ближе к 21", last.args[0])
        self.assertIn("🂠 🂠", last.args[0])  # чужие/свои на группе закрыты
        markup = last.kwargs["reply_markup"]
        labels = [button.text for row in markup.keyboard for button in row]
        self.assertEqual(labels, ["Открыть личку и карты"])
        dm = self.bot.send_message.await_args_list[0]
        self.assertIn("<b>11</b>", dm.args[1])
        self.assertIn("5♥ 6♦", dm.args[1])

        call = SimpleNamespace(id="hit", data=f"v2hit:{TABLE_ID}", from_user=SimpleNamespace(id=11))
        await runtime.handle_card_action(self.bot, client, call, hit=True)

        self.assertEqual(client.deals[-1]["shoe_side"], "seat1")
        self.assertEqual(client.deals[-1]["hand_size"], 3)
        self.assertTrue(any("5♥ 6♦ 10♠" in c.args[0] for c in self.bot.edit_message_text.await_args_list if c.args))
        self.assertTrue(any("<b>21</b>" in c.args[0] for c in self.bot.edit_message_text.await_args_list if c.args))
        self.assertTrue(any(
            len(c.args) > 1 and "Победил:" in str(c.args[1])
            for c in self.bot.send_message.await_args_list
        ))

    async def test_stale_blackjack_button_reports_finished_without_mutation(self):
        client = SimpleNamespace(
            v2_tables_get=AsyncMock(return_value={"tables": []}),
            v2_table_cards=AsyncMock(),
            v2_table_operation=AsyncMock(),
        )
        call = SimpleNamespace(
            id="stale-hit",
            data=f"v2hit:{TABLE_ID}",
            from_user=SimpleNamespace(id=11),
            message=SimpleNamespace(chat=SimpleNamespace(id=11)),
        )

        await runtime.handle_card_action(self.bot, client, call, hit=True)

        self.bot.answer_callback_query.assert_awaited_once_with(
            "stale-hit",
            "Игра уже завершена или отменена. Эта кнопка устарела.",
            show_alert=True,
        )
        client.v2_table_cards.assert_not_awaited()
        client.v2_table_operation.assert_not_awaited()

    async def test_blackjack_refresh_failure_has_specific_callback_feedback(self):
        client = SimpleNamespace(
            v2_tables_get=AsyncMock(side_effect=TimeoutError("backend unavailable")),
        )
        call = SimpleNamespace(
            id="refresh-failed",
            data=f"v2stand:{TABLE_ID}",
            from_user=SimpleNamespace(id=11),
            message=SimpleNamespace(chat=SimpleNamespace(id=11)),
        )

        await runtime.handle_card_action(self.bot, client, call, hit=False)

        self.bot.answer_callback_query.assert_awaited_once_with(
            "refresh-failed",
            "Не удалось обновить стол. Повторите через несколько секунд.",
            show_alert=True,
        )

    async def test_blackjack_dm_deep_link_opens_private_board(self):
        table = self._table(
            game_type="blackjack",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "player", "telegram_id": 22},
            ],
            extra_state={
                "phase": "hitting",
                "hands": {"1": ["9♠", "8♣"], "2": ["10♥", "7♦"]},
                "stood_seats": [],
                "decisions": {},
                "seat_nos": [1, 2],
            },
        )
        client = TableClient(table, {})
        self.assertEqual(
            runtime.extract_blackjack_start_table_id(f"/start bj_{TABLE_ID}"),
            TABLE_ID,
        )
        ok = await runtime.open_blackjack_dm_table(
            self.bot, client, chat_id=11, user_id=11, table_id=TABLE_ID,
        )
        self.assertTrue(ok)
        self.assertTrue(any(c.args[0] == 11 for c in self.bot.send_message.await_args_list))
        dm = next(c for c in self.bot.send_message.await_args_list if c.args[0] == 11)
        self.assertIn("9♠ 8♣", dm.args[1])
        self.assertIn("Ваши карты видите только вы", dm.args[1])
        labels = [button.text for row in dm.kwargs["reply_markup"].keyboard for button in row]
        self.assertEqual(labels, ["🃏 Взять карту", "🛑 Оставить"])

    async def test_blackjack_dm_deep_link_reports_backend_outage(self):
        client = AsyncMock()
        client.v2_tables_get.side_effect = TimeoutError("backend unavailable")

        ok = await runtime.open_blackjack_dm_table(
            self.bot, client, chat_id=11, user_id=11, table_id=TABLE_ID,
        )

        self.assertFalse(ok)
        self.bot.send_message.assert_awaited_once_with(
            11,
            "Не удалось обновить стол. Повторите через несколько секунд.",
        )

    async def test_private_dice_round_prompts_and_bot_waits_for_player(self):
        table = self._table(
            game_type="pvp_dice",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11, "display_name": "Алекс"},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Робот"}},
            ],
            extra_state={"bot_count": 1, "rounds": 1, "draw_policy": "tie_break", "chat_id": 11},
        )
        table["game_chat_id"] = 11
        table["status"] = "running"
        table["game_state"].pop("card_msg_id", None)
        client = TableClient(table, {})
        await runtime.start_table_round(self.bot, client, table)
        prompts = [call.args[1] for call in self.bot.send_message.await_args_list]
        self.assertTrue(any("реплай не нужен" in str(text) for text in prompts))
        self.assertEqual(self.bot.send_message.await_args.args[0], 11)
        self.assertEqual(client.table["game_state"]["play_chats"][0]["card_msg_id"], 99)
        self.bot.send_dice.assert_not_awaited()
        self.assertEqual(client.table["game_state"].get("rolls") or {}, {})

    async def test_private_dice_without_reply_is_recorded_then_bot_throws(self):
        table = self._table(
            game_type="pvp_dice",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11, "display_name": "Алекс"},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Робот"}},
            ],
            extra_state={
                "phase": "rolling",
                "rolls": {},
                "rounds": 1,
                "seat_nos": [1, 2],
                "chat_id": 11,
                "play_chats": [{"chat_id": 11, "card_msg_id": 71, "roll_msg_id": 50}],
            },
        )
        table["game_chat_id"] = 11
        table["status"] = "running"
        client = TableClient(table, {})
        order: list[str] = []

        async def wait():
            order.append("wait")

        async def send_dice(**kwargs):
            order.append("send_dice")
            return SimpleNamespace(message_id=80, dice=SimpleNamespace(emoji="🎲", value=4))

        self.wait.side_effect = wait
        self.bot.send_dice.side_effect = send_dice
        message = SimpleNamespace(
            chat=SimpleNamespace(id=11, type="private"),
            from_user=SimpleNamespace(id=11, is_bot=False),
            reply_to_message=None,
            dice=SimpleNamespace(emoji="🎲", value=5),
        )
        handled = await runtime.try_handle_v2_dice(self.bot, client, message)
        self.assertTrue(handled)
        self.assertEqual(client.table["game_state"]["rolls"].get("s1r0"), 5)
        self.assertEqual(client.table["game_state"]["rolls"].get("s2r0"), 4)
        self.assertEqual(order, ["wait", "send_dice", "wait"])
        self.bot.send_dice.assert_awaited()
        self.assertEqual(self.bot.send_dice.await_args.kwargs["chat_id"], 11)
        self.assertEqual(self.bot.send_dice.await_args.kwargs["emoji"], "🎲")
        self.assertEqual(self.bot.send_dice.await_args.kwargs.get("reply_to_message_id"), 71)
        self.bot.reply_to.assert_not_awaited()

    async def test_group_dice_without_reply_records_by_user_id(self):
        table = self._table(
            game_type="pvp_dice",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11, "display_name": "Алекс"},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Робот"}},
            ],
            extra_state={
                "phase": "rolling",
                "rolls": {},
                "rounds": 1,
                "seat_nos": [1, 2],
                "chat_id": -100123,
                "play_chats": [{"chat_id": -100123, "card_msg_id": 71, "roll_msg_id": 50}],
            },
        )
        table["status"] = "running"
        client = TableClient(table, {})
        self.bot.send_dice.return_value = SimpleNamespace(
            message_id=80, dice=SimpleNamespace(emoji="🎲", value=4),
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100123, type="supergroup"),
            from_user=SimpleNamespace(id=11, is_bot=False),
            reply_to_message=None,
            dice=SimpleNamespace(emoji="🎲", value=5),
        )
        handled = await runtime.try_handle_v2_dice(self.bot, client, message)
        self.assertTrue(handled)
        self.assertEqual(client.table["game_state"]["rolls"].get("s1r0"), 5)
        self.assertEqual(self.bot.send_dice.await_args.kwargs["emoji"], "🎲")
        self.bot.reply_to.assert_not_awaited()

    def _two_roll_dice_table(self):
        table = self._table(
            game_type="pvp_dice",
            roster=[
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11, "display_name": "Алекс"},
                {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Робот"}},
            ],
            extra_state={
                "phase": "rolling",
                "rolls": {},
                "rounds": 2,
                "seat_nos": [1, 2],
                "chat_id": 11,
                "play_chats": [{"chat_id": 11, "card_msg_id": 71, "roll_msg_id": 50}],
            },
        )
        table["game_chat_id"] = 11
        table["status"] = "running"
        return table

    def _private_dice(self, value: int):
        return SimpleNamespace(
            chat=SimpleNamespace(id=11, type="private"),
            from_user=SimpleNamespace(id=11, is_bot=False),
            reply_to_message=None,
            dice=SimpleNamespace(emoji="🎲", value=value),
        )

    async def test_two_roll_game_casino_throws_once_per_player_throw(self):
        client = TableClient(self._two_roll_dice_table(), {})
        self.bot.send_dice.return_value = SimpleNamespace(
            message_id=80, dice=SimpleNamespace(emoji="🎲", value=4),
        )
        await runtime.try_handle_v2_dice(self.bot, client, self._private_dice(5))
        self.assertEqual(self.bot.send_dice.await_count, 1)
        self.assertEqual(client.table["game_state"]["rolls"].get("s1r0"), 5)
        self.assertEqual(client.table["game_state"]["rolls"].get("s2r0"), 4)
        self.assertIsNone(client.table["game_state"]["rolls"].get("s1r1"))
        await runtime.try_handle_v2_dice(self.bot, client, self._private_dice(6))
        self.assertEqual(self.bot.send_dice.await_count, 2)
        self.assertEqual(client.table["game_state"]["rolls"].get("s1r1"), 6)
        self.assertEqual(client.table["game_state"]["rolls"].get("s2r1"), 4)

    async def test_two_roll_overlapping_player_dice_casino_throws_twice(self):
        client = TableClient(self._two_roll_dice_table(), {})
        first_wait = asyncio.Event()
        release = asyncio.Event()

        async def wait():
            if not first_wait.is_set():
                first_wait.set()
                await release.wait()

        self.wait.side_effect = wait
        self.bot.send_dice.return_value = SimpleNamespace(
            message_id=80, dice=SimpleNamespace(emoji="🎲", value=4),
        )
        first = asyncio.create_task(
            runtime.try_handle_v2_dice(self.bot, client, self._private_dice(5))
        )
        for _ in range(50):
            await asyncio.sleep(0)
            if first_wait.is_set():
                break
        self.assertTrue(first_wait.is_set())
        second = asyncio.create_task(
            runtime.try_handle_v2_dice(self.bot, client, self._private_dice(6))
        )
        await asyncio.sleep(0)
        release.set()
        handled = await asyncio.gather(first, second)
        self.assertEqual(handled, [True, True])
        self.assertEqual(self.bot.send_dice.await_count, 2)
        self.assertEqual(client.table["game_state"]["rolls"].get("s1r0"), 5)
        self.assertEqual(client.table["game_state"]["rolls"].get("s1r1"), 6)
        self.assertEqual(client.table["game_state"]["rolls"].get("s2r0"), 4)
        self.assertEqual(client.table["game_state"]["rolls"].get("s2r1"), 4)


if __name__ == "__main__":
    unittest.main()
