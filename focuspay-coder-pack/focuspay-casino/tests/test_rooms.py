import importlib
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules


def _snapshot(**overrides):
    data = {
        "room_id": "fr-aabbccddeeff",
        "status": "open",
        "creator_id": 7,
        "stake_rub": 100.0,
        "seat_count": 3,
        "filled": 1,
        "free_seats": [1, 2],
        "pot_rub": 100.0,
        "rake_percent": 5.0,
        "players": [{"user_id": 7, "display_name": "Alex", "participant_kind": "player"}],
        "my_seat": 0,
        "can_add_bot": True,
        "can_leave": True,
        "can_cancel": True,
        "min_bet_rub": 10,
        "max_bet_rub": 100000,
        "enabled": True,
    }
    data.update(overrides)
    return data


def _client(**overrides):
    client = AsyncMock()
    client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -5562276559})
    client.list_fixed_rooms = AsyncMock(return_value={"rooms": [_snapshot(my_seat=None)], "rake_percent": 5})
    client.get_fixed_room = AsyncMock(return_value=_snapshot())
    client.create_fixed_room = AsyncMock(return_value=_snapshot())
    client.join_fixed_room = AsyncMock(return_value=_snapshot(my_seat=1, filled=2))
    client.leave_fixed_room = AsyncMock(return_value=_snapshot(my_seat=None, filled=0, can_leave=False))
    client.cancel_fixed_room = AsyncMock(return_value=_snapshot(status="cancelled"))
    client.add_fixed_room_bot = AsyncMock(return_value=_snapshot(filled=2, can_add_bot=True))
    for key, value in overrides.items():
        setattr(client, key, value)
    return client


with TelebotModules("games.rooms", "games.site_links", "games.rooms_card", "games.live_card"):
    rooms = importlib.import_module("games.rooms")
    rooms_card = importlib.import_module("games.rooms_card")


class Keyboard:
    def __init__(self, *args, **kwargs):
        self.keyboard = []

    def add(self, *buttons):
        self.keyboard.append(list(buttons))


class Button:
    def __init__(self, text, callback_data=None, url=None, web_app=None, **kwargs):
        self.text = text
        self.callback_data = callback_data
        self.url = url
        self.web_app = web_app


class RoomsParseTests(unittest.TestCase):
    def test_callback_join_and_create_payloads(self):
        self.assertEqual(rooms.parse_room_callback("rm:join:fr-aabbccddeeff"), ("join", "fr-aabbccddeeff"))
        self.assertEqual(rooms.parse_room_callback("rm:mk:100:3"), ("mk", "100", "3"))
        self.assertEqual(rooms.parse_room_callback("rm:st:custom"), ("st", "custom"))
        self.assertIsNone(rooms.parse_room_callback("rm:join:../etc"))
        self.assertIsNone(rooms.parse_room_callback("jpbet:100"))

    def test_encode_stake_strips_zeros(self):
        self.assertEqual(rooms.encode_stake(Decimal("100.00")), "100")
        self.assertEqual(rooms.parse_amount_token("50р"), Decimal("50.00"))

    def test_room_card_shows_status_and_countdown_copy(self):
        text = rooms.room_card_text(_snapshot())
        self.assertIn("Комната", text)
        self.assertIn("Alex", text)
        self.assertIn("open", text)
        countdown = rooms.room_card_text(_snapshot(status="countdown", countdown_ends_at="2099-01-01T00:00:00+00:00"))
        self.assertIn("Старт через", countdown)


class RoomsKeyboardTests(unittest.TestCase):
    def setUp(self):
        self.original_types = rooms.types
        rooms.types = SimpleNamespace(InlineKeyboardMarkup=Keyboard, InlineKeyboardButton=Button)

    def tearDown(self):
        rooms.types = self.original_types

    def test_http_card_keyboard_has_url_not_web_app(self):
        with patch.object(rooms, "room_url", return_value="http://127.0.0.1:18081/casino/rooms/fr-aabbccddeeff"):
            keyboard = rooms._card_keyboard(_snapshot())
        urls = [button.url for row in keyboard.keyboard for button in row if button.url]
        web_apps = [button.web_app for row in keyboard.keyboard for button in row if button.web_app]
        self.assertEqual(urls, ["http://127.0.0.1:18081/casino/rooms/fr-aabbccddeeff"])
        self.assertEqual(web_apps, [])
        callbacks = [button.callback_data for row in keyboard.keyboard for button in row if button.callback_data]
        self.assertIn("rm:bot:fr-aabbccddeeff", callbacks)
        self.assertIn("rm:leave:fr-aabbccddeeff", callbacks)
        self.assertNotIn("rm:join:fr-aabbccddeeff", callbacks)


class RoomsFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_types = rooms.types
        rooms.types = SimpleNamespace(InlineKeyboardMarkup=Keyboard, InlineKeyboardButton=Button)
        rooms._awaiting_stake.clear()

    async def asyncTearDown(self):
        from games.drama import drain_drama, reset_state

        await rooms_card.drain_state()
        await drain_drama()
        reset_state()
        rooms.types = self.original_types
        rooms._awaiting_stake.clear()

    def tearDown(self):
        rooms.types = self.original_types
        rooms._awaiting_stake.clear()

    async def test_create_and_join_hit_client(self):
        bot = SimpleNamespace(
            answer_callback_query=AsyncMock(),
            edit_message_text=AsyncMock(),
            send_message=AsyncMock(),
        )
        client = _client()
        user = SimpleNamespace(id=7)
        call = SimpleNamespace(
            id="c1",
            data="rm:mk:100:3",
            from_user=user,
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=9),
        )
        guard = SimpleNamespace(require_callback=AsyncMock(return_value=True))
        await rooms.handle_rooms_callback(bot, client, call, guard=guard)
        client.create_fixed_room.assert_awaited_once()
        kwargs = client.create_fixed_room.await_args.kwargs
        self.assertEqual(kwargs["telegram_id"], 7)
        self.assertEqual(kwargs["seat_count"], 3)
        self.assertEqual(kwargs["stake_rub"], Decimal("100.00"))
        client.join_fixed_room.assert_not_awaited()

        join_call = SimpleNamespace(
            id="c2",
            data="rm:join:fr-aabbccddeeff",
            from_user=SimpleNamespace(id=8),
            message=SimpleNamespace(chat=SimpleNamespace(id=8, type="private"), message_id=10),
        )
        await rooms.handle_rooms_callback(bot, client, join_call, guard=guard)
        client.join_fixed_room.assert_awaited_once_with("fr-aabbccddeeff", telegram_id=8)

    async def test_wizard_entry_asks_for_stake(self):
        bot = SimpleNamespace(edit_message_text=AsyncMock(), send_message=AsyncMock())
        call = SimpleNamespace(
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=3),
        )
        await rooms.start_room_create(bot, _client(), call)
        text = bot.edit_message_text.await_args.args[0]
        self.assertIn("Комната", text)
        self.assertIn("ставку", text.lower())


if __name__ == "__main__":
    unittest.main()
