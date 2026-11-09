import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from games.roulette_cmd import parse_roulette_command
from tests.telebot_stub import TelebotModules


SETTINGS = {
    "enabled_games": {"roulette": True},
    "min_bet_rub": 10,
    "max_bet_rub": 100000,
}


def _dm_message(text: str = "/roulette red 50"):
    user = SimpleNamespace(id=8443902979, username="absoluteop", first_name="A")
    return SimpleNamespace(
        from_user=user,
        chat=SimpleNamespace(id=8443902979, type="private"),
        text=text,
        message_id=21,
    )


def _group_message(text: str = "/roulette red 50"):
    user = SimpleNamespace(id=8443902979, username="absoluteop", first_name="A")
    return SimpleNamespace(
        from_user=user,
        chat=SimpleNamespace(id=-5562276559, type="supergroup"),
        text=text,
        message_id=22,
    )


def _client(**overrides):
    client = AsyncMock()
    client.get_active_game_chat_binding = AsyncMock(
        return_value={"chat_id": -5562276559}
    )
    client.get_roulette_table = AsyncMock(
        return_value={"status": "open", "collect_seconds": 25}
    )
    client.get_casino_settings = AsyncMock(return_value=SETTINGS)
    client.place_roulette_table_bet = AsyncMock(
        return_value={"status": "open", "collect_seconds": 25, "closes_at": None}
    )
    for key, value in overrides.items():
        setattr(client, key, value)
    return client


with TelebotModules("games.roulette_table", "games.site_links", "games.roulette_card", "games.live_card"):
    roulette_table = importlib.import_module("games.roulette_table")
    roulette_card = importlib.import_module("games.roulette_card")
    chat_reaper = importlib.import_module("games.chat_reaper")


class RouletteTableNotifyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await roulette_card.drain_state()
        chat_reaper.reset_state()

    def test_http_miniapp_does_not_attach_web_app_keyboard(self):
        with patch.object(
            roulette_table.config,
            "CASINO_MINIAPP_URL",
            "http://127.0.0.1:18081/casino/tg",
        ):
            self.assertEqual(
                roulette_table.roulette_table_url(),
                "http://127.0.0.1:18081/casino/play/roulette?mode=players",
            )
            self.assertIsNone(roulette_table.https_table_url())
            keyboard = roulette_table._table_keyboard()
            self.assertIsNotNone(keyboard)
            urls = [
                button.url
                for row in keyboard.keyboard
                for button in row
                if getattr(button, "url", None)
            ]
            web = [
                button.web_app
                for row in keyboard.keyboard
                for button in row
                if getattr(button, "web_app", None)
            ]
            self.assertEqual(urls, ["http://127.0.0.1:18081/casino/play/roulette?mode=players"])
            self.assertEqual(web, [])

    def test_https_miniapp_uses_url_not_web_app(self):
        with patch.object(
            roulette_table.config,
            "CASINO_MINIAPP_URL",
            "https://example.test/casino/tg",
        ):
            self.assertEqual(
                roulette_table.https_table_url(),
                "https://example.test/casino/play/roulette?mode=players",
            )
            keyboard = roulette_table._table_keyboard()
            self.assertIsNotNone(keyboard)
            web = [
                button.web_app
                for row in keyboard.keyboard
                for button in row
                if getattr(button, "web_app", None)
            ]
            urls = [
                button.url
                for row in keyboard.keyboard
                for button in row
                if getattr(button, "url", None)
            ]
            self.assertEqual(web, [])
            self.assertEqual(urls, ["https://example.test/casino/play/roulette?mode=players"])

    def test_confirm_text_says_stake_accepted(self):
        parsed = parse_roulette_command("/roulette red 50")
        with patch.object(
            roulette_table.config,
            "CASINO_MINIAPP_URL",
            "http://127.0.0.1:18081/casino/tg",
        ):
            text = roulette_table.confirm_text(parsed, {"status": "open", "collect_seconds": 25})
        self.assertIn("Ставка принята", text)
        self.assertIn("красное — 50.00 ₽", text)
        self.assertIn("Списание: 50.00 ₽", text)
        self.assertIn("Смотреть на сайте", text)
        self.assertIn("http://127.0.0.1:18081/casino/play/roulette?mode=players", text)

    async def test_reply_html_retries_without_keyboard(self):
        bot = SimpleNamespace(
            reply_to=AsyncMock(
                side_effect=[RuntimeError("Only HTTPS links are allowed"), SimpleNamespace()]
            )
        )
        with patch.object(
            roulette_table.config,
            "CASINO_MINIAPP_URL",
            "https://example.test/casino/tg",
        ):
            await roulette_table.reply_html(bot, object(), "ok")
        self.assertEqual(bot.reply_to.await_count, 2)
        first = bot.reply_to.await_args_list[0]
        second = bot.reply_to.await_args_list[1]
        self.assertIsNotNone(first.kwargs.get("reply_markup"))
        self.assertNotIn("reply_markup", second.kwargs)

    async def test_dm_bet_replies_without_mirroring_to_game_chat(self):
        bot = SimpleNamespace(
            reply_to=AsyncMock(),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=101)),
            edit_message_text=AsyncMock(),
            delete_message=AsyncMock(),
        )
        client = _client(
            place_roulette_table_bet=AsyncMock(
                return_value={
                    "status": "open",
                    "collect_seconds": 25,
                    "round_id": "ed42ffe8-aaaa-bbbb-cccc-dddddddddddd",
                    "closes_at": None,
                    "player_count": 1,
                    "players": [
                        {
                            "user_id": 8443902979,
                            "display_name": "A",
                            "bet": "red",
                            "title_ru": "красное",
                            "odds_ru": "1:1",
                            "stake_rub": 50,
                        }
                    ],
                }
            )
        )
        guard = roulette_table.ActiveGameChatGuard(client)
        with patch.object(
            roulette_table.config,
            "CASINO_MINIAPP_URL",
            "http://127.0.0.1:18081/casino/tg",
        ):
            await roulette_table.handle_roulette_command(
                bot, client, _dm_message(), guard=guard
            )
        client.place_roulette_table_bet.assert_awaited_once()
        placed = client.place_roulette_table_bet.await_args
        self.assertEqual(placed.kwargs["telegram_id"], 8443902979)
        self.assertEqual(placed.kwargs["notify_chat_id"], 8443902979)
        self.assertEqual(placed.kwargs["chips"], [{"bet": "red", "amount_rub": "50.00"}])
        bot.reply_to.assert_not_awaited()
        bot.send_message.assert_awaited_once()
        send = bot.send_message.await_args
        self.assertEqual(send.args[0], 8443902979)
        self.assertIn("Ставка принята", send.args[1])
        self.assertIn("красное", send.args[1])
        markup = send.kwargs.get("reply_markup")
        self.assertIsNotNone(markup)
        urls = [
            button.url
            for row in markup.keyboard
            for button in row
            if getattr(button, "url", None)
        ]
        web = [
            button.web_app
            for row in markup.keyboard
            for button in row
            if getattr(button, "web_app", None)
        ]
        self.assertEqual(urls, ["http://127.0.0.1:18081/casino/play/roulette?mode=players"])
        self.assertEqual(web, [])

    async def test_group_bet_does_not_duplicate_into_bound_chat(self):
        bot = SimpleNamespace(
            reply_to=AsyncMock(),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=101)),
            edit_message_text=AsyncMock(),
            delete_message=AsyncMock(),
        )
        client = _client()
        guard = roulette_table.ActiveGameChatGuard(client)
        await roulette_table.handle_roulette_command(
            bot, client, _group_message(), guard=guard
        )
        bot.reply_to.assert_not_awaited()
        bot.send_message.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.args[0], -5562276559)
        self.assertIn("Ставка принята", bot.send_message.await_args.args[1])
        self.assertEqual(
            client.place_roulette_table_bet.await_args.kwargs["notify_chat_id"],
            -5562276559,
        )
        bot.delete_message.assert_awaited_once_with(-5562276559, 22)

    async def test_cheatsheet_still_replies_when_web_app_url_is_http(self):
        bot = SimpleNamespace(
            reply_to=AsyncMock(return_value=SimpleNamespace(message_id=50)),
            send_message=AsyncMock(),
            delete_message=AsyncMock(),
        )
        client = _client()
        guard = roulette_table.ActiveGameChatGuard(client)
        with patch.object(
            roulette_table.config,
            "CASINO_MINIAPP_URL",
            "http://127.0.0.1:18081/casino/tg",
        ):
            await roulette_table.handle_roulette_command(
                bot, client, _dm_message("/roulette"), guard=guard
            )
        client.place_roulette_table_bet.assert_not_awaited()
        bot.reply_to.assert_awaited_once()
        self.assertIn("Рулетка 0–36", bot.reply_to.await_args.args[1])
        self.assertIn("Смотреть на сайте", bot.reply_to.await_args.args[1])
        bot.send_message.assert_not_awaited()
