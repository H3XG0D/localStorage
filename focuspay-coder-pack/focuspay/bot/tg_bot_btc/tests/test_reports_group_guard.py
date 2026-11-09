"""Owner report commands stay silent outside the reports group."""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.reports_group_guard import reply_wrong_reports_group


def _update(chat_id: int, user_id: int, *, title: str = "FOCUS PAY"):
    msg = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(
        message=msg,
        effective_message=msg,
        effective_user=SimpleNamespace(id=user_id, username="focuspayadmin"),
        effective_chat=SimpleNamespace(id=chat_id, title=title, type="supergroup"),
    ), msg


class ReportsGroupGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_in_public_group_gets_no_reply(self):
        update, msg = _update(chat_id=-100111, user_id=111)
        with (
            patch("services.reports_group_guard.config_rates.is_reports_group_chat", return_value=False),
            patch("services.reports_group_guard.config_rates.TELEGRAM_ADMIN_IDS", [111]),
        ):
            swallowed = await reply_wrong_reports_group(update)
        self.assertTrue(swallowed)
        msg.reply_text.assert_not_awaited()

    async def test_non_admin_in_public_group_is_also_swallowed(self):
        update, msg = _update(chat_id=-100111, user_id=8760743763)
        with (
            patch("services.reports_group_guard.config_rates.is_reports_group_chat", return_value=False),
            patch("services.reports_group_guard.config_rates.TELEGRAM_ADMIN_IDS", [111]),
        ):
            swallowed = await reply_wrong_reports_group(update)
        self.assertTrue(swallowed)
        msg.reply_text.assert_not_awaited()

    async def test_reports_group_is_not_swallowed(self):
        update, msg = _update(chat_id=-5272708942, user_id=111)
        with (
            patch("services.reports_group_guard.config_rates.is_reports_group_chat", return_value=True),
            patch("services.reports_group_guard.config_rates.TELEGRAM_ADMIN_IDS", [111]),
        ):
            swallowed = await reply_wrong_reports_group(update)
        self.assertFalse(swallowed)
        msg.reply_text.assert_not_awaited()


class ReportsChatidSourceTests(unittest.TestCase):
    def test_chatid_does_not_reply_to_non_admins(self):
        src = Path(__file__).resolve().parents[1].joinpath("handlers/reports_chatid.py").read_text()
        self.assertIn("if user_id not in config_rates.TELEGRAM_ADMIN_IDS:", src)
        self.assertNotIn("Только для администраторов", src)


if __name__ == "__main__":
    unittest.main()
