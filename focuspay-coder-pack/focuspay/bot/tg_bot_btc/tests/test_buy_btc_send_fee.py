import unittest
from decimal import Decimal
from unittest.mock import patch

from services import config_rates
from services.crypto_network_fee import (
    apply_buy_client_send_fee,
    btc_send_surcharge_rub,
    buy_btc_send_fee_rub,
)

BTC_RUB = 9_000_000.0


class BuyBtcSendFeeTest(unittest.TestCase):
    def setUp(self):
        # Потолок в процентах выключен, чтобы проверять саму себестоимость.
        self._p = [
            patch.object(config_rates, "BUY_BTC_FEE_FREE_SAT_VB", 2.0),
            patch.object(config_rates, "BUY_BTC_FEE_VSIZE", 200),
            patch.object(config_rates, "BUY_BTC_FEE_BUFFER_PCT", 0.0),
            patch.object(config_rates, "BUY_BTC_FEE_MAX_PCT_OF_ORDER", 0.0),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def test_at_or_below_threshold_is_free(self):
        for rate in (None, 0, 1.5, 2.0):
            self.assertEqual(
                btc_send_surcharge_rub(rate, btc_rub=BTC_RUB, order_rub=50_000), 0.0
            )

    def test_excess_over_threshold_is_charged(self):
        # (8 - 2) * 200 = 1200 sat = 0.000012 BTC
        fee = btc_send_surcharge_rub(8, btc_rub=BTC_RUB, order_rub=50_000)
        self.assertAlmostEqual(fee, 0.000012 * BTC_RUB, places=2)

    def test_buffer_is_added(self):
        with patch.object(config_rates, "BUY_BTC_FEE_BUFFER_PCT", 20.0):
            fee = btc_send_surcharge_rub(8, btc_rub=BTC_RUB, order_rub=50_000)
        self.assertAlmostEqual(fee, 0.000012 * BTC_RUB * 1.2, places=2)

    def test_percent_cap_protects_small_orders(self):
        with patch.object(config_rates, "BUY_BTC_FEE_MAX_PCT_OF_ORDER", 3.0):
            fee = btc_send_surcharge_rub(40, btc_rub=BTC_RUB, order_rub=1_500)
        self.assertEqual(fee, 45.0)

    def test_no_rate_no_surcharge(self):
        self.assertEqual(
            btc_send_surcharge_rub(None, btc_rub=BTC_RUB, order_rub=50_000), 0.0
        )

    def test_only_btc(self):
        self.assertEqual(
            buy_btc_send_fee_rub(
                "ltc", btc_rub=BTC_RUB, order_rub=50_000, fee_rate_sat_vb=8
            ),
            0.0,
        )
        self.assertGreater(
            buy_btc_send_fee_rub(
                "btc", btc_rub=BTC_RUB, order_rub=50_000, fee_rate_sat_vb=8
            ),
            0.0,
        )

    def test_apply_adds_to_fiat_and_keeps_decimal(self):
        pay, fee = apply_buy_client_send_fee(
            Decimal("50000.00"), "btc", usdt_rub=BTC_RUB, btc_fee_rate_sat_vb=8
        )
        self.assertIsInstance(pay, Decimal)
        self.assertGreater(fee, 0)
        self.assertEqual(pay, Decimal("50000.00") + Decimal(str(fee)))

    def test_apply_without_rate_is_unchanged(self):
        pay, fee = apply_buy_client_send_fee(
            Decimal("50000.00"), "btc", usdt_rub=BTC_RUB
        )
        self.assertEqual(fee, 0.0)
        self.assertEqual(pay, Decimal("50000.00"))

    def test_usdt_fee_still_wins_for_usdt(self):
        pay, fee = apply_buy_client_send_fee(
            Decimal("50000.00"), "usdt", usdt_rub=90, btc_fee_rate_sat_vb=8
        )
        self.assertEqual(fee, round(config_rates.CRYPTO_NETWORK_FEE_USD_USDT * 90, 2))
        self.assertEqual(pay, Decimal("50000.00") + Decimal(str(fee)))


if __name__ == "__main__":
    unittest.main()
