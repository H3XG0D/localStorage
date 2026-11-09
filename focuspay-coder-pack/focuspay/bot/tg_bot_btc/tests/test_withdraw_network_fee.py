"""Crypto withdrawal: network fee deducted from payout."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from services.user_referral_withdraw import create_withdrawal, format_withdrawal_admin_message


class WithdrawNetworkFeeTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_withdrawal_rejects_amount_below_fee(self):
        with (
            patch(
                "services.user_referral_withdraw.resolve_usdt_rub",
                new=AsyncMock(return_value=90.0),
            ),
            patch(
                "services.user_referral_withdraw.min_crypto_amount_rub",
                new=AsyncMock(return_value=10.0),
            ),
        ):
            with self.assertRaises(ValueError) as ctx:
                await create_withdrawal(
                    referrer_user_id=1,
                    amount_rub=40.0,
                    method="crypto",
                    requisites="bc1qtest",
                    crypto="btc",
                )
            self.assertIn("комиссия сети", str(ctx.exception).lower())

    def test_admin_message_shows_payout_after_fee(self):
        msg = format_withdrawal_admin_message(
            {
                "id": 7,
                "referrer_user_id": 42,
                "method": "crypto",
                "amount_rub": 5000.0,
                "network_fee_rub": 50.0,
                "payout_amount_rub": 4950.0,
                "crypto": "btc",
                "network": None,
                "requisites": "bc1qtest",
            },
            "alice",
        )
        self.assertIn("4,950", msg)
        self.assertIn("50", msg)
        self.assertIn("К отправке", msg)

    def test_admin_message_casino_card_shows_fee(self):
        msg = format_withdrawal_admin_message(
            {
                "id": 8,
                "referrer_user_id": 42,
                "method": "card",
                "amount_rub": 500.0,
                "network_fee_rub": 100.0,
                "payout_amount_rub": 400.0,
                "source": "casino",
                "requisites": "2200700123456789",
            },
            "alice",
        )
        self.assertIn("400", msg)
        self.assertIn("100", msg)
        self.assertIn("К отправке", msg)


if __name__ == "__main__":
    unittest.main()
