"""Unit-тесты агрегации прибыли в профиле покупателя."""
import unittest

from buyer_profile_service import (
    compute_gross_profit_from_orders,
    compute_net_profit_rub,
)
from service_profit import order_service_profit


class TestBuyerProfileProfit(unittest.TestCase):
    def test_order_service_profit_buy_manual(self):
        p = order_service_profit(
            "buy",
            "usdt_trc20",
            10000.0,
            100.0,
            100.0,
            cashback_applied_rub=50.0,
            card_fee_pct=0.02,
        )
        self.assertGreater(p, 0)

    def test_compute_gross_profit_from_orders(self):
        orders = [
            {
                "direction": "buy",
                "crypto": "usdt",
                "fiat_amount": 5000.0,
                "crypto_amount": 50.0,
                "rate": 100.0,
                "cashback_applied_rub": 0,
                "card_fee_pct": None,
            },
            {
                "direction": "sell",
                "crypto": "usdt",
                "fiat_amount": 3000.0,
                "crypto_amount": 30.0,
                "rate": 100.0,
                "cashback_applied_rub": 0,
                "card_fee_pct": None,
            },
        ]
        gross = compute_gross_profit_from_orders(orders)
        expected = sum(
            order_service_profit(
                o["direction"],
                o["crypto"],
                o["fiat_amount"],
                o["crypto_amount"],
                o["rate"],
                cashback_applied_rub=0,
                card_fee_pct=None,
            )
            for o in orders
        )
        self.assertEqual(gross, round(expected, 2))

    def test_compute_net_profit_rub(self):
        net = compute_net_profit_rub(1000.0, 100.0, 50.0, 25.0)
        self.assertEqual(net, 825.0)

    def test_compute_net_profit_rub_zero_costs(self):
        self.assertEqual(compute_net_profit_rub(500.0, 0, 0, 0), 500.0)


class TestBuyerTrustLevel(unittest.TestCase):
    def test_thresholds(self):
        from buyer_profile_service import buyer_trust_level

        self.assertEqual(buyer_trust_level(0), "Новый")
        self.assertEqual(buyer_trust_level(1), "Начинающий")
        self.assertEqual(buyer_trust_level(3), "Начинающий")
        self.assertEqual(buyer_trust_level(4), "Постоянный")
        self.assertEqual(buyer_trust_level(9), "Постоянный")
        self.assertEqual(buyer_trust_level(10), "Доверенный")
        self.assertEqual(buyer_trust_level(19), "Доверенный")
        self.assertEqual(buyer_trust_level(20), "VIP")


if __name__ == "__main__":
    unittest.main()
