"""Tests for payout_pending_store."""
from __future__ import annotations

import time
import unittest

from services.payout_pending_store import (
    _TTL_SEC,
    clear_pending,
    lookup_pending,
    save_pending,
)


class PayoutPendingStoreTests(unittest.TestCase):
    def setUp(self):
        self.bot_data: dict = {}

    def test_lookup_by_reply_to_message_id(self):
        save_pending(
            self.bot_data,
            kind="buy_payout",
            chat_id=-100123,
            user_id=111,
            prompt_message_id=501,
            card_message_id=500,
            payload={"order_id": "ABC123"},
        )
        hit = lookup_pending(
            self.bot_data,
            chat_id=-100123,
            user_id=999,
            reply_to_message_id=501,
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["order_id"], "ABC123")
        self.assertEqual(hit["kind"], "buy_payout")

    def test_lookup_by_user_fallback(self):
        save_pending(
            self.bot_data,
            kind="buy_payout",
            chat_id=-100123,
            user_id=111,
            prompt_message_id=501,
            card_message_id=500,
            payload={"order_id": "XYZ"},
        )
        hit = lookup_pending(
            self.bot_data,
            chat_id=-100123,
            user_id=111,
            reply_to_message_id=None,
        )
        self.assertEqual(hit["order_id"], "XYZ")

    def test_reply_takes_priority_over_other_user(self):
        save_pending(
            self.bot_data,
            kind="buy_payout",
            chat_id=-100123,
            user_id=111,
            prompt_message_id=501,
            card_message_id=500,
            payload={"order_id": "FROM_REPLY"},
        )
        save_pending(
            self.bot_data,
            kind="buy_payout",
            chat_id=-100123,
            user_id=222,
            prompt_message_id=601,
            card_message_id=600,
            payload={"order_id": "FROM_USER"},
        )
        hit = lookup_pending(
            self.bot_data,
            chat_id=-100123,
            user_id=222,
            reply_to_message_id=501,
        )
        self.assertEqual(hit["order_id"], "FROM_REPLY")

    def test_clear_pending(self):
        save_pending(
            self.bot_data,
            kind="refwd",
            chat_id=-100123,
            user_id=111,
            prompt_message_id=501,
            card_message_id=500,
            payload={"withdrawal_id": 7},
        )
        entry = lookup_pending(self.bot_data, chat_id=-100123, user_id=111)
        self.assertIsNotNone(entry)
        clear_pending(self.bot_data, entry)
        self.assertIsNone(
            lookup_pending(self.bot_data, chat_id=-100123, user_id=111)
        )

    def test_expired_entries_pruned(self):
        store = self.bot_data.setdefault("payout_pending_store", {})
        store["by_user"] = {
            "-100123:111": {
                "kind": "buy_payout",
                "chat_id": -100123,
                "user_id": 111,
                "ts": time.time() - _TTL_SEC - 1,
                "order_id": "OLD",
            }
        }
        store["by_prompt"] = {}
        hit = lookup_pending(self.bot_data, chat_id=-100123, user_id=111)
        self.assertIsNone(hit)


if __name__ == "__main__":
    unittest.main()
