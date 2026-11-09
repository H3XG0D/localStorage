"""Clan command formatting — no live Telegram."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.telebot_stub import TelebotModules


with TelebotModules("casino_teams"):
    from casino_teams import api_error_text, format_clan


class ClanFormatTests(unittest.TestCase):
    def test_clan_card_includes_tag_and_code_for_owner(self):
        text = format_clan(
            {
                "tag": "ACE",
                "name": "Aces",
                "wager_rub": 250,
                "member_count": 2,
                "max_members": 20,
                "invite_code": "ABCD1234",
                "members": [{"display_name": "Ivan", "role": "owner", "wager_rub": 250, "user_id": 1}],
            },
            with_code=True,
        )
        self.assertIn("[ACE]", text)
        self.assertIn("ABCD1234", text)
        self.assertIn("владелец", text)

    def test_api_error_reads_detail(self):
        exc = SimpleNamespace(response=SimpleNamespace(json=lambda: {"detail": "Кланы выключены"}))
        self.assertEqual(api_error_text(exc), "Кланы выключены")

    def test_api_error_reads_validation_list(self):
        exc = SimpleNamespace(
            response=SimpleNamespace(json=lambda: {"detail": [{"msg": "String should have at least 3 characters"}]})
        )
        self.assertEqual(api_error_text(exc), "String should have at least 3 characters")


class ClanCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_teamtop_lists_clans(self):
        with TelebotModules("casino_teams"):
            import importlib
            import casino_teams

            importlib.reload(casino_teams)
            bot = SimpleNamespace()
            handlers = []

            def message_handler(*args, **kwargs):
                def wrap(fn):
                    handlers.append((kwargs, fn))
                    return fn

                return wrap

            bot.message_handler = message_handler
            client = SimpleNamespace(get_clan_top=AsyncMock(return_value={"clans": [{"tag": "ACE", "name": "Aces", "wager_rub": 100}]}))
            casino_teams.register_team_handlers(bot, client)
            cmd = next(fn for kwargs, fn in handlers if "teamtop" in str(kwargs.get("commands")))
            sent = AsyncMock()
            bot.send_message = sent
            message = SimpleNamespace(
                chat=SimpleNamespace(id=7, type="private"),
                from_user=SimpleNamespace(id=7),
                text="/teamtop",
            )
            await cmd(message)
            self.assertIn("ACE", sent.await_args.args[1])
