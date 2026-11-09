"""Opt-in DMs for new blackjack tables; group invitation is skipped."""
from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import AsyncMock

from casino_open_alerts import (
    OPEN_ALERT_EVENT,
    enqueue_open_table_alerts,
    open_table_alert_text,
    publishes_web_group_invitation,
)


class OpenAlertTextTests(unittest.TestCase):
    def test_blackjack_mentions_stake_and_seats(self):
        text = open_table_alert_text(game_type="blackjack", stake_rub=Decimal("100.00"), seats=4)
        self.assertIn("Блэкджек", text)
        self.assertIn("100.00", text)
        self.assertIn("4 мест", text)
        self.assertIn("<b>", text)

    def test_group_invite_skipped_only_for_blackjack(self):
        self.assertFalse(publishes_web_group_invitation("blackjack"))
        self.assertTrue(publishes_web_group_invitation("baccara"))
        self.assertTrue(publishes_web_group_invitation("pvp_dice"))


class OpenAlertEnqueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_non_blackjack(self):
        conn = AsyncMock()
        count = await enqueue_open_table_alerts(
            conn, game_id="web-1", game_type="pvp_dice", creator_id=1, stake_rub=50, seats=2
        )
        self.assertEqual(count, 0)
        conn.fetch.assert_not_awaited()

    async def test_skips_when_nobody_opted_in(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        count = await enqueue_open_table_alerts(
            conn, game_id="web-bj", game_type="blackjack", creator_id=9, stake_rub=100, seats=4
        )
        self.assertEqual(count, 0)
        conn.execute.assert_not_awaited()

    async def test_inserts_dm_for_opted_in_telegram_user(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[{"user_id": 940002}])
        conn.execute = AsyncMock(return_value="INSERT 0 1")
        count = await enqueue_open_table_alerts(
            conn,
            game_id="web-bj",
            game_type="blackjack",
            creator_id=1,
            stake_rub=Decimal("50"),
            seats=3,
            href="/casino/tables/web-bj",
        )
        self.assertEqual(count, 1)
        args = conn.execute.await_args.args
        self.assertIn("casino_notification_outbox", args[0])
        self.assertEqual(args[2], OPEN_ALERT_EVENT)
        self.assertEqual(args[3], "web-bj")
        self.assertEqual(args[4], 940002)
        self.assertIn("open_table", args[1])
        self.assertIn("940002", args[5])
        self.assertIn("/casino/tables/web-bj", args[5])
        self.assertIn("chat_id", args[5])
