"""Кнопки подтверждения кошелька и перехват адреса только в ожидании."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram.ext import ApplicationHandlerStop

from handlers.payout_wallet_confirm import (
    AWAITING_KEY,
    parse_payout_wallet_callback,
    payout_wallet_text_handler,
    wallet_text_should_stop,
)


class ParseTests(unittest.TestCase):
    def test_ok_and_new(self):
        self.assertEqual(parse_payout_wallet_callback("pw:ok:777"), ("ok", "777"))
        self.assertEqual(parse_payout_wallet_callback("pw:new:777"), ("new", "777"))

    def test_junk_is_ignored(self):
        self.assertIsNone(parse_payout_wallet_callback("pw:ok:"))
        self.assertIsNone(parse_payout_wallet_callback("pay:777"))
        self.assertIsNone(parse_payout_wallet_callback("pw:no:777"))


class CaptureTests(unittest.TestCase):
    def test_text_is_captured_only_while_waiting(self):
        self.assertFalse(wallet_text_should_stop({}))
        self.assertFalse(wallet_text_should_stop(None))
        self.assertTrue(wallet_text_should_stop({AWAITING_KEY: "777"}))

    def test_handler_lets_other_text_through(self):
        update = SimpleNamespace(message=SimpleNamespace(text="5000"), effective_user=SimpleNamespace(id=5))
        context = SimpleNamespace(user_data={})
        asyncio.run(payout_wallet_text_handler(update, context))

    def test_handler_stops_exchange_while_waiting(self):
        reply = AsyncMock()
        update = SimpleNamespace(
            message=SimpleNamespace(text="not-a-wallet", reply_text=reply),
            effective_user=SimpleNamespace(id=5),
        )
        context = SimpleNamespace(user_data={AWAITING_KEY: "777"})
        with patch(
            "handlers.payout_wallet_confirm.post_wallet_decision",
            new=AsyncMock(return_value=(400, {"detail": "Неверный формат адреса Bitcoin"})),
        ):
            with self.assertRaises(ApplicationHandlerStop):
                asyncio.run(payout_wallet_text_handler(update, context))
        self.assertEqual(context.user_data[AWAITING_KEY], "777")
        reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
