"""Tests for buy payout chat notify client."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.buy_payout import format_paid_chat_message


class FormatPaidChatMessageBotTests(unittest.TestCase):
    def test_plain_url(self):
        text = format_paid_chat_message(
            {"order_id": "OP123", "direction": "buy", "crypto": "btc", "crypto_amount": 0.1},
            "https://mempool.space/tx/deadbeef12345678",
        )
        self.assertIn("https://mempool.space/tx/deadbeef12345678", text)
        self.assertIn("Выплачено", text)


class RunPaidNotificationsTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivers_chat_after_bot_notify(self):
        order = {"order_id": "OP123", "user_id": 1, "crypto": "ltc"}
        chat = AsyncMock(return_value=True)
        with patch(
            "services.buy_payout.notify_buyer_paid",
            new=AsyncMock(),
        ), patch(
            "services.buyer_payout_notify.deliver_buy_payout_to_client_chat",
            new=chat,
        ), patch(
            "services.order_ops_notify.notify_ops_order",
            new=AsyncMock(),
        ):
            from services.buy_payout import _run_paid_notifications

            await _run_paid_notifications(order, "https://example.com/tx")
        chat.assert_awaited_once_with(order, "https://example.com/tx")


if __name__ == "__main__":
    unittest.main()
