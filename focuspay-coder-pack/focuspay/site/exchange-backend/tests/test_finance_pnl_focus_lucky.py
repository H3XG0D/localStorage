"""P&L: paid FocusLucky prizes reduce profit_after_costs and owner_residual."""
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from finance_pnl import compute_pnl, fetch_focus_lucky_prize_cost
from external_exchange_stats import empty_period_summary


def _pool_for(mock_conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = ctx

    async def _pool():
        return mock_pool

    return _pool


def _empty_fetches(mock_conn):
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.fetch = AsyncMock(
        side_effect=[
            [],  # orders
            [],  # operator_accounts
            [],  # operator_orders
            [],  # split_payroll_rows
            [],  # hourly_payroll_rows
            [],  # operator_shifts
        ]
    )


class FocusLuckyPrizeCostHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_table_is_zero(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        self.assertEqual(
            await fetch_focus_lucky_prize_cost(conn, date(2026, 9, 1), date(2026, 9, 1)),
            0.0,
        )
        self.assertEqual(conn.fetchval.await_count, 1)

    async def test_sums_paid_prizes(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=["raffle_winners", 14500.0])
        got = await fetch_focus_lucky_prize_cost(
            conn, date(2026, 9, 1), date(2026, 9, 1)
        )
        self.assertEqual(got, 14500.0)
        sql = conn.fetchval.await_args_list[1].args[0]
        self.assertIn("raffle_winners", sql)
        self.assertIn("status = 'paid'", sql)
        self.assertIn("paid_at::date", sql)


class FocusLuckyPnlTests(unittest.IsolatedAsyncioTestCase):
    async def test_paid_prizes_reduce_owner_residual(self):
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(
            side_effect=[
                0.0,  # manual_mandatory
                0.0,  # manual_work
                0.0,  # manual_unexpected
                0.0,  # cashback
                0.0,  # referral
                0.0,  # partner
                0.0,  # review_bonus
                0.0,  # wallet_payout
                0.0,  # exchange_discount
                0.0,  # swap_commission
                0.0,  # daily_salary_total
                0.0,  # usdt_issued_total_for_period
                None,  # vpn purchases row is fetchrow; tournament table missing
                0.0,  # requisite cost
            ]
        )
        _empty_fetches(mock_conn)

        with patch("finance_pnl.get_pool", side_effect=_pool_for(mock_conn)), patch(
            "finance_pnl.fetch_accruals_for_orders", new=AsyncMock(return_value={})
        ), patch(
            "finance_pnl.fetch_period_summary",
            new=AsyncMock(return_value=empty_period_summary()),
        ), patch(
            "finance_pnl.fetch_focus_lucky_prize_cost",
            new=AsyncMock(return_value=14500.0),
        ), patch("finance_pnl.admin_weekly_salary_rub", return_value=0.0), patch(
            "finance_pnl.market_prices_rub", new=AsyncMock(return_value={"usdt": 0.0})
        ):
            result = await compute_pnl(date(2026, 9, 1), date(2026, 9, 1))

        self.assertEqual(result["costs"]["focus_lucky"], 14500.0)
        self.assertEqual(result["costs"]["wallet_payout"], 0.0)
        self.assertEqual(result["costs"]["total"], 14500.0)
        self.assertEqual(result["total"]["profit_after_costs"], -14500.0)
        self.assertEqual(result["payroll"]["owner_residual"], -14500.0)
        step = next(s for s in result["waterfall"] if s["key"] == "focus_lucky")
        self.assertEqual(step["amount"], -14500.0)
        self.assertEqual(step["kind"], "expense")
        self.assertEqual(step["label"], "FocusLucky")

    async def test_wallet_payout_sql_excludes_raffle_ltc(self):
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(
            side_effect=[
                0.0,  # manual_mandatory
                0.0,  # manual_work
                0.0,  # manual_unexpected
                0.0,  # cashback
                0.0,  # referral
                0.0,  # partner
                0.0,  # review_bonus
                0.0,  # wallet_payout (already without raffle rows)
                0.0,  # exchange_discount
                0.0,  # swap_commission
                0.0,  # daily_salary_total
                0.0,  # usdt_issued_total_for_period
                None,  # tournament table missing
                0.0,  # requisite cost
            ]
        )
        _empty_fetches(mock_conn)

        with patch("finance_pnl.get_pool", side_effect=_pool_for(mock_conn)), patch(
            "finance_pnl.fetch_accruals_for_orders", new=AsyncMock(return_value={})
        ), patch(
            "finance_pnl.fetch_period_summary",
            new=AsyncMock(return_value=empty_period_summary()),
        ), patch(
            "finance_pnl.fetch_focus_lucky_prize_cost",
            new=AsyncMock(return_value=5000.0),
        ), patch("finance_pnl.admin_weekly_salary_rub", return_value=0.0), patch(
            "finance_pnl.market_prices_rub", new=AsyncMock(return_value={"usdt": 0.0})
        ):
            result = await compute_pnl(date(2026, 9, 1), date(2026, 9, 1))

        wallet_sql = next(
            call.args[0]
            for call in mock_conn.fetchval.await_args_list
            if "operator_wallet_payouts" in call.args[0]
        )
        self.assertIn("raffle_winner_id IS NULL", wallet_sql)
        self.assertEqual(result["costs"]["focus_lucky"], 5000.0)
        self.assertEqual(result["costs"]["wallet_payout"], 0.0)
        self.assertEqual(result["costs"]["total"], 5000.0)


if __name__ == "__main__":
    unittest.main()
