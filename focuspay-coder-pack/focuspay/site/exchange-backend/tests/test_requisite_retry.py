"""Черновик повторного запроса: окно 30 минут, кулдаун 5, кошелёк только у своих заявок."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from payout_wallet_confirm import evaluate_wallet_decision
from requisite_retry import (
    COOLDOWN,
    WINDOW,
    client_message,
    decide_attempt,
    kept_expiry,
    snapshot_is_requisite_retry,
    wallet_coin_supported,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
OLD = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
TRON = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"


class WindowTests(unittest.TestCase):
    def test_new_draft_lasts_thirty_minutes(self):
        self.assertEqual(kept_expiry(None, NOW), NOW + WINDOW)
        self.assertEqual(WINDOW, timedelta(minutes=30))

    def test_repeat_does_not_extend_the_window(self):
        first = NOW + timedelta(minutes=10)
        self.assertEqual(kept_expiry(first, NOW + timedelta(minutes=6)), first)

    def test_expired_window_starts_over(self):
        old = NOW - timedelta(minutes=1)
        self.assertEqual(kept_expiry(old, NOW), NOW + WINDOW)


class CooldownTests(unittest.TestCase):
    def test_press_inside_five_minutes_waits(self):
        decision = decide_attempt(NOW + timedelta(minutes=2), NOW + WINDOW, NOW)
        self.assertFalse(decision["ok"])
        self.assertEqual(decision["reason"], "cooldown")
        self.assertGreater(decision["retry_after_sec"], 0)
        self.assertEqual(COOLDOWN, timedelta(minutes=5))

    def test_press_after_five_minutes_is_ready(self):
        decision = decide_attempt(NOW + COOLDOWN, NOW + WINDOW, NOW)
        self.assertTrue(decision["ok"])
        self.assertEqual(decision["reason"], "ready")

    def test_expired_draft_is_not_pressed(self):
        decision = decide_attempt(NOW + WINDOW, NOW + WINDOW, NOW)
        self.assertEqual(decision["reason"], "expired")
        self.assertIn("вышло", client_message("expired"))


class WalletFlagTests(unittest.TestCase):
    def test_snapshot_flag(self):
        self.assertTrue(snapshot_is_requisite_retry({"requisite_retry": True}))
        self.assertTrue(snapshot_is_requisite_retry('{"requisite_retry": true}'))
        self.assertFalse(snapshot_is_requisite_retry({}))
        self.assertFalse(snapshot_is_requisite_retry(None))

    def test_usdt_asks_only_for_draft_orders(self):
        self.assertTrue(wallet_coin_supported("btc", requisite_retry=False))
        self.assertFalse(wallet_coin_supported("usdt", requisite_retry=False))
        self.assertTrue(wallet_coin_supported("usdt", requisite_retry=True))
        self.assertTrue(wallet_coin_supported("trx", requisite_retry=True))

    def test_plain_usdt_payout_does_not_ask(self):
        decision = evaluate_wallet_decision(
            {
                "order_id": "1",
                "user_id": 5,
                "direction": "buy",
                "status": "COMPLETED",
                "crypto": "USDT_TRC20",
                "payout_tx_hash": None,
                "payment_snapshot": {},
            },
            {"status": "pending", "address": TRON},
            user_id=5,
            action="confirm",
            address=None,
        )
        self.assertEqual(decision["detail"], "unsupported_coin")

    def test_draft_usdt_can_confirm_wallet(self):
        decision = evaluate_wallet_decision(
            {
                "order_id": "1",
                "user_id": 5,
                "direction": "buy",
                "status": "COMPLETED",
                "crypto": "USDT_TRC20",
                "payout_tx_hash": None,
                "payment_snapshot": {"requisite_retry": True},
            },
            {"status": "pending", "address": TRON},
            user_id=5,
            action="confirm",
            address=None,
        )
        self.assertEqual(decision["http"], 200)
        self.assertEqual(decision["status"], "confirmed")
        self.assertEqual(decision["address"], TRON)

    def test_draft_can_replace_usdt_address(self):
        decision = evaluate_wallet_decision(
            {
                "order_id": "1",
                "user_id": 5,
                "direction": "buy",
                "status": "COMPLETED",
                "crypto": "USDT_TRC20",
                "payout_tx_hash": None,
                "payment_snapshot": {"requisite_retry": True},
            },
            {"status": "pending", "address": TRON},
            user_id=5,
            action="replace",
            address="TXYZusdtrecentwalletXXXXXXXXXXXX",
        )
        self.assertEqual(decision["http"], 400)

    def test_btc_without_flag_still_confirms(self):
        decision = evaluate_wallet_decision(
            {
                "order_id": "777",
                "user_id": 5,
                "direction": "buy",
                "status": "COMPLETED",
                "crypto": "btc",
                "payout_tx_hash": None,
            },
            {"status": "pending", "address": OLD},
            user_id=5,
            action="confirm",
            address=None,
        )
        self.assertEqual(decision["http"], 200)
        self.assertEqual(decision["address"], OLD)


if __name__ == "__main__":
    unittest.main()
