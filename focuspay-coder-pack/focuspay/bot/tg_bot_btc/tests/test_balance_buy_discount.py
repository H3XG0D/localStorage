"""Баланс на BUY: только скидка ₽, крипта клиента не меняется."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.user_cashback_db import apply_cashback_with_conn


class BalanceBuyDiscountTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_cashback_with_conn_keeps_crypto(self):
        conn = MagicMock()
        with patch(
            "services.user_cashback_db._cashback_spendable",
            new=AsyncMock(return_value=21.05),
        ):
            fiat_pay, crypto_out, applied = await apply_cashback_with_conn(
                conn,
                user_id=1,
                fiat_amount=4437.0,
                crypto_amount=1.070654,
                rate=4105.0,
                crypto="LTC",
                use_cashback=True,
            )
        self.assertAlmostEqual(applied, 21.05)
        self.assertAlmostEqual(fiat_pay, 4437.0 - 21.05)
        self.assertAlmostEqual(crypto_out, 1.070654)

    def test_validate_payout_after_balance_discount(self):
        from services.buy_payout_validate import validate_buy_payout_crypto

        order = {
            "crypto": "LTC",
            "fiat_amount": 4416,
            "crypto_amount": 1.070654,
            "rate": 4105.0,
            "cashback_applied_rub": 21.05,
            "exchange_discount_applied_rub": 0,
        }
        ok, reason = validate_buy_payout_crypto(order)
        self.assertTrue(ok, reason)


if __name__ == "__main__":
    unittest.main()
