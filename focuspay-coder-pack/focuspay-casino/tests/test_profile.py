import importlib
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules


with TelebotModules("bot", "games.pvp", "games.baccara", "games.blackjack", "games.table_wizard", "games.v2_tables", "games.v2_runtime", "games.fairness", "games.roulette_table", "games.jackpot"):
    casino_bot = importlib.import_module("bot")


class ProfileHandlersTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_in_private_chat_sends_png_card(self):
        message = SimpleNamespace(
            chat=SimpleNamespace(id=77, type="private"),
            from_user=SimpleNamespace(id=77, first_name="Анна", username="anna"),
        )

        with (
            patch.object(casino_bot, "_send_profile_card", AsyncMock()) as send_card,
            patch.object(casino_bot, "_profile_keyboard", return_value="keyboard"),
        ):
            await casino_bot.profile_handler(message)

        send_card.assert_awaited_once_with(77, 77, message.from_user, "keyboard")

    async def test_profile_in_group_does_not_load_profile(self):
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100123, type="group"),
            from_user=SimpleNamespace(id=77),
        )

        with (
            patch.object(casino_bot, "_send_profile_card", AsyncMock()) as send_card,
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send_message,
        ):
            await casino_bot.profile_handler(message)

        send_card.assert_not_awaited()
        self.assertIn("только в личке", send_message.await_args.args[1])

    async def test_profile_refresh_replaces_private_card(self):
        call = SimpleNamespace(
            id="profile-refresh",
            from_user=SimpleNamespace(id=77, first_name="Анна", username="anna"),
            message=SimpleNamespace(
                chat=SimpleNamespace(id=77, type="private"),
                message_id=123,
            ),
        )
        photo = BytesIO(b"png")

        with (
            patch.object(casino_bot, "_load_profile_data", AsyncMock(return_value={})) as load_profile,
            patch.object(casino_bot, "_render_profile_card", AsyncMock(return_value=photo)) as render_card,
            patch.object(casino_bot, "_profile_keyboard", return_value="keyboard"),
            patch.object(casino_bot.bot, "edit_message_media", AsyncMock()) as edit_media,
            patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()) as answer_callback,
        ):
            await casino_bot.profile_refresh_cb(call)

        load_profile.assert_awaited_once_with(77)
        render_card.assert_awaited_once_with(77, {}, call.from_user)
        edit_media.assert_awaited_once_with(photo, 77, 123, reply_markup="keyboard")
        answer_callback.assert_awaited_once_with("profile-refresh", "Профиль обновлён")

    async def test_avatar_failure_uses_profile_card_fallback(self):
        client = SimpleNamespace(get_profile_avatar=AsyncMock(side_effect=RuntimeError("unavailable")))
        profile = {
            "identity": {"first_name": "Анна", "username": "anna"},
            "available_rub": "10",
            "current_week": {"wager_rub": "0", "loss_rub": "0", "tier": "5", "progress": {}},
            "wagering": {"remaining_rub": "0"},
        }

        with (
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
            patch("casino_profile_card.render_profile_card", return_value=b"PNG") as render_card,
        ):
            photo = await casino_bot._render_profile_card(77, profile, SimpleNamespace(first_name="Анна", username="anna"))

        self.assertEqual(photo.getvalue(), b"PNG")
        self.assertIsNone(render_card.call_args.kwargs["avatar_bytes"])

    def test_profile_card_prefixes_clan_tag(self):
        player = casino_bot._profile_card_player(
            {
                "identity": {"first_name": "Анна", "username": "anna"},
                "clan": {"tag": "ACE", "name": "Aces", "role": "owner"},
                "available_rub": "10",
                "current_week": {},
                "wagering": {"remaining_rub": "0"},
            },
            SimpleNamespace(first_name="Анна", username="anna"),
        )
        self.assertEqual(player["name"], "[ACE] Анна")

    async def test_balance_in_group_does_not_post_amount(self):
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100111, type="supergroup"),
            from_user=SimpleNamespace(id=77, username="anna"),
        )
        client = SimpleNamespace(get_balance=AsyncMock(return_value=5000.0))

        with (
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
            patch.object(casino_bot, "send_ephemeral", AsyncMock()) as ephemeral,
            patch.object(casino_bot, "try_delete_user_message", AsyncMock()) as delete_msg,
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send_message,
        ):
            await casino_bot.balance_handler(message)

        client.get_balance.assert_not_awaited()
        send_message.assert_not_awaited()
        ephemeral.assert_awaited_once()
        self.assertIn("личке", ephemeral.await_args.args[2])
        delete_msg.assert_awaited_once()

    async def test_send_profile_card_falls_back_to_text_when_chrome_fails(self):
        profile = {
            "identity": {"first_name": "Анна", "username": "anna"},
            "available_rub": "5000.00",
            "current_week": {"wager_rub": "0", "loss_rub": "0", "tier": "5", "progress": {}},
            "wagering": {"remaining_rub": "0"},
        }
        user = SimpleNamespace(first_name="Анна", username="anna")

        with (
            patch.object(casino_bot, "_load_profile_data", AsyncMock(return_value=profile)),
            patch.object(casino_bot, "_render_profile_card", AsyncMock(side_effect=RuntimeError("chrome"))),
            patch.object(casino_bot.bot, "send_photo", AsyncMock()) as send_photo,
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send_message,
        ):
            await casino_bot._send_profile_card(77, 77, user, "keyboard")

        send_photo.assert_not_awaited()
        send_message.assert_awaited_once()
        self.assertIn("5000.00", send_message.await_args.args[1])
        self.assertEqual(send_message.await_args.kwargs["reply_markup"], "keyboard")


if __name__ == "__main__":
    unittest.main()
