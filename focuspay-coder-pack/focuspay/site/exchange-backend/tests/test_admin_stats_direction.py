"""Tests for per-direction daily profit bucketing in admin stats."""
import unittest


def profit_type_bucket(direction: str, merchant_order_id) -> str:
    """Mirror of admin_stats.py bucketing logic."""
    if direction == "buy":
        return "profit_auto_buy" if merchant_order_id else "profit_manual_buy"
    return "profit_sell"


class TestProfitTypeBucket(unittest.TestCase):
    def test_auto_buy(self):
        self.assertEqual(profit_type_bucket("buy", "uuid-123"), "profit_auto_buy")

    def test_manual_buy(self):
        self.assertEqual(profit_type_bucket("buy", None), "profit_manual_buy")
        self.assertEqual(profit_type_bucket("buy", ""), "profit_manual_buy")

    def test_sell(self):
        self.assertEqual(profit_type_bucket("sell", None), "profit_sell")
        self.assertEqual(profit_type_bucket("sell", "uuid"), "profit_sell")


if __name__ == "__main__":
    unittest.main()
