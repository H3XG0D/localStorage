import importlib
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from games.help import parse_help_topic, render_help
from tests.telebot_stub import TelebotModules


SETTINGS = {
    "enabled_games": {"jackpot": True},
    "min_bet_rub": 10,
    "max_bet_rub": 100000,
}


def _dm_message(text: str = "/jackpot 100"):
    user = SimpleNamespace(id=8443902979, username="absoluteop", first_name="A")
    return SimpleNamespace(
        from_user=user,
        chat=SimpleNamespace(id=8443902979, type="private"),
        text=text,
        message_id=21,
    )


def _group_message(text: str = "/jackpot 100"):
    user = SimpleNamespace(id=8443902979, username="absoluteop", first_name="A")
    return SimpleNamespace(
        from_user=user,
        chat=SimpleNamespace(id=-5562276559, type="supergroup"),
        text=text,
        message_id=22,
    )


def _snapshot(**overrides):
    data = {
        "status": "open",
        "collect_seconds": 300,
        "pot_rub": 150.0,
        "player_count": 2,
        "max_players": 30,
        "rake_percent": 5.0,
        "min_bet_rub": 10,
        "max_bet_rub": 100000,
        "closes_at": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
        "my_amount_rub": 50.0,
        "my_chance_pct": 33.33,
        "players": [
            {
                "user_id": 8443902979,
                "display_name": "A",
                "amount_rub": 50.0,
                "chance_pct": 33.33,
            },
            {
                "user_id": 22,
                "display_name": "Bob",
                "amount_rub": 100.0,
                "chance_pct": 66.67,
            },
        ],
    }
    data.update(overrides)
    return data


def _client(**overrides):
    client = AsyncMock()
    client.get_active_game_chat_binding = AsyncMock(
        return_value={"chat_id": -5562276559}
    )
    client.get_jackpot = AsyncMock(return_value=_snapshot())
    client.get_casino_settings = AsyncMock(return_value=SETTINGS)
    client.place_jackpot_bet = AsyncMock(
        return_value=_snapshot(my_amount_rub=100.0, my_chance_pct=50.0, pot_rub=200.0)
    )
    for key, value in overrides.items():
        setattr(client, key, value)
    return client


with TelebotModules("games.jackpot", "games.site_links", "games.jackpot_card", "games.live_card"):
    jackpot = importlib.import_module("games.jackpot")
    jackpot_card = importlib.import_module("games.jackpot_card")
    chat_reaper = importlib.import_module("games.chat_reaper")


class JackpotParseTests(unittest.TestCase):
    def test_bare_command_is_status(self):
        self.assertIsNone(jackpot.parse_jackpot_command("/jackpot"))
        self.assertIsNone(jackpot.parse_jackpot_command("/джекпот"))

    def test_amount_with_and_without_suffix(self):
        self.assertEqual(jackpot.parse_jackpot_command("/jackpot 100"), Decimal("100.00"))
        self.assertEqual(jackpot.parse_jackpot_command("/jackpot 50р"), Decimal("50.00"))
        self.assertEqual(jackpot.parse_jackpot_command("/джекпот 25.5"), Decimal("25.50"))

    def test_bad_args_raise_usage(self):
        with self.assertRaises(jackpot.JackpotCommandError):
            jackpot.parse_jackpot_command("/jackpot red 50")
        with self.assertRaises(jackpot.JackpotCommandError):
            jackpot.parse_jackpot_command("/jackpot nope")

    def test_status_text_lists_bank_timer_and_chances(self):
        text = jackpot.status_text(_snapshot(), viewer_id=8443902979)
        self.assertIn("Банк: <b>150 ₽</b>", text)
        self.assertIn("Игроков: 2 / 30", text)
        self.assertIn("Рейк: 5%", text)
        self.assertIn("До спина", text)
        self.assertIn("33.33%", text)
        self.assertIn("Bob", text)
        self.assertIn("Вы: 50 ₽", text)
        self.assertIn("/jackpot 100", text)

    def test_waiting_for_first_stake(self):
        text = jackpot.timer_line(_snapshot(closes_at=None, pot_rub=0, players=[], player_count=0))
        self.assertIn("Ждём первую ставку", text)

    def test_jackpot_interval_tightens_near_close(self):
        far = _snapshot(closes_at=(datetime.now(timezone.utc) + timedelta(seconds=200)).isoformat())
        minute = _snapshot(closes_at=(datetime.now(timezone.utc) + timedelta(seconds=40)).isoformat())
        last = _snapshot(closes_at=(datetime.now(timezone.utc) + timedelta(seconds=8)).isoformat())
        self.assertEqual(jackpot_card.interval_for(far), 30.0)
        self.assertEqual(jackpot_card.interval_for(minute), 5.0)
        self.assertEqual(jackpot_card.interval_for(last), 2.0)


class JackpotNotifyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await jackpot_card.drain_state()
        from games.drama import drain_drama, reset_state

        await drain_drama()
        reset_state()
        chat_reaper.reset_state()

    def test_http_miniapp_does_not_attach_web_app_keyboard(self):
        with patch.object(
            jackpot.config,
            "CASINO_MINIAPP_URL",
            "http://127.0.0.1:18081/casino/tg",
        ):
            self.assertEqual(
                jackpot.jackpot_play_url(),
                "http://127.0.0.1:18081/casino/play/jackpot?mode=players",
            )
            self.assertIsNone(jackpot.https_play_url())
            keyboard = jackpot._status_keyboard(_snapshot())
            self.assertIsNotNone(keyboard)
            web = [
                button.web_app
                for row in keyboard.keyboard
                for button in row
                if getattr(button, "web_app", None)
            ]
            self.assertEqual(web, [])
            callbacks = [
                button.callback_data
                for row in keyboard.keyboard
                for button in row
                if button.callback_data
            ]
            self.assertIn("jpbet:100", callbacks)
            self.assertNotIn("jpbet:custom", callbacks)
            urls = [
                button.url
                for row in keyboard.keyboard
                for button in row
                if getattr(button, "url", None)
            ]
            self.assertEqual(urls, [])

    def test_https_miniapp_uses_url_not_web_app(self):
        with patch.object(
            jackpot.config,
            "CASINO_MINIAPP_URL",
            "https://example.test/casino/tg",
        ):
            keyboard = jackpot._status_keyboard(_snapshot(), include_watch=True)
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
            self.assertEqual(urls, ["https://example.test/casino/play/jackpot?mode=players"])

    def test_confirm_text_says_stake_accepted(self):
        with patch.object(
            jackpot.config,
            "CASINO_MINIAPP_URL",
            "http://127.0.0.1:18081/casino/tg",
        ):
            text = jackpot.confirm_text(
                Decimal("100"),
                {"status": "open", "collect_seconds": 300, "my_amount_rub": 100, "my_chance_pct": 50, "pot_rub": 200},
            )
        self.assertIn("Ставка принята", text)
        self.assertIn("Списание: 100 ₽", text)
        self.assertIn("Банк: 200 ₽", text)
        self.assertIn("Смотреть на сайте", text)
        self.assertIn("http://127.0.0.1:18081/casino/play/jackpot?mode=players", text)

    async def test_reply_html_retries_without_keyboard(self):
        bot = SimpleNamespace(
            reply_to=AsyncMock(
                side_effect=[RuntimeError("Only HTTPS links are allowed"), SimpleNamespace()]
            )
        )
        with patch.object(
            jackpot.config,
            "CASINO_MINIAPP_URL",
            "https://example.test/casino/tg",
        ):
            await jackpot.reply_html(bot, object(), "ok", snapshot=_snapshot())
        self.assertEqual(bot.reply_to.await_count, 2)
        first = bot.reply_to.await_args_list[0]
        second = bot.reply_to.await_args_list[1]
        self.assertIsNotNone(first.kwargs.get("reply_markup"))
        self.assertNotIn("reply_markup", second.kwargs)

    async def test_status_command_does_not_place(self):
        bot = SimpleNamespace(
            reply_to=AsyncMock(return_value=SimpleNamespace(message_id=50)),
            send_message=AsyncMock(),
            delete_message=AsyncMock(),
        )
        client = _client()
        guard = jackpot.ActiveGameChatGuard(client)
        with patch.object(
            jackpot.config,
            "CASINO_MINIAPP_URL",
            "http://127.0.0.1:18081/casino/tg",
        ):
            await jackpot.handle_jackpot_command(
                bot, client, _dm_message("/jackpot"), guard=guard
            )
        client.place_jackpot_bet.assert_not_awaited()
        bot.reply_to.assert_awaited_once()
        self.assertIn("Банк:", bot.reply_to.await_args.args[1])
        self.assertIn("До спина", bot.reply_to.await_args.args[1])
        bot.send_message.assert_not_awaited()

    async def test_dm_bet_replies_without_mirroring_to_game_chat(self):
        bot = SimpleNamespace(
            reply_to=AsyncMock(),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=101)),
            edit_message_text=AsyncMock(),
            delete_message=AsyncMock(),
        )
        client = _client()
        guard = jackpot.ActiveGameChatGuard(client)
        with patch.object(
            jackpot.config,
            "CASINO_MINIAPP_URL",
            "http://127.0.0.1:18081/casino/tg",
        ):
            await jackpot.handle_jackpot_command(
                bot, client, _dm_message(), guard=guard
            )
        client.place_jackpot_bet.assert_awaited_once()
        placed = client.place_jackpot_bet.await_args
        self.assertEqual(placed.kwargs["telegram_id"], 8443902979)
        self.assertEqual(placed.kwargs["notify_chat_id"], 8443902979)
        self.assertEqual(placed.kwargs["amount_rub"], Decimal("100.00"))
        bot.reply_to.assert_not_awaited()
        bot.send_message.assert_awaited_once()
        send = bot.send_message.await_args
        self.assertEqual(send.args[0], 8443902979)
        self.assertIn("Ставка принята", send.args[1])
        self.assertIn("Банк:", send.args[1])
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
        self.assertEqual(urls, ["http://127.0.0.1:18081/casino/play/jackpot?mode=players"])
        self.assertEqual(web, [])

    async def test_group_bet_does_not_duplicate_into_bound_chat(self):
        bot = SimpleNamespace(
            reply_to=AsyncMock(),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=101)),
            edit_message_text=AsyncMock(),
            delete_message=AsyncMock(),
        )
        client = _client()
        guard = jackpot.ActiveGameChatGuard(client)
        await jackpot.handle_jackpot_command(bot, client, _group_message(), guard=guard)
        bot.reply_to.assert_not_awaited()
        bot.send_message.assert_awaited_once()
        self.assertIn("Ставка принята", bot.send_message.await_args.args[1])
        self.assertEqual(bot.send_message.await_args.args[0], -5562276559)
        self.assertEqual(
            client.place_jackpot_bet.await_args.kwargs["notify_chat_id"],
            -5562276559,
        )
        bot.delete_message.assert_awaited_once_with(-5562276559, 22)

    def _group_callback(self, data: str = "jpbet:100"):
        return SimpleNamespace(
            id="jp-cb",
            data=data,
            from_user=SimpleNamespace(id=8443902979, username="absoluteop", first_name="A"),
            message=SimpleNamespace(
                chat={"id": -5562276559, "type": "supergroup"},
                message_id=11,
            ),
        )

    async def test_group_stake_callback_places_in_bound_chat(self):
        bot = SimpleNamespace(
            reply_to=AsyncMock(),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=101)),
            edit_message_text=AsyncMock(),
            delete_message=AsyncMock(),
            answer_callback_query=AsyncMock(),
        )
        client = _client()
        guard = jackpot.ActiveGameChatGuard(client)
        with patch.object(
            jackpot.config,
            "CASINO_MINIAPP_URL",
            "http://127.0.0.1:18081/casino/tg",
        ):
            await jackpot.handle_jackpot_callback(
                bot, client, self._group_callback(), guard=guard
            )
        client.place_jackpot_bet.assert_awaited_once()
        placed = client.place_jackpot_bet.await_args
        self.assertEqual(placed.kwargs["telegram_id"], 8443902979)
        self.assertEqual(placed.kwargs["notify_chat_id"], -5562276559)
        self.assertEqual(placed.kwargs["amount_rub"], Decimal("100.00"))
        bot.answer_callback_query.assert_awaited()
        bot.reply_to.assert_not_awaited()
        bot.send_message.assert_awaited_once()
        self.assertIn("Ставка принята", bot.send_message.await_args.args[1])

    async def test_foreign_group_callback_is_rejected(self):
        bot = SimpleNamespace(
            reply_to=AsyncMock(),
            send_message=AsyncMock(),
            answer_callback_query=AsyncMock(),
        )
        client = _client()
        client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -999})
        guard = jackpot.ActiveGameChatGuard(client)
        await jackpot.handle_jackpot_callback(
            bot, client, self._group_callback(), guard=guard
        )
        client.place_jackpot_bet.assert_not_awaited()
        bot.answer_callback_query.assert_awaited_once()
        self.assertIn("игровом чате", bot.answer_callback_query.await_args.args[1])
        bot.reply_to.assert_not_awaited()

    async def test_foreign_group_is_rejected(self):
        bot = SimpleNamespace(
            reply_to=AsyncMock(return_value=SimpleNamespace(message_id=50)),
            send_message=AsyncMock(),
            delete_message=AsyncMock(),
        )
        client = _client()
        client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -999})
        guard = jackpot.ActiveGameChatGuard(client)
        await jackpot.handle_jackpot_command(bot, client, _group_message(), guard=guard)
        client.place_jackpot_bet.assert_not_awaited()
        bot.reply_to.assert_awaited_once()
        self.assertIn("игровом чате", bot.reply_to.await_args.args[1])


class JackpotHelpTests(unittest.TestCase):
    def test_help_jackpot_page(self):
        settings = {
            "min_bet_rub": 10,
            "max_bet_rub": 100000,
            "commission_rate_wagering_active": 15,
            "commission_rate_wagering_complete": 5,
            "wagering_percent": 100,
            "jackpot_collect_seconds": 300,
        }
        text = render_help(settings, "/help jackpot")
        self.assertIn("/jackpot 100", text)
        self.assertIn("play/jackpot", text)
        self.assertLess(len(text), 4096)
        self.assertEqual(parse_help_topic("/help джекпот"), "jackpot")
        index = render_help(settings, "/help")
        self.assertIn("/help jackpot", index)


if __name__ == "__main__":
    unittest.main()
