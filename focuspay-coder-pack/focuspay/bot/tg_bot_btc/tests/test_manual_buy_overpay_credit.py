"""Регрессии начисления дополнительного баланса за переплату ручной BUY."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.buy_payout import format_paid_user_message
from services.db import _apply_paid_side_effects_in_tx
from services.user_cashback_db import credit_manual_buy_overpay_for_order


class ManualBuyOverpayCreditTests(unittest.IsolatedAsyncioTestCase):
    async def test_credits_overpay_with_deterministic_key(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"user_id": 10, "overpay_credit_rub": 160})
        conn.execute = AsyncMock()

        await credit_manual_buy_overpay_for_order("OP123", conn=conn)

        self.assertEqual(conn.execute.await_args.args[1:], (10, 160.0, "OP123:overpay", "Дополнительный баланс за переплату по заявке OP123"))
        self.assertIn("ON CONFLICT (order_id) DO NOTHING", conn.execute.await_args.args[0])

    async def test_skips_zero_credit(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"user_id": 10, "overpay_credit_rub": 0})
        conn.execute = AsyncMock()

        await credit_manual_buy_overpay_for_order("OP123", conn=conn)

        conn.execute.assert_not_called()

    async def test_credits_payin_rail_overpay(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"user_id": 10, "overpay_credit_rub": 100})
        conn.execute = AsyncMock()

        await credit_manual_buy_overpay_for_order("W4900", conn=conn)

        sql = conn.fetchrow.await_args.args[0]
        self.assertIn("payin_requisite_id IS NOT NULL", sql)
        self.assertEqual(
            conn.execute.await_args.args[1:],
            (10, 100.0, "W4900:overpay", "Дополнительный баланс за переплату по заявке W4900"),
        )

    async def test_holds_payin_credit_when_pdf_lacks_order_amount(self):
        """Round-up 3600→3990, в PDF суммы 3990 нет → 390 ₽ на баланс не идут, ставим hold."""
        conn = MagicMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "user_id": 10,
                "overpay_credit_rub": 390,
                "payin_requisite_id": 7,
                "payment_snapshot": {"receipt_pdf_meta": {"amount_present": False}},
            }
        )
        conn.execute = AsyncMock()

        await credit_manual_buy_overpay_for_order("W3990", conn=conn)

        self.assertEqual(conn.execute.await_count, 1)
        sql = conn.execute.await_args.args[0]
        self.assertIn("UPDATE orders", sql)
        self.assertNotIn("user_cashback_ledger", sql)
        self.assertIn("overpay_credit_hold", conn.execute.await_args.args[2])

    async def test_credits_payin_when_pdf_meta_unknown_or_amount_found(self):
        from services.user_cashback_db import overpay_credit_receipt_ok

        self.assertTrue(overpay_credit_receipt_ok(None))
        self.assertTrue(overpay_credit_receipt_ok({}))
        self.assertTrue(overpay_credit_receipt_ok({"receipt_pdf_meta": {"amount_present": None}}))
        self.assertTrue(overpay_credit_receipt_ok({"receipt_pdf_meta": {"amount_present": True}}))
        self.assertTrue(overpay_credit_receipt_ok('{"receipt_pdf_meta": {"amount_present": true}}'))
        self.assertFalse(overpay_credit_receipt_ok({"receipt_pdf_meta": {"amount_present": False}}))
        self.assertFalse(overpay_credit_receipt_ok('{"receipt_pdf_meta": {"amount_present": false}}'))

    async def test_manual_operator_credit_ignores_pdf_meta(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "user_id": 10,
                "overpay_credit_rub": 160,
                "payin_requisite_id": None,
                "payment_snapshot": {"receipt_pdf_meta": {"amount_present": False}},
            }
        )
        conn.execute = AsyncMock()

        await credit_manual_buy_overpay_for_order("OP123", conn=conn)

        self.assertIn("user_cashback_ledger", conn.execute.await_args.args[0])

    async def test_skips_order_that_is_not_manual_buy(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.execute = AsyncMock()

        await credit_manual_buy_overpay_for_order("OP123", conn=conn)

        conn.execute.assert_not_called()


class PaidSideEffectsTests(unittest.IsolatedAsyncioTestCase):
    async def test_paid_path_runs_cashback_before_overpay_credit(self):
        with (
            patch("services.order_financial.apply_paid_financial_effects", new=AsyncMock()),
            patch("services.partner_commission.accrue_partner_commission", new=AsyncMock()),
            patch("services.user_referral_commission.accrue_user_referral_commission", new=AsyncMock()),
            patch("services.user_cashback_commission.accrue_user_cashback", new=AsyncMock()) as cashback,
            patch("services.user_cashback_db.credit_manual_buy_overpay_for_order", new=AsyncMock()) as overpay,
            patch("services.raffle_accrual.accrue_raffle_tickets", new=AsyncMock()),
        ):
            conn = MagicMock()
            conn.fetchval = AsyncMock(return_value=None)
            await _apply_paid_side_effects_in_tx(conn, "OP123")

        cashback.assert_awaited_once_with("OP123", conn=conn)
        overpay.assert_awaited_once_with("OP123", conn=conn)


class PaidMessageOverpayTests(unittest.TestCase):
    def test_message_shows_cashback_and_overpay_separately(self):
        message = format_paid_user_message(
            {"order_id": "OP123", "direction": "buy", "crypto": "usdt", "crypto_amount": 10},
            "",
            cashback_accrued=20,
            overpay_credit=160,
        )
        self.assertIn("Кешбэк на баланс", message)
        self.assertIn("Дополнительный баланс за переплату", message)
        self.assertIn("Выплачено", message)

    def test_message_hides_zero_overpay(self):
        message = format_paid_user_message(
            {"order_id": "OP123", "direction": "buy", "crypto": "usdt", "crypto_amount": 10},
            "",
            overpay_credit=0,
        )
        self.assertNotIn("Дополнительный баланс за переплату", message)


if __name__ == "__main__":
    unittest.main()
