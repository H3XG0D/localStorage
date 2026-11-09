"""Котировка вывода баланса: сколько крипты слать по живому курсу."""
from __future__ import annotations

import unittest

from crypto_network_fee import quote_withdraw_crypto, withdraw_payout_rub


class QuoteWithdrawCryptoTests(unittest.TestCase):
    def test_btc_2700_rub_nonzero(self):
        out = quote_withdraw_crypto(
            method="crypto",
            crypto="btc",
            amount_rub=2700,
            payout_amount_rub=2700,
            rates={"btc": 1_000_000},
        )
        self.assertEqual(out["rate_rub"], 1_000_000.0)
        self.assertAlmostEqual(out["payout_crypto_amount"], 0.0027, places=8)

    def test_uses_payout_after_network_fee(self):
        out = quote_withdraw_crypto(
            method="crypto",
            crypto="btc",
            amount_rub=2700,
            network_fee_rub=200,
            payout_amount_rub=2500,
            rates={"btc": 1_000_000},
        )
        self.assertAlmostEqual(out["payout_crypto_amount"], 0.0025, places=8)

    def test_falls_back_to_amount_minus_fee(self):
        self.assertEqual(
            withdraw_payout_rub(amount_rub=2700, network_fee_rub=200),
            2500.0,
        )
        out = quote_withdraw_crypto(
            method="crypto",
            crypto="btc",
            amount_rub=2700,
            network_fee_rub=200,
            rates={"btc": 1_000_000},
        )
        self.assertAlmostEqual(out["payout_crypto_amount"], 0.0025, places=8)

    def test_usdt_trc20_uses_base_coin(self):
        out = quote_withdraw_crypto(
            method="crypto",
            crypto="usdt_trc20",
            payout_amount_rub=800,
            rates={"usdt": 80},
        )
        self.assertAlmostEqual(out["payout_crypto_amount"], 10.0, places=2)
        self.assertEqual(out["rate_rub"], 80.0)

    def test_card_has_no_crypto_amount(self):
        out = quote_withdraw_crypto(
            method="card",
            crypto=None,
            amount_rub=2700,
            rates={"btc": 1_000_000},
        )
        self.assertIsNone(out["payout_crypto_amount"])
        self.assertIsNone(out["rate_rub"])

    def test_missing_rate_is_null(self):
        out = quote_withdraw_crypto(
            method="crypto",
            crypto="btc",
            payout_amount_rub=2700,
            rates={"usdt": 80},
        )
        self.assertIsNone(out["payout_crypto_amount"])
        self.assertIsNone(out["rate_rub"])


if __name__ == "__main__":
    unittest.main()
