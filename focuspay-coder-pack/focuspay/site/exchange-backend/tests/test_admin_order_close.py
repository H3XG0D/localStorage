"""Гейты admin-закрытия AWAITING_CHECK (без БД)."""
from __future__ import annotations

import unittest
from pathlib import Path

from admin_order_close import (
    admin_awaiting_check_payout_error,
    admin_cancel_awaiting_check_error,
    cancel_user_telegram_text,
)


class AdminCancelGateTests(unittest.TestCase):
    def test_only_awaiting_check(self):
        self.assertIsNone(admin_cancel_awaiting_check_error("AWAITING_CHECK"))
        self.assertEqual(admin_cancel_awaiting_check_error("CANCELED"), "already_canceled")
        self.assertEqual(admin_cancel_awaiting_check_error("PAID"), "already_closed")
        self.assertEqual(admin_cancel_awaiting_check_error("COMPLETED"), "already_closed")
        self.assertEqual(admin_cancel_awaiting_check_error("PENDING"), "wrong_status")
        self.assertEqual(admin_cancel_awaiting_check_error("CREATED"), "wrong_status")

    def test_cancel_text_matches_operator(self):
        from routers.operator import _cancel_user_text

        text = cancel_user_telegram_text("ABC123", "хвост очереди")
        self.assertEqual(text, _cancel_user_text("ABC123", "хвост очереди"))
        self.assertIn("Заявка отменена", text)
        self.assertIn("ABC123", text)
        self.assertIn("хвост очереди", text)
        self.assertIn("пересоздайте", text)
        self.assertIn("@focus_operator", text)


class AdminPayoutGateTests(unittest.TestCase):
    def test_only_buy_awaiting_check(self):
        self.assertIsNone(admin_awaiting_check_payout_error("buy", "AWAITING_CHECK"))
        self.assertEqual(admin_awaiting_check_payout_error("sell", "AWAITING_CHECK"), "not_buy")
        self.assertEqual(admin_awaiting_check_payout_error("buy", "COMPLETED"), "wrong_status")
        self.assertEqual(admin_awaiting_check_payout_error("buy", "PAID"), "already_paid")
        self.assertEqual(admin_awaiting_check_payout_error("buy", "PENDING"), "wrong_status")

    def test_patch_still_blocks_buy_paid(self):
        src = Path(__file__).resolve().parents[1] / "routers" / "admin_orders.py"
        text = src.read_text(encoding="utf-8")
        self.assertIn("BUY-заявку нельзя пометить PAID вручную", text)
        self.assertIn("confirm_awaiting_check_buy_payout", text)
        self.assertIn("/orders/{order_id}/cancel", text)
        self.assertIn("_ORDERS_WITH_BUYER_SQL", text)
        payout_fn = text.split("async def confirm_awaiting_check_payout", 1)[1]
        payout_fn = payout_fn.split("async def ", 1)[0]
        self.assertIn("_ORDERS_WITH_BUYER_SQL", payout_fn)

    def test_bridge_import_error_is_unavailable(self):
        src = Path(__file__).resolve().parents[1] / "bot_status_bridge.py"
        text = src.read_text(encoding="utf-8")
        block = text.split("async def confirm_awaiting_check_buy_payout", 1)[1]
        block = block.split("async def ", 1)[0]
        self.assertIn("except ImportError", block)
        self.assertIn("bridge_unavailable", block)

    def test_bridge_exposes_payfast_settle_after_receipt(self):
        src = Path(__file__).resolve().parents[1] / "bot_status_bridge.py"
        text = src.read_text(encoding="utf-8")
        self.assertIn("async def try_complete_if_payfast_settled", text)
        order_src = Path(__file__).resolve().parents[1] / "order_service.py"
        self.assertIn(
            "try_complete_if_payfast_settled",
            order_src.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
