"""Тесты уведомлений и начислений по внештатным выплатам/сделкам."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from external_payout_notify import (
    btc_amount_from_usd,
    external_payout_admin_keyboard,
    format_external_payout_admin_message,
    wallet_from_note,
)


class ExternalPayoutNotifyTests(unittest.TestCase):
    def test_wallet_from_note(self):
        self.assertEqual(
            wallet_from_note("Кошелёк: bc1qtest"),
            "bc1qtest",
        )

    def test_btc_amount_from_usd(self):
        # BTC 9_000_000 RUB, USDT 90 RUB → BTC = $100k → $14.33 = 0.0001433
        amt = btc_amount_from_usd(14.33, {"usdt": 90.0, "btc": 9_000_000.0})
        self.assertIsNotNone(amt)
        self.assertAlmostEqual(amt, 0.0001433, places=6)

    def test_format_includes_btc_and_wallet(self):
        text = format_external_payout_admin_message(
            {
                "id": 1,
                "gross_usd": 17.33,
                "fee_usd": 3.0,
                "net_usd": 14.33,
                "crypto": "usdt",
                "crypto_amount": 14.33,
                "note": "Кошелёк: bc1qabc",
            },
            exchanger_name="nch",
            username="nch_0333",
            market_rub={"usdt": 90.0, "btc": 9_000_000.0},
        )
        self.assertIn("bc1qabc", text)
        self.assertIn("BTC", text)
        self.assertIn("nch", text)

    def test_admin_keyboard_extwd_actions(self):
        with patch("external_payout_notify.sign_external_payout", return_value="sig"):
            kb = external_payout_admin_keyboard(42)
        flat = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row if "callback_data" in btn]
        self.assertIn("extwd:skip:42:sig", flat)
        self.assertIn("extwd:receipt:42:sig", flat)
        self.assertIn("extwd:reject:42:sig", flat)


class ShiftExternalDealPayrollTests(unittest.IsolatedAsyncioTestCase):
    async def test_accrue_split_between_two_shift_operators(self):
        from external_deal_shift_payroll import accrue_shift_external_deal

        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[{"operator_id": 1}, {"operator_id": 2}])
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"id": 1, "display_name": "Op1", "username": "op1"},
                {"id": 2, "display_name": "Op2", "username": "op2"},
            ]
        )
        conn.fetchval = AsyncMock(return_value=None)
        conn.execute = AsyncMock()

        n = await accrue_shift_external_deal(conn, deal_id=5, net_profit_rub=1000.0)
        self.assertEqual(n, 2)
        self.assertEqual(conn.execute.await_count, 3)


if __name__ == "__main__":
    unittest.main()
