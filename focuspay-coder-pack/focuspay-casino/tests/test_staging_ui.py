import importlib
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules


with TelebotModules("bot", "casino_menu", "games.pvp", "games.baccara", "games.blackjack", "games.table_wizard", "games.v2_tables", "games.v2_runtime", "games.fairness", "games.roulette_table", "games.jackpot", "web_login"):
    casino_bot = importlib.import_module("bot")
    casino_menu = importlib.import_module("casino_menu")


def private_message() -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(id=77, type="private"),
        from_user=SimpleNamespace(id=77, username="player", first_name="Player"),
    )


class StagingStartTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = SimpleNamespace(v2_recovery_or_outbox=AsyncMock(return_value={"success": True, "resumed": 0}))
        self.client_patch = patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=self.client))
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)

    async def test_start_sends_single_personal_card(self):
        """В личке ровно один баннер: карточка, без второго текстового сообщения."""
        message = private_message()
        with (
            patch.object(casino_bot, "_send_casino_card", AsyncMock(return_value=True)) as send_card,
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send_message,
        ):
            await casino_bot.start_handler(message)

        send_card.assert_awaited_once()
        self.assertEqual(send_card.await_args.args[0], 77)
        self.assertEqual(send_card.await_args.args[1], 77)
        send_message.assert_not_awaited()
        self.client.v2_recovery_or_outbox.assert_awaited_once_with(
            "/notifications/resume", telegram_id=77, limit=10,
        )

    async def test_start_card_carries_reply_menu(self):
        """Карточка несёт reply-меню, иначе постоянные кнопки не появятся."""
        message = private_message()
        with (
            patch.object(casino_bot, "_send_casino_card", AsyncMock(return_value=True)) as send_card,
            patch.object(casino_bot.bot, "send_message", AsyncMock()),
        ):
            await casino_bot.start_handler(message)

        markup = send_card.await_args.args[3]
        labels = [button.text for row in markup.keyboard for button in row]
        self.assertIn(casino_menu.MENU_CREATE_GAME, labels)
        self.assertIn(casino_menu.MENU_FIND_GAME, labels)
        self.assertIn(casino_menu.MENU_BALANCE, labels)
        self.assertIn(casino_menu.MENU_DEPOSIT, labels)
        self.assertNotIn(casino_menu.MENU_TEAM, labels)

    async def test_start_falls_back_to_text_when_card_is_unavailable(self):
        message = private_message()
        with (
            patch.object(casino_bot, "_send_casino_card", AsyncMock(return_value=False)),
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send_message,
        ):
            await casino_bot.start_handler(message)

        self.assertIn("FocusCasino", send_message.await_args.args[1])
        self.assertNotIn("Ваш ID", send_message.await_args.args[1])
        markup = send_message.await_args.kwargs["reply_markup"]
        labels = [button.text for row in markup.keyboard for button in row]
        self.assertIn(casino_menu.MENU_CREATE_GAME, labels)

    async def test_start_falls_back_when_card_send_is_rejected(self):
        """If Telegram rejects the photo (e.g. HTTP Web App URL), /start still replies."""
        message = private_message()
        with (
            patch.object(casino_bot, "_load_profile_data", AsyncMock(return_value={})),
            patch.object(
                casino_bot, "_render_profile_card", AsyncMock(return_value=BytesIO(b"png"))
            ),
            patch.object(
                casino_bot.bot,
                "send_photo",
                AsyncMock(side_effect=RuntimeError("WEBAPP_URL_INVALID")),
            ),
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send_message,
        ):
            await casino_bot.start_handler(message)

        send_message.assert_awaited_once()
        self.assertIn("FocusCasino", send_message.await_args.args[1])

    async def test_start_in_group_never_loads_personal_card(self):
        message = private_message()
        message.chat = SimpleNamespace(id=-100, type="group")
        with (
            patch.object(casino_bot, "_send_casino_card", AsyncMock()) as send_card,
            patch.object(casino_bot.bot, "send_message", AsyncMock()),
        ):
            await casino_bot.start_handler(message)
        send_card.assert_not_awaited()


class MiniAppMenuTests(unittest.TestCase):
    def test_http_miniapp_url_is_not_attached_as_web_app(self):
        """Telegram 400s HTTP Web App URLs; attaching one made /start silent."""
        with patch.object(
            casino_bot.config, "CASINO_MINIAPP_URL", "http://127.0.0.1:18081/casino/tg"
        ):
            reply = casino_menu.main_menu_keyboard()
            inline = casino_bot._staging_menu_keyboard()
        self.assertEqual(_web_app_urls(reply), [])
        self.assertEqual(_web_app_urls(inline), [])

    def test_https_miniapp_url_keeps_web_app_button(self):
        url = "https://example.test/casino/tg"
        with patch.object(casino_bot.config, "CASINO_MINIAPP_URL", url):
            reply = casino_menu.main_menu_keyboard()
            inline = casino_bot._staging_menu_keyboard()
        self.assertEqual(_web_app_urls(reply), [url])
        self.assertEqual(_web_app_urls(inline), [url])


def _web_app_urls(markup) -> list[str]:
    return [
        button.web_app.url
        for row in markup.keyboard
        for button in row
        if getattr(button, "web_app", None)
    ]


def private_call(data: str, call_id: str = "cb") -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        data=data,
        from_user=SimpleNamespace(id=77, username="player", first_name="Player"),
        message=SimpleNamespace(chat=SimpleNamespace(id=77, type="private")),
    )


class StagingMenuTests(unittest.IsolatedAsyncioTestCase):
    async def test_menu_deposit_offers_amount_buttons(self):
        """Пополнение идёт кнопками: слеш-команду пользователю больше не показываем."""
        call = private_call("menu:deposit", "deposit")
        with (
            patch.object(casino_bot.config, "DEPOSITS_ENABLED", True),
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send_message,
            patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()),
        ):
            await casino_bot.staging_menu_callback(call)

        text = send_message.await_args.args[1]
        self.assertIn("Пополнение баланса", text)
        self.assertNotIn("/deposit", text)
        callbacks = [
            button.callback_data
            for row in send_message.await_args.kwargs["reply_markup"].keyboard
            for button in row
        ]
        self.assertTrue(any(cb.startswith("depamt:") for cb in callbacks))

    async def test_menu_deposit_soon_when_disabled(self):
        call = private_call("menu:deposit", "deposit")
        with (
            patch.object(casino_bot.config, "DEPOSITS_ENABLED", False),
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send_message,
            patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()),
        ):
            await casino_bot.staging_menu_callback(call)

        text = send_message.await_args.args[1]
        self.assertIn("Пополнение скоро", text)
        markup = send_message.await_args.kwargs.get("reply_markup")
        self.assertTrue(markup is None or getattr(markup, "keyboard", None) in (None, []))

    async def test_menu_games_opens_real_lobby(self):
        """«Активные игры» открывают durable V2-лобби."""
        call = private_call("menu:lobby", "lobby")
        with (
            patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()),
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=object())),
            patch.object(casino_bot, "send_v2_lobby", AsyncMock()) as lobby,
        ):
            await casino_bot.staging_menu_callback(call)

        lobby.assert_awaited_once()
        self.assertEqual(lobby.await_args.args[2:], (77, 77))

    async def test_legacy_games_callback_still_opens_lobby(self):
        """Старые сообщения с callback_data=menu:games не должны ломаться."""
        call = private_call("menu:games", "games")
        with (
            patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()),
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=object())),
            patch.object(casino_bot, "send_v2_lobby", AsyncMock()) as lobby,
        ):
            await casino_bot.staging_menu_callback(call)

        lobby.assert_awaited_once()

    async def test_menu_my_games_lists_own_v2_tables(self):
        call = private_call("menu:mygames", "mygames")
        with (
            patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()),
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=object())),
            patch.object(casino_bot, "send_v2_my_tables", AsyncMock()) as my_tables,
        ):
            await casino_bot.staging_menu_callback(call)

        my_tables.assert_awaited_once()
        self.assertEqual(my_tables.await_args.args[2:], (77, 77))

    async def test_menu_withdraw_points_to_main_bot(self):
        """У казино нет payout-API, поэтому вывод адресуем в основной бот."""
        call = private_call("menu:withdraw", "withdraw")
        with (
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send_message,
            patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()),
        ):
            await casino_bot.staging_menu_callback(call)

        text = send_message.await_args.args[1]
        self.assertIn("Вывод", text)
        self.assertIn("отыгрыш", text.lower())

    async def test_menu_rejects_personal_actions_in_group(self):
        call = SimpleNamespace(
            id="group",
            data="menu:profile",
            from_user=SimpleNamespace(id=77),
            message=SimpleNamespace(chat=SimpleNamespace(id=-100, type="group")),
        )
        with patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()) as answer:
            await casino_bot.staging_menu_callback(call)

        answer.assert_awaited_once_with("group", "Откройте личный чат с ботом", show_alert=True)


if __name__ == "__main__":
    unittest.main()
