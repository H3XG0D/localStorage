"""Tests for ops notifications and buyer stats block."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from services.order_ops_notify import (
    _format_buyer_stats_block,
    _resolve_buyer_stats_sync,
    _trust_level,
    build_ops_keyboard,
    format_ops_message,
)


class TrustLevelTests(unittest.TestCase):
    def test_trust_boundaries(self):
        self.assertIn("Новый", _trust_level(0))
        self.assertIn("Начинающий", _trust_level(1))
        self.assertIn("Начинающий", _trust_level(3))
        self.assertIn("Постоянный", _trust_level(4))
        self.assertIn("Постоянный", _trust_level(9))
        self.assertIn("Доверенный", _trust_level(10))
        self.assertIn("Доверенный", _trust_level(19))
        self.assertIn("VIP", _trust_level(20))


class BuyerStatsBlockTests(unittest.TestCase):
    def test_format_ops_message_includes_buyer_block(self):
        order = {
            "order_id": "ORD-1",
            "direction": "buy",
            "status": "AWAITING_CHECK",
            "crypto": "btc",
            "fiat_amount": 15000,
            "crypto_amount": 0.001,
            "user_id": 123,
        }
        stats = {
            "paid_count": 5,
            "last_paid_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
            "total_volume_rub": 87500.0,
        }
        text = format_ops_message("awaiting_receipt", order, buyer_stats=stats)
        self.assertIn("Покупатель", text)
        self.assertIn("Сделок завершено", text)
        self.assertIn("87500", text.replace(" ", ""))
        self.assertIn("Постоянный", text)

    def test_format_buyer_stats_block_new_user(self):
        block = _format_buyer_stats_block(
            {"paid_count": 0, "last_paid_at": None, "total_volume_rub": 0}
        )
        self.assertIn("Новый", block)
        self.assertIn("—", block)


class ResolveBuyerStatsSyncTests(unittest.TestCase):
    def test_returns_provided_stats_without_db(self):
        stats = {"paid_count": 3, "last_paid_at": None, "total_volume_rub": 1000.0}
        order = {"user_id": 999}
        result = _resolve_buyer_stats_sync(order, stats)
        self.assertEqual(result, stats)


class BuyerProfileLinkTests(unittest.TestCase):
    def test_format_ops_message_includes_profile_link(self):
        order = {
            "order_id": "ORD-1",
            "direction": "buy",
            "status": "AWAITING_CHECK",
            "crypto": "ltc",
            "fiat_amount": 4800,
            "crypto_amount": 1.1,
            "user_id": 5180993642,
        }
        text = format_ops_message("awaiting_receipt", order, username="testuser")
        self.assertNotIn("tg://user?id=5180993642", text)
        self.assertIn("/ops/client/5180993642", text)
        self.assertIn("t.me/testuser", text)

    def test_build_ops_keyboard_includes_profile_button(self):
        kb = build_ops_keyboard("ORD-1", user_id=5180993642)
        flat = [btn for row in kb["inline_keyboard"] for btn in row]
        tg_btn = next(b for b in flat if b.get("text") == "💬 Telegram")
        profile_btn = next(b for b in flat if b.get("text") == "👤 Профиль клиента")
        self.assertEqual(tg_btn["url"], "tg://user?id=5180993642")
        self.assertIn("/ops/client/5180993642", profile_btn["url"])


if __name__ == "__main__":
    unittest.main()
