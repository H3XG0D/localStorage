import unittest
from decimal import Decimal

from services.swap_commission_parse import (
    parse_swap_commission_parts,
    parse_swap_commission_text,
)


class SwapCommissionParseTests(unittest.TestCase):
    def test_usdt(self):
        p = parse_swap_commission_text("5.2 USDT")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.crypto, "usdt")
        self.assertEqual(p.crypto_amount, Decimal("5.2"))

    def test_comma_decimal(self):
        p = parse_swap_commission_text("комиссия 3,15 usdt")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.crypto_amount, Decimal("3.15"))

    def test_rub(self):
        p = parse_swap_commission_text("150 ₽")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.crypto, "rub")
        self.assertEqual(p.crypto_amount, Decimal("150"))

    def test_btc(self):
        p = parse_swap_commission_text("0.001 btc")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.crypto, "btc")

    def test_multi_glued(self):
        parts = parse_swap_commission_parts("10trx + 2usdt + 0.00024btc")
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0].crypto, "trx")
        self.assertEqual(parts[0].crypto_amount, Decimal("10"))
        self.assertEqual(parts[1].crypto, "usdt")
        self.assertEqual(parts[1].crypto_amount, Decimal("2"))
        self.assertEqual(parts[2].crypto, "btc")
        self.assertEqual(parts[2].crypto_amount, Decimal("0.00024"))

    def test_multi_spaced(self):
        parts = parse_swap_commission_parts("10 TRX + 2 USDT + 150 ₽")
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[2].crypto, "rub")

    def test_no_match(self):
        self.assertIsNone(parse_swap_commission_text("привет всем"))
        self.assertEqual(parse_swap_commission_parts(""), [])


if __name__ == "__main__":
    unittest.main()
