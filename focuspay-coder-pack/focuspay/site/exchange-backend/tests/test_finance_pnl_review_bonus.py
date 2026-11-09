"""P&L: review bonus reduces profit_after_costs and owner_residual."""
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from finance_pnl import compute_pnl
from external_exchange_stats import empty_period_summary


class ReviewBonusPnlTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_bonus_reduces_owner_residual(self):
        mock_conn = AsyncMock()
        fetchval_results = [
            0.0,    # manual_mandatory
            0.0,    # manual_work
            0.0,    # manual_unexpected
            0.0,    # cashback
            0.0,    # referral
            0.0,    # partner
            150.0,  # review_bonus
            0.0,    # wallet_payout
            0.0,    # raffle_winners to_regclass
            0.0,    # exchange_discount
            0.0,    # swap_commission
            0.0,    # daily_salary_total
            0.0,    # usdt_issued_total_for_period
            None,   # tournament table missing
            0.0,    # requisite cost
        ]
        mock_conn.fetchval = AsyncMock(side_effect=fetchval_results)
        mock_conn.fetchrow = AsyncMock(return_value=None)  # capital snapshot отсутствует
        mock_conn.fetch = AsyncMock(
            side_effect=[
                [],  # orders (38)
                [],  # operator_accounts (180)
                [],  # operator_orders (195)
                [],  # split_payroll_rows
                [],  # hourly_payroll_rows
                [],  # operator_shifts
            ]
        )

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = ctx

        async def _pool():
            return mock_pool

        with patch("finance_pnl.get_pool", side_effect=_pool), patch(
            "finance_pnl.fetch_accruals_for_orders", new=AsyncMock(return_value={})
        ), patch(
            "finance_pnl.fetch_period_summary",
            new=AsyncMock(return_value=empty_period_summary()),
        ), patch("finance_pnl.admin_weekly_salary_rub", return_value=0.0), patch(
            "finance_pnl.market_prices_rub", new=AsyncMock(return_value={"usdt": 0.0})
        ):
            result = await compute_pnl(date(2026, 6, 1), date(2026, 6, 1))

        self.assertEqual(result["costs"]["review_bonus"], 150.0)
        self.assertEqual(result["costs"]["total"], 150.0)
        self.assertEqual(result["total"]["profit_after_costs"], -150.0)
        self.assertEqual(result["payroll"]["owner_residual"], -150.0)
        rb = next(s for s in result["waterfall"] if s["key"] == "review_bonus")
        self.assertEqual(rb["amount"], -150.0)
        self.assertEqual(rb["kind"], "expense")


if __name__ == "__main__":
    unittest.main()
