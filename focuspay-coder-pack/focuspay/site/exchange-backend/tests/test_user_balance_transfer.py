import unittest
from decimal import Decimal

from user_balance_transfer import (
    TransferError,
    guard_transfer,
    quote_transfer,
    split_sources,
)


class TransferQuoteTests(unittest.TestCase):
    def test_below_minimum_is_refused(self):
        with self.assertRaises(TransferError) as exc:
            quote_transfer(99.99)
        self.assertEqual(exc.exception.code, "min")

    def test_fee_is_ten_percent_of_the_amount(self):
        amount, fee, net = quote_transfer(100)
        self.assertEqual((amount, fee, net), (Decimal("100.00"), Decimal("10.00"), Decimal("90.00")))
        amount, fee, net = quote_transfer(250.55)
        self.assertEqual(fee, Decimal("25.06"))
        self.assertEqual(net, Decimal("225.49"))
        self.assertEqual(amount, fee + net)

    def test_cannot_send_to_self(self):
        with self.assertRaises(TransferError) as exc:
            guard_transfer(7, 7, 500, 100)
        self.assertEqual(exc.exception.code, "self")

    def test_unknown_recipient_is_refused(self):
        with self.assertRaises(TransferError) as exc:
            guard_transfer(7, None, 500, 100)
        self.assertEqual(exc.exception.code, "unknown")

    def test_balance_cannot_go_negative(self):
        with self.assertRaises(TransferError) as exc:
            guard_transfer(7, 8, 99.99, 100)
        self.assertEqual(exc.exception.code, "funds")
        amount, fee, net = guard_transfer(7, 8, 100, 100)
        self.assertEqual(net, Decimal("90.00"))
        self.assertEqual(amount, fee + net)

    def test_debit_order_uses_cashback_then_referral_then_partner(self):
        parts = split_sources(40, 30, 50, Decimal("100.00"))
        self.assertEqual(parts, (Decimal("40.00"), Decimal("30.00"), Decimal("30.00")))
        self.assertEqual(sum(parts), Decimal("100.00"))
        with self.assertRaises(TransferError) as exc:
            split_sources(10, 10, 10, Decimal("100.00"))
        self.assertEqual(exc.exception.code, "funds")
