from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from scripts import snapshot_capital


class CurrentShiftBalanceTests(unittest.TestCase):
    def test_formula_includes_flows_and_issuance(self):
        result = snapshot_capital.current_shift_balance(
            balance_start="100",
            sent_in_buy="20.5",
            recv_in_sell="7.25",
            issued="10",
        )

        self.assertEqual(result, Decimal("96.75"))


class ActiveShiftBalancesTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_current_balances_computed_by_query(self):
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"crypto": "usdt", "current_balance": Decimal("91.5")},
            {"crypto": "BTC", "current_balance": Decimal("0.25")},
        ]
        at = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)

        balances = await snapshot_capital.get_active_shift_balances(conn, at)

        self.assertEqual(
            balances,
            {"usdt": Decimal("91.5"), "btc": Decimal("0.25")},
        )
        sql = conn.fetch.await_args.args[0]
        self.assertIn("balance_start", sql)
        self.assertIn("LOWER(o.direction) = 'buy'", sql)
        self.assertIn("LOWER(o.direction) = 'sell'", sql)
        self.assertIn("operator_usdt_issuances", sql)
        self.assertNotIn("SUM(osb.balance_start) AS total_balance", sql)
        self.assertEqual(conn.fetch.await_args.args[1], at)


class CapitalComputationTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_gross_assets_liabilities_and_net_capital(self):
        at = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
        balances = {"usdt": Decimal("10"), "btc": Decimal("0.01")}
        rates = {
            "usdt": Decimal("100"),
            "btc": Decimal("10000000"),
            "trx": Decimal("20"),
            "ltc": Decimal("10000"),
        }
        liabilities = {
            "total_rub": 25000.25,
            "sections": [{"id": "operators", "amount_rub": 25000.25}],
        }

        with (
            patch.object(snapshot_capital, "get_active_shift_balances", AsyncMock(return_value=balances)),
            patch.object(snapshot_capital, "get_crypto_rates", AsyncMock(return_value=rates)),
            patch.object(snapshot_capital, "get_liabilities", AsyncMock(return_value=liabilities)),
        ):
            result = await snapshot_capital.compute_capital_snapshot(AsyncMock(), at)

        self.assertEqual(result["gross_assets_rub"], 101000.0)
        self.assertEqual(result["liabilities_rub"], 25000.25)
        self.assertEqual(result["net_capital_rub"], 75999.75)
        self.assertEqual(result["metadata"]["gross_assets"]["crypto"]["usdt"]["balance"], 10.0)
        self.assertEqual(result["metadata"]["liabilities"]["sections"], liabilities["sections"])


class SaveSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_insert_matches_ledger_columns_and_stores_net_amount(self):
        conn = AsyncMock()
        conn.fetchval.return_value = 42
        at = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
        data = {
            "net_capital_rub": 75999.75,
            "metadata": {"gross_assets": {"total_rub": 101000.0}, "liabilities": {"total_rub": 25000.25}},
            "note": "Automated net capital snapshot",
        }

        entry_id = await snapshot_capital.save_capital_snapshot(conn, at, data)

        self.assertEqual(entry_id, 42)
        args = conn.fetchval.await_args.args
        self.assertIn("occurred_at, entry_type, amount, currency", args[0])
        self.assertNotIn("metadata", args[0])
        self.assertEqual(args[2], "capital_snapshot")
        self.assertEqual(args[3], Decimal("75999.75"))
        self.assertEqual(json.loads(args[6]), data["metadata"])


class CliLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_initializes_and_closes_backend_pool(self):
        conn = AsyncMock()
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire
        snapshot = {
            "gross_assets_rub": 100.0,
            "liabilities_rub": 20.0,
            "net_capital_rub": 80.0,
            "metadata": {"gross_assets": {"crypto": {}}},
            "note": "Automated net capital snapshot",
        }

        with (
            patch("db.init_db", new=AsyncMock()) as init_db,
            patch("db.get_pool", new=AsyncMock(return_value=pool)),
            patch("db.close_db", new=AsyncMock()) as close_db,
            patch.object(snapshot_capital, "compute_capital_snapshot", AsyncMock(return_value=snapshot)),
        ):
            code = await snapshot_capital.run(["--dry-run"])

        self.assertEqual(code, 0)
        init_db.assert_awaited_once()
        close_db.assert_awaited_once()

    async def test_closes_pool_when_snapshot_fails(self):
        pool = MagicMock()
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(side_effect=RuntimeError("boom"))
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool.acquire.return_value = acquire

        with (
            patch("db.init_db", new=AsyncMock()),
            patch("db.get_pool", new=AsyncMock(return_value=pool)),
            patch("db.close_db", new=AsyncMock()) as close_db,
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                await snapshot_capital.run(["--dry-run"])

        close_db.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
