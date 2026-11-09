"""Скидка на обмен: снижает цену (не крипту), порог, и реальный минус в P&L."""
import unittest
from unittest.mock import AsyncMock

from exchange_discount_db import apply_discount_with_conn, preview_discount_amount
from service_profit import order_service_profit


class ApplyDiscountPriceTests(unittest.IsolatedAsyncioTestCase):
    async def test_discount_reduces_fiat_keeps_crypto(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"id": 1, "amount_rub": 500, "min_order_rub": 3000}
        )
        fiat_pay, crypto_out, applied, did = await apply_discount_with_conn(
            conn, 1, 100, fiat_amount=3600, crypto_amount=10.0, rate=120, crypto="ltc"
        )
        self.assertEqual(applied, 500.0)
        self.assertEqual(fiat_pay, 3100.0)  # 3600 - 500
        self.assertEqual(crypto_out, 10.0)  # крипта НЕ изменилась
        self.assertEqual(did, 1)

    async def test_below_min_order_not_applied(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"id": 1, "amount_rub": 500, "min_order_rub": 3000}
        )
        fiat_pay, crypto_out, applied, did = await apply_discount_with_conn(
            conn, 1, 100, fiat_amount=2500, crypto_amount=10.0, rate=120, crypto="ltc"
        )
        self.assertEqual(applied, 0.0)
        self.assertEqual(fiat_pay, 2500)  # без изменений
        self.assertEqual(crypto_out, 10.0)
        self.assertIsNone(did)


class PreviewDiscountAmountTests(unittest.TestCase):
    def test_preview_matches_apply_logic(self):
        self.assertEqual(preview_discount_amount(3600, 500, 3000), 500.0)
        self.assertEqual(preview_discount_amount(2500, 500, 3000), 0.0)
        self.assertEqual(preview_discount_amount(3600, 5000, 0), 3599.0)


class DiscountPnlTests(unittest.TestCase):
    def test_discounted_order_shows_negative_net(self):
        # Заказ: платит 3100, крипта стоит 3000 по рынку (rate=120, markup=1.2 →
        # market=100; crypto 30 → cost 3000). Комиссия карт 12%.
        net = order_service_profit(
            "buy", "ltc", 3100, 30.0, 120,
            card_fee_pct=0.12, clamp=False,
        )
        # 3100 - 3000 - 0.12*3100 = -272
        self.assertAlmostEqual(net, -272.0, places=2)

    def test_clamp_true_hides_loss(self):
        net = order_service_profit(
            "buy", "ltc", 3100, 30.0, 120,
            card_fee_pct=0.12, clamp=True,
        )
        self.assertEqual(net, 0.0)

    def test_no_discount_positive(self):
        # Без скидки платит 3600 → прибыль положительная.
        net = order_service_profit(
            "buy", "ltc", 3600, 30.0, 120,
            card_fee_pct=0.12, clamp=False,
        )
        # 3600 - 3000 - 0.12*3600 = 168
        self.assertAlmostEqual(net, 168.0, places=2)


if __name__ == "__main__":
    unittest.main()
