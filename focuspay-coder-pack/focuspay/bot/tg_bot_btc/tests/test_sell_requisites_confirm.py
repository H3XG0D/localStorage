"""SELL: заявка не должна «пропадать» из‑за docker-URL на кнопке Telegram."""
from __future__ import annotations

import os
import time
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import InlineKeyboardMarkup

from handlers.exchange_flow import (
    _payin_plan_keyboard,
    _rates_keyboard,
    exchange_enter_requisites,
    sell_created_keyboard,
)
from services.payin_resolver import PayinPlan
from services.rates_api import CACHE


def _sell_update():
    user = SimpleNamespace(id=424242, username="buyer")
    msg = SimpleNamespace(
        text="+79999999999 сбербанк",
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(message=msg, effective_user=user, effective_chat=msg), msg


class SellCreatedKeyboardTests(unittest.TestCase):
    def test_staging_gateway_omits_url_button(self):
        with patch.dict(os.environ, {"PUBLIC_SITE_URL": "http://gateway:8080"}):
            self.assertIsNone(sell_created_keyboard())

    def test_public_https_keeps_url_button(self):
        with patch.dict(os.environ, {"PUBLIC_SITE_URL": "https://focuspay.org"}):
            kb = sell_created_keyboard()
            self.assertIsInstance(kb, InlineKeyboardMarkup)
            self.assertEqual(kb.inline_keyboard[0][0].url, "https://focuspay.org/?chat=1")


class PayinAndRatesKeyboardTests(unittest.TestCase):
    def test_payin_operator_keyboard_keeps_callbacks_without_site_url(self):
        with patch.dict(os.environ, {"PUBLIC_SITE_URL": "http://gateway:8080"}):
            kb = _payin_plan_keyboard(PayinPlan(mode="operator", pay_now=5000, message=""))
        data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        urls = [btn.url for row in kb.inline_keyboard for btn in row if btn.url]
        self.assertIn("payin:go:operator", data)
        self.assertIn("payin:cancel", data)
        self.assertEqual(urls, [])

    def test_rates_keyboard_keeps_refresh_without_site_url(self):
        with patch(
            "services.config_rates.PUBLIC_SITE_URL",
            "http://gateway:8080",
        ), patch.dict(os.environ, {"PUBLIC_SITE_URL": "http://gateway:8080"}):
            kb = _rates_keyboard()
        data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        urls = [btn.url for row in kb.inline_keyboard for btn in row if btn.url]
        self.assertEqual(data, ["refresh_rates"])
        self.assertEqual(urls, [])


class SellRequisitesConfirmTests(unittest.IsolatedAsyncioTestCase):
    async def test_sell_order_confirms_when_site_url_is_internal(self):
        update, msg = _sell_update()
        context = SimpleNamespace(
            user_data={
                "step": "awaiting_requisites",
                "crypto": "btc",
                "direction": "sell",
                "crypto_amount": Decimal("0.001"),
                "fiat_amount": Decimal("5900"),
                "effective_rate": Decimal("5900000"),
                "fsm_started_at": time.time(),
            },
            bot=SimpleNamespace(),
        )
        CACHE["btc"] = {"price": 8_000_000.0}
        created = {
            "promo_applied": False,
            "promo_code": None,
            "promo_bonus_percent": None,
            "promo_bonus_fixed_rub": None,
            "crypto_amount": 0.001,
            "fiat_amount": 5900.0,
        }

        with (
            patch.dict(os.environ, {"PUBLIC_SITE_URL": "http://gateway:8080"}),
            patch("handlers.exchange_flow.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch("handlers.exchange_flow.load_config", return_value=SimpleNamespace()),
            patch(
                "handlers.exchange_flow.count_orders_by_user_in_last_minutes",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "handlers.exchange_flow._block_requisites_if_no_shift",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "handlers.exchange_flow.create_order_with_promo",
                new=AsyncMock(return_value=created),
            ) as create_order,
            patch("services.db.get_order", new=AsyncMock(return_value={"order_id": "24523709"})),
            patch(
                "services.order_ops_notify.notify_ops_order",
                new=AsyncMock(),
            ) as notify,
            patch("services.commission.commission_label", return_value="5%"),
        ):
            await exchange_enter_requisites(update, context)

        create_order.assert_awaited()
        msg.reply_text.assert_awaited()
        kwargs = msg.reply_text.await_args.kwargs
        text = msg.reply_text.await_args.args[0]
        self.assertIn("передана оператору", text)
        self.assertNotIn("http://gateway", text)
        self.assertIsNone(kwargs.get("reply_markup"))
        self.assertEqual(context.user_data, {})
        notify.assert_awaited()
        self.assertNotIn("Нажмите «Совершить обмен»", text)

    async def test_sell_order_keeps_success_if_ops_notify_fails(self):
        update, msg = _sell_update()
        context = SimpleNamespace(
            user_data={
                "step": "awaiting_requisites",
                "crypto": "btc",
                "direction": "sell",
                "crypto_amount": Decimal("0.001"),
                "fiat_amount": Decimal("5900"),
                "effective_rate": Decimal("5900000"),
                "fsm_started_at": time.time(),
            },
            bot=SimpleNamespace(),
        )
        CACHE["btc"] = {"price": 8_000_000.0}
        created = {
            "promo_applied": False,
            "promo_code": None,
            "promo_bonus_percent": None,
            "promo_bonus_fixed_rub": None,
            "crypto_amount": 0.001,
            "fiat_amount": 5900.0,
        }

        with (
            patch.dict(os.environ, {"PUBLIC_SITE_URL": "https://focuspay.org"}),
            patch("handlers.exchange_flow.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch("handlers.exchange_flow.load_config", return_value=SimpleNamespace()),
            patch(
                "handlers.exchange_flow.count_orders_by_user_in_last_minutes",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "handlers.exchange_flow._block_requisites_if_no_shift",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "handlers.exchange_flow.create_order_with_promo",
                new=AsyncMock(return_value=created),
            ),
            patch("services.db.get_order", new=AsyncMock(return_value={"order_id": "1"})),
            patch(
                "services.order_ops_notify.notify_ops_order",
                new=AsyncMock(side_effect=RuntimeError("ops down")),
            ),
            patch("services.commission.commission_label", return_value="5%"),
        ):
            await exchange_enter_requisites(update, context)

        text = msg.reply_text.await_args.args[0]
        self.assertIn("передана оператору", text)
        self.assertEqual(context.user_data, {})
