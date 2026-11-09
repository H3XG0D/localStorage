"""Минимум вывода реферального баланса в крипте."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from services.crypto_network_fee import min_withdraw_usd
from services.user_referral_withdraw import min_crypto_amount_rub


class TestMinCryptoAmountRub(unittest.IsolatedAsyncioTestCase):
    async def test_btc_ltc_use_five_usd(self):
        with patch(
            "services.crypto_network_fee.get_market_price",
            new=AsyncMock(return_value=(90.0, False, False)),
        ):
            for crypto in ("btc", "ltc", "trx"):
                min_rub = await min_crypto_amount_rub(crypto)
                expected = min_withdraw_usd(crypto) * 90.0
                self.assertAlmostEqual(min_rub, expected, places=2)
                self.assertAlmostEqual(min_rub, 450.0, places=2)

    async def test_usdt_uses_twenty_usd(self):
        with patch(
            "services.crypto_network_fee.get_market_price",
            new=AsyncMock(return_value=(90.0, False, False)),
        ):
            min_rub = await min_crypto_amount_rub("usdt")
            self.assertAlmostEqual(min_rub, 1800.0, places=2)

    async def test_rate_unavailable_raises(self):
        with patch(
            "services.crypto_network_fee.get_market_price",
            new=AsyncMock(return_value=(None, True, True)),
        ):
            with self.assertRaises(ValueError):
                await min_crypto_amount_rub("btc")


class TestWithdrawalSource(unittest.TestCase):
    def test_ops_path_casino_goes_to_payouts(self):
        from services.user_referral_withdraw import normalize_withdrawal_source, ops_path_for_withdrawal

        self.assertEqual(ops_path_for_withdrawal({"source": "casino"}), "/ops/casino-payouts")
        self.assertEqual(ops_path_for_withdrawal({"source": "balance"}), "/ops/orders")
        self.assertEqual(normalize_withdrawal_source(None), "balance")

    def test_card_min_is_20000_for_every_source(self):
        from services.user_referral_withdraw import min_card_withdraw_rub

        self.assertEqual(min_card_withdraw_rub("casino"), 20000)
        self.assertEqual(min_card_withdraw_rub(None), 20000)
        self.assertEqual(min_card_withdraw_rub("balance"), 20000)


class TestCardMinCreateWithdrawal(unittest.IsolatedAsyncioTestCase):
    async def test_casino_card_below_min_rejected(self):
        from services.user_referral_withdraw import create_withdrawal

        with self.assertRaises(ValueError) as ctx:
            await create_withdrawal(
                referrer_user_id=1,
                amount_rub=19999,
                method="card",
                requisites="2200700123456789",
                source="casino",
            )
        self.assertEqual(str(ctx.exception), "Минимум для карты: 20 000 ₽")

    async def test_balance_card_below_500_rejected(self):
        from services.user_referral_withdraw import create_withdrawal

        with self.assertRaises(ValueError) as ctx:
            await create_withdrawal(
                referrer_user_id=1,
                amount_rub=19999,
                method="card",
                requisites="2200700123456789",
            )
        self.assertEqual(str(ctx.exception), "Минимум для карты: 20 000 ₽")


if __name__ == "__main__":
    unittest.main()
