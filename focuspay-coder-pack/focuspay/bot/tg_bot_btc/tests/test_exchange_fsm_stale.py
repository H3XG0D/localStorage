"""Тесты: «сессия устарела» vs подсказка при повторном вводе."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.exchange_flow import (
    exchange_input_is_stale,
    exchange_repeat_input_reply,
)


class ExchangeStaleLogicTests(unittest.TestCase):
    def test_stale_when_no_step(self):
        self.assertTrue(exchange_input_is_stale(None))
        self.assertTrue(exchange_input_is_stale(""))

    def test_not_stale_during_flow(self):
        self.assertFalse(exchange_input_is_stale("choose_payment_method"))
        self.assertFalse(exchange_input_is_stale("confirm_buy_amount"))

    def test_repeat_amount_at_payment_step_is_not_stale(self):
        self.assertFalse(
            exchange_input_is_stale("choose_payment_method"),
        )
        self.assertFalse(
            exchange_input_is_stale("confirm_buy_amount"),
        )


class ExchangeRepeatInputTests(unittest.IsolatedAsyncioTestCase):
    async def test_amount_at_payment_method_gets_hint(self):
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"step": "choose_payment_method"}

        handled = await exchange_repeat_input_reply(update, context, kind="amount")
        self.assertTrue(handled)
        update.message.reply_text.assert_awaited_once()
        self.assertIn("Карта", update.message.reply_text.await_args.args[0])

    async def test_payment_at_requisites_gets_hint(self):
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"step": "awaiting_requisites"}

        handled = await exchange_repeat_input_reply(update, context, kind="payment")
        self.assertTrue(handled)
        self.assertIn("кошел", update.message.reply_text.await_args.args[0].lower())

    async def test_amount_at_confirm_gets_hint(self):
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"step": "confirm_buy_amount"}

        handled = await exchange_repeat_input_reply(update, context, kind="amount")
        self.assertTrue(handled)
        self.assertIn("устраивает", update.message.reply_text.await_args.args[0].lower())

    async def test_payment_at_confirm_gets_hint(self):
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"step": "confirm_buy_amount"}

        handled = await exchange_repeat_input_reply(update, context, kind="payment")
        self.assertTrue(handled)
        self.assertIn("устраивает", update.message.reply_text.await_args.args[0].lower())

    async def test_unknown_step_returns_false(self):
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"step": None}

        handled = await exchange_repeat_input_reply(update, context, kind="amount")
        self.assertFalse(handled)
