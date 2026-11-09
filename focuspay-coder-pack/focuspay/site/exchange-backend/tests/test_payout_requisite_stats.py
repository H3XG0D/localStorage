"""Стоимость реквизитного пула в статистике и в водопаде P&L."""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from payout_requisite_stats import (
    empty_pool_stats,
    fetch_requisite_cost,
    fetch_requisite_cost_daily,
    fetch_requisite_pool_stats,
)

ROOT = Path(__file__).resolve().parents[1]

D_FROM = date(2026, 9, 1)
D_TO = date(2026, 9, 30)


class LedgerCostTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_only_requisite_source(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=1500.0)
        out = await fetch_requisite_cost(conn, D_FROM, D_TO)
        self.assertEqual(out, 1500.0)
        sql, *args = conn.fetchval.await_args.args
        self.assertIn("FROM owner_finance_ledger", sql)
        self.assertIn("source = $3", sql)
        self.assertEqual(args[2], "payout_requisite")

    async def test_negative_cost_is_kept_signed(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=-820.5)
        self.assertEqual(await fetch_requisite_cost(conn, D_FROM, D_TO), -820.5)

    async def test_missing_table_does_not_break(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(side_effect=RuntimeError("no ledger"))
        self.assertEqual(await fetch_requisite_cost(conn, D_FROM, D_TO), 0.0)

    async def test_daily_keys_are_iso_dates(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[{"day": date(2026, 9, 3), "amount": 300.0}])
        out = await fetch_requisite_cost_daily(conn, D_FROM, D_TO)
        self.assertEqual(out, {"2026-09-03": 300.0})

    async def test_daily_survives_missing_table(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(side_effect=RuntimeError("no ledger"))
        self.assertEqual(await fetch_requisite_cost_daily(conn, D_FROM, D_TO), {})


class PoolStatsTests(unittest.IsolatedAsyncioTestCase):
    async def _stats(self, row, card_fee_pct=12.0):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=row)
        return await fetch_requisite_pool_stats(
            conn, D_FROM, D_TO, card_fee_pct=card_fee_pct
        )

    async def test_saving_against_card_provider(self):
        out = await self._stats({"requisites": 4, "turnover": 500000.0, "cost": 5000.0})
        self.assertEqual(out["turnover_rub"], 500000.0)
        self.assertEqual(out["avg_cost_pct"], 1.0)
        self.assertEqual(out["card_fee_cost_rub"], 60000.0)
        self.assertEqual(out["saving_rub"], 55000.0)

    async def test_negative_cost_increases_saving(self):
        out = await self._stats({"requisites": 1, "turnover": 100000.0, "cost": -2000.0})
        self.assertEqual(out["avg_cost_pct"], -2.0)
        self.assertEqual(out["saving_rub"], 14000.0)

    async def test_empty_period_has_no_division(self):
        out = await self._stats({"requisites": 0, "turnover": 0.0, "cost": 0.0})
        self.assertEqual(out["avg_cost_pct"], 0.0)
        self.assertEqual(out["saving_rub"], 0.0)

    async def test_missing_table_returns_empty_shape(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=RuntimeError("no table"))
        out = await fetch_requisite_pool_stats(conn, D_FROM, D_TO, card_fee_pct=12.0)
        self.assertEqual(out, empty_pool_stats(12.0))


class WiringTests(unittest.TestCase):
    def test_pnl_subtracts_requisite_cost(self):
        src = (ROOT / "finance_pnl.py").read_text()
        self.assertIn("fetch_requisite_cost", src)
        self.assertIn('"key": "payout_requisites"', src)
        self.assertIn("+ requisite_cost", src)
        self.assertIn('"payout_requisites": requisite_pool', src)

    def test_daily_costs_include_requisites(self):
        src = (ROOT / "stats_daily_costs.py").read_text()
        self.assertIn("cost_payout_requisites", src)
        self.assertIn("fetch_requisite_cost_daily", src)

    def test_admin_stats_exposes_pool_breakdown(self):
        src = (ROOT / "routers" / "admin_stats.py").read_text()
        self.assertIn("fetch_requisite_pool_stats", src)
        self.assertIn('summary["payout_requisites"]', src)


if __name__ == "__main__":
    unittest.main()
