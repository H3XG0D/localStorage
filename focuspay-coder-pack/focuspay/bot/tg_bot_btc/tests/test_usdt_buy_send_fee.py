"""BUY USDT: +$4 send fee on pay, crypto unchanged, warning copy."""
from __future__ import annotations

import unittest
from decimal import Decimal

from services.buy_rub_quote import quote_buy_rub_base
from services.crypto_network_fee import (
    apply_buy_client_send_fee,
    buy_client_send_fee_rub,
    format_usdt_buy_send_fee_html,
)
from services.ux_copy import txt_amount_prompt, txt_direction, txt_usdt_network


class UsdtBuySendFeeQuoteTests(unittest.TestCase):
    def test_fee_only_usdt(self):
        self.assertAlmostEqual(buy_client_send_fee_rub("usdt", usdt_rub=90), 360.0)
        self.assertAlmostEqual(buy_client_send_fee_rub("USDT_ERC20", usdt_rub=90), 360.0)
        self.assertEqual(buy_client_send_fee_rub("btc", usdt_rub=90), 0.0)
        self.assertEqual(buy_client_send_fee_rub("ltc", usdt_rub=90), 0.0)
        self.assertEqual(buy_client_send_fee_rub("trx", usdt_rub=90), 0.0)

    def test_crypto_fixed_100_usdt_adds_360_at_90(self):
        crypto_amount = Decimal("100")
        pay = (crypto_amount * Decimal("90") * Decimal("1.21")).quantize(Decimal("0.01"))
        new_pay, fee = apply_buy_client_send_fee(pay, "usdt", usdt_rub=90)
        self.assertEqual(crypto_amount, Decimal("100"))
        self.assertAlmostEqual(fee, 360.0)
        self.assertEqual(new_pay, pay + Decimal("360.00"))

    def test_rub_quote_crypto_unchanged_pay_grows(self):
        crypto, pay, _rate = quote_buy_rub_base(
            base_fiat=Decimal("9000"),
            rapira=Decimal("90"),
            coingecko=Decimal("90"),
            markup=Decimal("1.21"),
        )
        new_pay, fee = apply_buy_client_send_fee(pay, "usdt", usdt_rub=90)
        self.assertEqual(crypto, Decimal("100"))
        self.assertAlmostEqual(fee, 360.0)
        self.assertEqual(new_pay, pay + Decimal("360.00"))

    def test_html_contains_dollar_four(self):
        html = format_usdt_buy_send_fee_html(fee_rub=360)
        self.assertIn("$4", html)
        self.assertIn("360", html)

    def test_ux_copy_warns_on_usdt_buy_screens(self):
        self.assertIn("$4", txt_usdt_network())
        direction = txt_direction(
            crypto="usdt",
            coin_title="Tether (USDT · TRC20)",
            rate=90,
        )
        self.assertIn("$4", direction)
        self.assertNotIn("комиссия", direction)
        btc_dir = txt_direction(
            crypto="btc",
            coin_title="Bitcoin (BTC)",
            rate=6_000_000,
        )
        self.assertNotIn("$4", btc_dir)
        amount = txt_amount_prompt(
            crypto="usdt",
            direction="buy",
            unit="rub",
            min_label="1000 ₽",
        )
        self.assertIn("$4", amount)
        sell_amount = txt_amount_prompt(
            crypto="usdt",
            direction="sell",
            unit="coin",
            min_label="10 USDT",
        )
        self.assertNotIn("$4", sell_amount)


if __name__ == "__main__":
    unittest.main()
