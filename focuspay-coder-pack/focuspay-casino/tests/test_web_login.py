import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules

with TelebotModules(
    "bot",
    "casino_menu",
    "games.pvp",
    "games.baccara",
    "games.blackjack",
    "games.table_wizard",
    "games.v2_tables",
    "games.v2_runtime",
    "games.fairness",
    "games.roulette_table",
    "games.jackpot",
    "web_login",
):
    casino_bot = importlib.import_module("bot")
    web_login = importlib.import_module("web_login")


TOKEN = "a" * 32


def private_message(text="/start"):
    return SimpleNamespace(
        chat=SimpleNamespace(id=77, type="private"),
        from_user=SimpleNamespace(id=77, username="player", first_name="Player"),
        text=text,
    )


class ExtractCauthTests(unittest.TestCase):
    def test_start_payload(self):
        self.assertEqual(web_login.extract_cauth_token(f"/start cauth_{TOKEN}"), TOKEN)
        self.assertEqual(web_login.extract_cauth_token(f"cauth_{TOKEN}"), TOKEN)
        self.assertIsNone(web_login.extract_cauth_token("/start"))
        self.assertIsNone(web_login.extract_cauth_token("ref_abc"))


class SiteLoginStartTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.resume_client = SimpleNamespace(
            v2_recovery_or_outbox=AsyncMock(return_value={"success": True, "resumed": 0})
        )
        self.resume_patch = patch.object(
            casino_bot, "get_focuspay_client", AsyncMock(return_value=self.resume_client)
        )
        self.resume_patch.start()
        self.addCleanup(self.resume_patch.stop)

    async def test_plain_start_still_sends_card(self):
        message = private_message("/start")
        with (
            patch.object(casino_bot, "maybe_send_site_login", AsyncMock(return_value=False)),
            patch.object(casino_bot, "_send_casino_card", AsyncMock(return_value=True)) as send_card,
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send_message,
        ):
            await casino_bot.start_handler(message)
        send_card.assert_awaited_once()
        send_message.assert_not_awaited()

    async def test_cauth_sends_open_button_then_card(self):
        message = private_message(f"/start cauth_{TOKEN}")
        client = SimpleNamespace(
            attach_web_login=AsyncMock(
                return_value={"url": "https://focuspay.org/login/telegram?ticket=ff&next=%2Fcasino"}
            )
        )
        with (
            patch.object(web_login, "get_focuspay_client", AsyncMock(return_value=client)),
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send_message,
            patch.object(casino_bot, "_send_casino_card", AsyncMock(return_value=True)) as send_card,
        ):
            await casino_bot.start_handler(message)
        send_message.assert_awaited()
        self.assertIn("FocusBet", send_message.await_args.args[1])
        markup = send_message.await_args.kwargs["reply_markup"]
        self.assertEqual(markup.keyboard[0][0].text, "Открыть казино")
        self.assertIn("/login/telegram", markup.keyboard[0][0].url)
        send_card.assert_awaited_once()
        client.attach_web_login.assert_awaited_once()
