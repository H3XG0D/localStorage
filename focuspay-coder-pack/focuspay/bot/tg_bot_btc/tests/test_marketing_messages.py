"""Маркетинговые сообщения после PAID."""
import unittest

from services.cashback_tier import tier_info


class CashbackProgressTests(unittest.TestCase):
    def test_tier_until_next(self):
        info = tier_info(3)
        self.assertGreater(info["percent"], 0)
        self.assertGreaterEqual(info["exchanges_until_next_tier"], 0)

    def test_max_tier_zero_until(self):
        info = tier_info(100)
        self.assertEqual(info["exchanges_until_next_tier"], 0)


if __name__ == "__main__":
    unittest.main()
