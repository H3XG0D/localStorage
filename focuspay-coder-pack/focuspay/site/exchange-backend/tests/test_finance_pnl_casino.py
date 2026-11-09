"""P&L: casino owner profit is added to net_profit and owner_residual."""
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from finance_pnl import (
    compute_pnl,
    empty_casino_owner_profit,
    fetch_casino_owner_profit,
    fetch_casino_owner_profit_daily,
)
from external_exchange_stats import empty_period_summary


def _empty_pool_conn():
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
            0.0,  # raffle_winners to_regclass
            0.0,  # exchange_discount
            0.0,  # swap_commission
            0.0,  # daily_salary_total
            0.0,  # usdt_issued_total_for_period
            None,  # tournament table missing
            0.0,  # requisite cost
        ]
    )
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
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = ctx

    async def _pool():
        return mock_pool

    return mock_conn, _pool


class CasinoOwnerProfitHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_sums_commission_and_house(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"commission_profit": 21.5, "house_game_profit": 8.5}
        )
        got = await fetch_casino_owner_profit(conn, date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(got["commission_profit_rub"], 21.5)
        self.assertEqual(got["house_game_profit_rub"], 8.5)
        self.assertEqual(got["owner_profit_rub"], 30.0)
        sql = conn.fetchrow.await_args.args[0]
        self.assertIn("casino_commission_ledger", sql)
        self.assertIn("recipient_type = 'owner'", sql)
        self.assertIn("game_settlement", sql)
        self.assertIn("casino_v2_house_ledger", sql)
        self.assertIn("casino_v2_settlements", sql)
        self.assertIn("NOT EXISTS", sql)
        self.assertIn("casino_jackpot_rounds", sql)
        self.assertIn("jackpot-rake-", sql)
        self.assertIn("casino_fixed_room_rounds", sql)
        self.assertIn("room-rake-", sql)
        self.assertNotIn("funding", sql)

    async def test_none_row_is_zero(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        self.assertEqual(
            await fetch_casino_owner_profit(conn, date(2026, 8, 1), date(2026, 8, 1)),
            empty_casino_owner_profit(),
        )

    async def test_daily_maps_iso_dates(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {"day": date(2026, 8, 1), "profit": 10.0},
                {"day": date(2026, 8, 2), "profit": -3.25},
            ]
        )
        got = await fetch_casino_owner_profit_daily(
            conn, date(2026, 8, 1), date(2026, 8, 2)
        )
        self.assertEqual(got["2026-08-01"], 10.0)
        self.assertEqual(got["2026-08-02"], -3.25)
        daily_sql = conn.fetch.await_args.args[0]
        self.assertIn("casino_v2_house_ledger", daily_sql)
        self.assertIn("casino_jackpot_rounds", daily_sql)
        self.assertIn("casino_fixed_room_rounds", daily_sql)


class CasinoPnlTests(unittest.IsolatedAsyncioTestCase):
    async def test_casino_enters_net_profit_and_residual(self):
        _conn, _pool = _empty_pool_conn()
        casino = {
            "commission_profit_rub": 20.0,
            "house_game_profit_rub": 30.0,
            "owner_profit_rub": 50.0,
        }
        with patch("finance_pnl.get_pool", side_effect=_pool), patch(
            "finance_pnl.fetch_accruals_for_orders", new=AsyncMock(return_value={})
        ), patch(
            "finance_pnl.fetch_period_summary",
            new=AsyncMock(return_value=empty_period_summary()),
        ), patch(
            "finance_pnl.fetch_casino_owner_profit",
            new=AsyncMock(return_value=casino),
        ), patch("finance_pnl.admin_weekly_salary_rub", return_value=0.0), patch(
            "finance_pnl.market_prices_rub", new=AsyncMock(return_value={"usdt": 0.0})
        ):
            result = await compute_pnl(date(2026, 8, 1), date(2026, 8, 1))

        self.assertEqual(result["casino"]["owner_profit_rub"], 50.0)
        self.assertEqual(result["total"]["net_profit"], 50.0)
        self.assertEqual(result["total"]["profit_after_costs"], 50.0)
        self.assertEqual(result["payroll"]["owner_residual"], 50.0)
        self.assertEqual(result["total"]["fiat_volume"], 0.0)
        step = next(s for s in result["waterfall"] if s["key"] == "casino_profit")
        self.assertEqual(step["amount"], 50.0)
        self.assertEqual(step["kind"], "income")
        self.assertEqual(step["label"], "Казино: комиссия + дом")
        total_step = next(s for s in result["waterfall"] if s["key"] == "service_profit_total")
        self.assertEqual(total_step["amount"], 50.0)
        self.assertIn("казино", total_step["label"])
        casino_row = next(r for r in result["by_type"] if r["type"] == "casino")
        self.assertEqual(casino_row["orders"], 0)
        self.assertEqual(casino_row["net_profit"], 50.0)
        self.assertEqual(casino_row["fiat_volume"], 0.0)
        service = next(s for s in result["waterfall"] if s["key"] == "service_profit")
        self.assertEqual(service["amount"], 0.0)

    async def test_house_loss_still_in_waterfall(self):
        _conn, _pool = _empty_pool_conn()
        casino = {
            "commission_profit_rub": 5.0,
            "house_game_profit_rub": -40.0,
            "owner_profit_rub": -35.0,
        }
        with patch("finance_pnl.get_pool", side_effect=_pool), patch(
            "finance_pnl.fetch_accruals_for_orders", new=AsyncMock(return_value={})
        ), patch(
            "finance_pnl.fetch_period_summary",
            new=AsyncMock(return_value=empty_period_summary()),
        ), patch(
            "finance_pnl.fetch_casino_owner_profit",
            new=AsyncMock(return_value=casino),
        ), patch("finance_pnl.admin_weekly_salary_rub", return_value=0.0), patch(
            "finance_pnl.market_prices_rub", new=AsyncMock(return_value={"usdt": 0.0})
        ):
            result = await compute_pnl(date(2026, 8, 1), date(2026, 8, 1))

        self.assertEqual(result["total"]["net_profit"], -35.0)
        self.assertEqual(result["payroll"]["owner_residual"], -35.0)
        step = next(s for s in result["waterfall"] if s["key"] == "casino_profit")
        self.assertEqual(step["amount"], -35.0)

    async def test_zero_casino_still_in_waterfall(self):
        _conn, _pool = _empty_pool_conn()
        with patch("finance_pnl.get_pool", side_effect=_pool), patch(
            "finance_pnl.fetch_accruals_for_orders", new=AsyncMock(return_value={})
        ), patch(
            "finance_pnl.fetch_period_summary",
            new=AsyncMock(return_value=empty_period_summary()),
        ), patch(
            "finance_pnl.fetch_casino_owner_profit",
            new=AsyncMock(return_value=empty_casino_owner_profit()),
        ), patch("finance_pnl.admin_weekly_salary_rub", return_value=0.0), patch(
            "finance_pnl.market_prices_rub", new=AsyncMock(return_value={"usdt": 0.0})
        ):
            result = await compute_pnl(date(2026, 8, 1), date(2026, 8, 1))
        step = next(s for s in result["waterfall"] if s["key"] == "casino_profit")
        self.assertEqual(step["amount"], 0.0)
        casino_row = next(r for r in result["by_type"] if r["type"] == "casino")
        self.assertEqual(casino_row["net_profit"], 0.0)


if __name__ == "__main__":
    unittest.main()
