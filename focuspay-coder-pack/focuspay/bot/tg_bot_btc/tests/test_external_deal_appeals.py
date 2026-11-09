"""Тесты поиска external deal по ref appeals."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from services.external_deal_ops_notify import (
    format_external_deal_ops_notify,
    notify_external_deal_ops,
)

_DEAL = {
    "id": 2,
    "client_pays_rub": 1650,
    "exchanger_name": "NCH",
    "account_username": "nch_user",
    "payment_snapshot": {"merchant_uuid": "pf-uuid-99"},
    "client_is_new": True,
    "exchanger_id": 5,
}


class ExternalDealOpsNotifyBotTests(unittest.TestCase):
    def test_format_video_requested(self):
        text = format_external_deal_ops_notify("video_requested", _DEAL)
        self.assertIn("сделка #2", text)
        self.assertIn("EXT-2", text)
        self.assertNotIn("pf-uuid-99", text)
        self.assertIn("@nch_user", text)
        self.assertIn("видео", text)
        self.assertIn("Клиент: новый", text)

    def test_repeat_client_label(self):
        deal = {**_DEAL, "client_is_new": False}
        text = format_external_deal_ops_notify("success_receipt", deal)
        self.assertIn("Клиент: повторный", text)

    def test_stats_block_in_format(self):
        stats = {
            "confirmed_count": 7,
            "total_turnover_rub": 42000.0,
            "last_confirmed_at": None,
        }
        text = format_external_deal_ops_notify(
            "video_requested", _DEAL, ops_stats=stats
        )
        self.assertIn("Сделок: <b>7</b>", text)
        self.assertIn("42 000 ₽", text)


class ExternalDealOpsNotifyRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_to_external_group(self):
        bot = AsyncMock()
        with patch(
            "services.config_rates.external_deals_group_id",
            return_value=-100111,
        ), patch(
            "services.config_rates.ops_group_id",
            return_value=-100222,
        ):
            await notify_external_deal_ops("video_requested", _DEAL, bot=bot)

        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], -100111)
        self.assertIn("Клиент: новый", kwargs["text"])

    async def test_fallback_to_ops_group(self):
        bot = AsyncMock()
        with patch(
            "services.config_rates.external_deals_group_id",
            return_value=0,
        ), patch(
            "services.config_rates.ops_group_id",
            return_value=-100222,
        ):
            await notify_external_deal_ops("success_receipt", _DEAL, bot=bot)

        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], -100222)

    async def test_skips_when_no_group(self):
        bot = AsyncMock()
        with patch(
            "services.config_rates.external_deals_group_id",
            return_value=0,
        ), patch(
            "services.config_rates.ops_group_id",
            return_value=0,
        ):
            await notify_external_deal_ops("video_requested", _DEAL, bot=bot)

        bot.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
