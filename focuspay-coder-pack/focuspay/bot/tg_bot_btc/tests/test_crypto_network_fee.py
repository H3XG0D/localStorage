"""Расчёт комиссии сети и минимумов вывода."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from services.crypto_network_fee import (
    casino_withdraw_fee_rub,
    format_withdraw_terms_html,
    min_withdraw_usd,
    network_fee_applies,
    payout_amount_rub,
    withdraw_fee_rub,
    withdraw_network_fee_rub,
    withdraw_terms_snapshot,
)


class CryptoNetworkFeeTests(unittest.TestCase):
    def test_withdraw_fee_btc_ltc_trx_usdt(self):
        self.assertEqual(withdraw_network_fee_rub("btc", usdt_rub=90), 225.0)
        self.assertEqual(withdraw_network_fee_rub("ltc", usdt_rub=90), 225.0)
        self.assertEqual(withdraw_network_fee_rub("trx", usdt_rub=90), 225.0)
        self.assertAlmostEqual(withdraw_network_fee_rub("usdt", usdt_rub=90), 360.0)

    def test_payout_amount_rub(self):
        self.assertEqual(payout_amount_rub(5000, "btc", usdt_rub=90), 4775.0)
        self.assertEqual(payout_amount_rub(30, "btc", usdt_rub=90), 0.0)

    def test_min_withdraw_usd_per_coin(self):
        self.assertEqual(min_withdraw_usd("btc"), 5.0)
        self.assertEqual(min_withdraw_usd("usdt"), 20.0)

    def test_network_fee_applies(self):
        self.assertTrue(network_fee_applies("btc"))
        self.assertTrue(network_fee_applies("trx"))

    def test_one_table_card_btc_ltc_trx(self):
        self.assertEqual(casino_withdraw_fee_rub("card", None, usdt_rub=80), 100.0)
        self.assertEqual(casino_withdraw_fee_rub("crypto", "btc", usdt_rub=80), 200.0)
        self.assertEqual(casino_withdraw_fee_rub("crypto", "ltc", usdt_rub=80), 200.0)
        self.assertEqual(casino_withdraw_fee_rub("crypto", "trx", usdt_rub=80), 200.0)
        self.assertEqual(withdraw_fee_rub("card", None, usdt_rub=80, source="casino"), 100.0)
        self.assertEqual(withdraw_fee_rub("crypto", "btc", usdt_rub=90, source="casino"), 225.0)
        self.assertEqual(withdraw_fee_rub("card", None, usdt_rub=80, source="balance"), 100.0)
        self.assertEqual(withdraw_fee_rub("crypto", "btc", usdt_rub=90, source="balance"), 225.0)
        self.assertEqual(withdraw_fee_rub("crypto", "trx", usdt_rub=80, source="balance"), 200.0)


class WithdrawTermsFormatTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_includes_rub_mins(self):
        with patch(
            "services.crypto_network_fee.resolve_usdt_rub",
            new=AsyncMock(return_value=90.0),
        ):
            snap = await withdraw_terms_snapshot()
        self.assertAlmostEqual(snap["mins"]["btc"]["rub"], 450.0)
        self.assertAlmostEqual(snap["mins"]["usdt"]["rub"], 1800.0)
        self.assertEqual(snap["fees"]["card"]["rub"], 100.0)
        self.assertEqual(snap["fees"]["trx"]["usd"], 2.5)
        self.assertEqual(snap["fees"]["trx"]["rub"], 225.0)
        self.assertEqual(snap["fees"]["btc"]["usd"], 2.5)
        self.assertEqual(snap["fees"]["usdt"]["usd"], 4.0)

    async def test_format_html_contains_rub(self):
        with patch(
            "services.crypto_network_fee.resolve_usdt_rub",
            new=AsyncMock(return_value=90.0),
        ):
            html = await format_withdraw_terms_html(compact=False)
        self.assertIn("₽", html)
        self.assertIn("450", html)
        self.assertIn("LTC", html)
        self.assertIn("TRX", html)
        self.assertIn("$2.5", html)
        self.assertIn("225", html)
        self.assertIn("100", html)
        self.assertIn("$4", html)


class UsdtBuySendFeeTests(unittest.TestCase):
    def test_buy_client_send_fee_only_usdt(self):
        from services.crypto_network_fee import buy_client_send_fee_rub

        self.assertAlmostEqual(buy_client_send_fee_rub("usdt", usdt_rub=90), 360.0)
        self.assertAlmostEqual(buy_client_send_fee_rub("USDT_TRC20", usdt_rub=90), 360.0)
        self.assertEqual(buy_client_send_fee_rub("btc", usdt_rub=90), 0.0)
        self.assertEqual(buy_client_send_fee_rub("ltc", usdt_rub=90), 0.0)
        self.assertEqual(buy_client_send_fee_rub("trx", usdt_rub=90), 0.0)

    def test_apply_keeps_crypto_adds_pay(self):
        from decimal import Decimal

        from services.crypto_network_fee import apply_buy_client_send_fee

        crypto_amount = Decimal("100")
        pay = Decimal("10900.00")
        new_pay, fee = apply_buy_client_send_fee(pay, "usdt", usdt_rub=90)
        self.assertEqual(crypto_amount, Decimal("100"))
        self.assertAlmostEqual(fee, 360.0)
        self.assertEqual(new_pay, Decimal("11260.00"))
        btc_pay, btc_fee = apply_buy_client_send_fee(pay, "btc", usdt_rub=90)
        self.assertEqual(btc_pay, pay)
        self.assertEqual(btc_fee, 0.0)

    def test_format_html_uses_config_usd(self):
        from services.crypto_network_fee import format_usdt_buy_send_fee_html

        html = format_usdt_buy_send_fee_html(fee_rub=360)
        self.assertIn("$4", html)
        self.assertIn("360", html)
        self.assertIn("добавляется к оплате", html)
        self.assertIn("$4", format_usdt_buy_send_fee_html())


if __name__ == "__main__":
    unittest.main()
