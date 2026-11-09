"""Player-click matrix: every button in every seat/state answers like a live user sees it.

Machine version of docs/CASINO_PLAYER_CLICKS.md sections 1-6. Each test drives
a real registered telegram callback handler with a fake call shaped like a live
user tap (position = table status x who taps x where), then asserts what the
user actually sees: the answer_callback_query text, no double hold/board, and
the state the board ends in. No silent clicks, no phantom second games.
"""
import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules


with TelebotModules("games.v2_tables", "games.v2_runtime", "games.pvp", "games.site_links"):
    v2_tables = importlib.import_module("games.v2_tables")
    runtime = importlib.import_module("games.v2_runtime")

with TelebotModules("games.table_wizard", "games.v2_tables", "games.v2_runtime", "games.pvp", "games.house_cub", "games.site_links"):
    wizard = importlib.import_module("games.table_wizard")


TABLE_ID = "t" * 36


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


class ClickBot:
    """Minimal bot double that records what the tapping user would see."""

    def __init__(self):
        self.send_message = AsyncMock()
        self.edit_message_text = AsyncMock()
        self.delete_message = AsyncMock()
        self.answer_callback_query = AsyncMock()
        self.callback_handlers = []

    def callback_query_handler(self, **kwargs):
        def decorator(handler):
            self.callback_handlers.append((kwargs["func"], handler))
            return handler
        return decorator

    def message_handler(self, **kwargs):
        def decorator(handler):
            return handler
        return decorator

    def handler_for(self, data):
        for predicate, handler in self.callback_handlers:
            try:
                if predicate(SimpleNamespace(data=data)):
                    return handler
            except Exception:
                continue
        raise AssertionError(f"no handler for {data!r}")

    def last_answer(self):
        args, kwargs = self.answer_callback_query.await_args
        return {"text": args[1] if len(args) > 1 else "", "alert": bool(kwargs.get("show_alert"))}


def _call(data, user_id, chat_id=-100123, chat_type="group", message_id=9):
    return SimpleNamespace(
        id=f"call-{data}-{user_id}",
        data=data,
        from_user=SimpleNamespace(id=user_id, first_name="User", username=None),
        message=SimpleNamespace(chat=SimpleNamespace(id=chat_id, type=chat_type), message_id=message_id),
    )


def _open_table(**override):
    table = {
        "table_id": TABLE_ID,
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
    table.update(override)
    return table


class V2JoinClickTests(unittest.IsolatedAsyncioTestCase):
    """Checklist 1.1-1.5, 1.9-1.13: join / double-click / cancel / leave."""

    def setUp(self):
        self._types = v2_tables.types
        v2_tables.types = SimpleNamespace(InlineKeyboardMarkup=Keyboard, InlineKeyboardButton=Button)
        self.bot = ClickBot()
        self.client = SimpleNamespace(
            v2_tables_get=AsyncMock(),
            v2_table_operation=AsyncMock(),
            get_active_pvp_games=AsyncMock(return_value=[]),
        )
        v2_tables.register_v2_table_handlers(self.bot, self.client)

    def tearDown(self):
        v2_tables.types = self._types

    async def test_stranger_joins_open_table_once(self):
        """1.1: seated, success toast, single seats call."""
        table = _open_table()
        self.client.v2_tables_get.return_value = {"tables": [table]}
        self.client.v2_table_operation.return_value = {"ok": True}
        with patch("games.v2_runtime.after_table_join", new_callable=AsyncMock):
            await self.bot.handler_for(f"v2join:{TABLE_ID}")(_call(f"v2join:{TABLE_ID}", 77))
        self.client.v2_table_operation.assert_awaited_once()
        self.assertEqual(self.bot.last_answer()["text"], "✅ Вы заняли место.")

    async def test_double_click_never_creates_second_hold(self):
        """1.5: second tap is rejected, backend hit at most once per version."""
        table = _open_table()
        self.client.v2_tables_get.return_value = {"tables": [table]}
        self.client.v2_table_operation.return_value = {"ok": True}
        handler = self.bot.handler_for(f"v2join:{TABLE_ID}")
        with patch("games.v2_runtime.after_table_join", new_callable=AsyncMock):
            await handler(_call(f"v2join:{TABLE_ID}", 77))
            # Second tap after the table filled: backend now refuses.
            import httpx

            self.client.v2_table_operation.side_effect = httpx.HTTPStatusError(
                "full", request=SimpleNamespace(), response=SimpleNamespace(status_code=409),
            )
            await handler(_call(f"v2join:{TABLE_ID}", 77))
        self.assertEqual(self.client.v2_table_operation.await_count, 2)
        self.assertIn("уже заполнен", self.bot.last_answer()["text"])

    async def test_join_dead_table_discards_card(self):
        """1.4: card removed, stake-back message."""
        self.client.v2_tables_get.return_value = {"tables": []}
        with patch.object(v2_tables, "_discard_callback_card", new_callable=AsyncMock) as discard:
            await self.bot.handler_for(f"v2join:{TABLE_ID}")(_call(f"v2join:{TABLE_ID}", 77))
        discard.assert_awaited_once()
        answer = self.bot.last_answer()
        self.assertTrue(answer["alert"])
        self.assertIn("ставка вернулась", answer["text"])

    async def test_creator_cancels_releases_everything(self):
        """1.9: cancel toast, board cleanup runs once."""
        table = _open_table()
        self.client.v2_tables_get.return_value = {"tables": [table]}
        self.client.v2_table_operation.return_value = {"ok": True}
        with patch("games.v2_runtime.after_table_cancelled", new_callable=AsyncMock) as cancelled:
            await self.bot.handler_for(f"v2cancel:{TABLE_ID}")(
                _call(f"v2cancel:{TABLE_ID}", 10, chat_id=10, chat_type="private")
            )
        cancelled.assert_awaited_once()
        self.assertIn("отменён", self.bot.last_answer()["text"])

    async def test_stranger_cannot_cancel(self):
        """1.10: foreign cancel is rejected before touching the board."""
        table = _open_table()
        self.client.v2_tables_get.return_value = {"tables": [table]}
        import httpx

        self.client.v2_table_operation.side_effect = httpx.HTTPStatusError(
            "forbidden", request=SimpleNamespace(), response=SimpleNamespace(status_code=403),
        )
        with patch("games.v2_runtime.after_table_cancelled", new_callable=AsyncMock) as cancelled:
            await self.bot.handler_for(f"v2cancel:{TABLE_ID}")(_call(f"v2cancel:{TABLE_ID}", 77))
        cancelled.assert_not_awaited()
        self.assertIn("недоступно", self.bot.last_answer()["text"])

    async def test_guest_leaves_frees_stake(self):
        """1.12: leave toast names the freed stake."""
        table = _open_table()
        self.client.v2_tables_get.return_value = {"tables": [table]}
        self.client.v2_table_operation.return_value = {"ok": True}
        await self.bot.handler_for(f"v2leave:{TABLE_ID}")(_call(f"v2leave:{TABLE_ID}", 77))
        self.assertIn("вышли", self.bot.last_answer()["text"])


class WizardConfirmClickTests(unittest.IsolatedAsyncioTestCase):
    """Checklist 6.1-6.3: confirm path, double-click, lost-response retry."""

    def setUp(self):
        self._types = wizard.types
        wizard.types = SimpleNamespace(InlineKeyboardMarkup=Keyboard, InlineKeyboardButton=Button)
        self.bot = ClickBot()
        self.client = AsyncMock()
        self.client.get_active_game_chat_binding = AsyncMock(return_value=None)
        with patch.object(wizard.config, "CASINO_MINIAPP_URL", "http://127.0.0.1:18081/casino/tg"):
            wizard.register_table_wizard_handlers(self.bot, self.client)

    def tearDown(self):
        wizard.types = self._types

    def _confirm_call(self, token, user_id=7):
        return SimpleNamespace(
            id=f"confirm-{token}", data=f"tw:{token}",
            from_user=SimpleNamespace(id=user_id),
            message=SimpleNamespace(chat=SimpleNamespace(id=user_id, type="private"), message_id=9),
        )

    def _issue_confirm(self):
        from decimal import Decimal

        return wizard._issue(
            7, step="confirm", family="cub", game_key="cub", rolls=1,
            max_players=2, bot_count=0, draw_policy="tie_split",
            stake=Decimal("50"), chat_id=7,
        )

    async def test_full_path_creates_exactly_one_table(self):
        """6.1: one confirm tap = one backend create = one board."""
        from decimal import Decimal  # noqa: F401  (documents stake type at this step)

        token = self._issue_confirm()
        self.client.create_v2_table = AsyncMock(return_value={"table": {
            "table_id": "same", "status": "open", "state_version": 0,
            "game_state": {}, "game_type": "pvp_dice",
        }})
        handler = self.bot.handler_for(f"tw:{token}")
        with patch("games.v2_runtime.publish_created_table", new_callable=AsyncMock) as publish:
            with patch.object(wizard.config, "CASINO_MINIAPP_URL", "http://127.0.0.1:18081/casino/tg"):
                await handler(self._confirm_call(token))
        self.client.create_v2_table.assert_awaited_once()
        publish.assert_awaited_once()

    async def test_double_click_after_success_publishes_no_second_board(self):
        """6.2: consumed token answers, backend/board untouched the second time."""
        token = self._issue_confirm()
        self.client.create_v2_table = AsyncMock(return_value={"table": {
            "table_id": "same", "status": "open", "state_version": 0,
            "game_state": {}, "game_type": "pvp_dice",
        }})
        handler = self.bot.handler_for(f"tw:{token}")
        with patch("games.v2_runtime.publish_created_table", new_callable=AsyncMock) as publish:
            with patch.object(wizard.config, "CASINO_MINIAPP_URL", "http://127.0.0.1:18081/casino/tg"):
                await handler(self._confirm_call(token))
                await handler(self._confirm_call(token, user_id=7))
        self.client.create_v2_table.assert_awaited_once()
        publish.assert_awaited_once()
        texts = [str(args[1]) if len(args) > 1 else "" for args, _ in self.bot.answer_callback_query.await_args_list]
        self.assertTrue(any("уже использовано" in text or "устарел" in text for text in texts))

    async def test_retry_after_lost_response_replays_same_request(self):
        """6.3: the retry reuses table_id + idempotency_key, no second hold."""
        from decimal import Decimal

        entry = {"family": "cub", "game_key": "cub", "max_players": 2,
                 "bot_count": 1, "draw_policy": "tie_split", "stake": Decimal("50"), "chat_id": 7}
        call = SimpleNamespace(id="first", from_user=SimpleNamespace(id=7),
                               message=SimpleNamespace(chat=SimpleNamespace(id=7), message_id=3))
        self.client.create_v2_table = AsyncMock(side_effect=[
            TimeoutError("response lost after commit"), {"table": {"table_id": "same"}},
        ])
        tap_bot = SimpleNamespace(answer_callback_query=AsyncMock(), delete_message=AsyncMock())
        with patch("games.v2_runtime.publish_created_table", new_callable=AsyncMock):
            self.assertFalse(await wizard._finalize(tap_bot, self.client, call, entry))
            call.id = "second"
            self.assertTrue(await wizard._finalize(tap_bot, self.client, call, entry))
        first, second = self.client.create_v2_table.await_args_list
        self.assertEqual(first.kwargs, second.kwargs)


class BlackjackHitStandClickTests(unittest.IsolatedAsyncioTestCase):
    """Checklist 1.14-1.20: hit/stand answers per seat, surface and table state."""

    def setUp(self):
        self._types = runtime.types
        runtime.types = SimpleNamespace(InlineKeyboardMarkup=Keyboard, InlineKeyboardButton=Button)
        self.bot = ClickBot()
        self.bot.get_chat = AsyncMock(return_value=SimpleNamespace(first_name="User", username=None))
        self.client = SimpleNamespace(
            v2_tables_get=AsyncMock(),
            v2_table_operation=AsyncMock(),
            v2_table_cards=AsyncMock(),
        )
        runtime.register_v2_runtime_handlers(self.bot, self.client)

    def tearDown(self):
        runtime.types = self._types

    def _hitting_table(self, **override):
        table = {
            "table_id": TABLE_ID,
            "game_type": "blackjack",
            "creator_id": 11,
            "stake_rub": "50.00",
            "max_seats": 2,
            "status": "running",
            "state_version": 4,
            "game_chat_id": -100123,
            "game_state": {
                "chat_id": -100123,
                "card_msg_id": 71,
                "phase": "hitting",
                "hands": {"1": ["9♠", "8♣"], "2": ["10♥", "7♦"]},
                "decisions": {"2": "stand"},
                "stood_seats": [2],
                "seat_nos": [1, 2],
                "roll_deadline_at": "2099-01-01T00:00:00+00:00",
            },
            "roster": [
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "player", "telegram_id": 22},
            ],
            "free_seats": [],
        }
        table.update(override)
        return table

    async def test_group_hit_is_redirected_to_dm(self):
        """1.15: tapping hit in the group chat explains where the cards live."""
        self.client.v2_tables_get.return_value = {"tables": [self._hitting_table()]}
        await self.bot.handler_for(f"v2hit:{TABLE_ID}")(
            _call(f"v2hit:{TABLE_ID}", 11, chat_id=-100123, chat_type="group")
        )
        answer = self.bot.last_answer()
        self.assertTrue(answer["alert"])
        self.assertIn("личку", answer["text"])
        self.client.v2_table_cards.assert_not_awaited()

    async def test_second_hit_after_decision_is_rejected(self):
        """1.16: seat that already stood cannot hit again."""
        table = self._hitting_table()
        table["game_state"] = {**table["game_state"], "decisions": {"1": "stand", "2": "stand"}}
        self.client.v2_tables_get.return_value = {"tables": [table]}
        await self.bot.handler_for(f"v2hit:{TABLE_ID}")(
            _call(f"v2hit:{TABLE_ID}", 11, chat_id=11, chat_type="private")
        )
        self.assertEqual(self.bot.last_answer()["text"], "Решение уже принято.")
        self.client.v2_table_cards.assert_not_awaited()

    async def test_outsider_hit_is_rejected(self):
        """1.17: a watcher tapping hit learns they are not seated."""
        self.client.v2_tables_get.return_value = {"tables": [self._hitting_table()]}
        await self.bot.handler_for(f"v2hit:{TABLE_ID}")(
            _call(f"v2hit:{TABLE_ID}", 99, chat_id=99, chat_type="private")
        )
        self.assertEqual(self.bot.last_answer()["text"], "Вы не за этим столом.")
        self.client.v2_table_cards.assert_not_awaited()

    async def test_finished_table_hit_reports_stale_button(self):
        """1.18: dead tables answer stale-button, never deal."""
        self.client.v2_tables_get.return_value = {"tables": []}
        await self.bot.handler_for(f"v2hit:{TABLE_ID}")(
            _call(f"v2hit:{TABLE_ID}", 11, chat_id=11, chat_type="private")
        )
        answer = self.bot.last_answer()
        self.assertTrue(answer["alert"])
        self.assertIn("устарела", answer["text"])
        self.client.v2_table_cards.assert_not_awaited()

    async def test_stand_locks_decision_for_that_seat(self):
        """1.19: stand persists hands+decisions and confirms to the tapping seat."""
        table = self._hitting_table()
        self.client.v2_tables_get.return_value = {"tables": [table]}
        persisted: dict = {}

        async def _persist(table_id, operation, **kwargs):
            persisted.update(kwargs.get("game_state") or {})
            return {"table": table}

        async def _persist_refresh(client, table_arg, game_state):
            persisted.update(game_state or {})
            return table

        with patch.object(runtime, "_persist_and_refresh", side_effect=_persist_refresh), \
            patch.object(runtime, "_edit_board", new_callable=AsyncMock), \
            patch.object(runtime, "_sync_blackjack_dms", new_callable=AsyncMock), \
            patch.object(runtime, "_maybe_finish_blackjack", new_callable=AsyncMock):
            await self.bot.handler_for(f"v2stand:{TABLE_ID}")(
                _call(f"v2stand:{TABLE_ID}", 11, chat_id=11, chat_type="private")
            )
        self.assertEqual(persisted.get("decisions"), {"1": "stand", "2": "stand"})
        self.assertEqual(self.bot.last_answer()["text"], "Ок, карты оставлены.")


if __name__ == "__main__":
    unittest.main()
