"""Legacy economics backfill locks only closed orders."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import backfill_order_economics_snapshots as backfill_module


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.fetchval = AsyncMock(return_value=len(rows))
        self.execute = AsyncMock(return_value="UPDATE 1")
        self.closed = False

    def transaction(self):
        return _Transaction()

    async def fetch(self, query, batch_size):
        self.query = query
        if not self.rows:
            return []
        rows, self.rows = self.rows, []
        return rows

    async def close(self):
        self.closed = True


class LegacyEconomicsBackfillTests(unittest.TestCase):
    def test_dry_run_counts_only_closed_orders_without_snapshots(self):
        conn = _Connection([])
        conn.fetchval = AsyncMock(return_value=3)

        with patch.object(backfill_module.asyncpg, "connect", new=AsyncMock(return_value=conn)):
            count = asyncio.run(backfill_module.backfill(dsn="postgres://test", apply=False, batch_size=10))

        self.assertEqual(count, 3)
        self.assertIn("status IN ('PAID', 'COMPLETED')", conn.fetchval.call_args.args[0])
        self.assertIn("economics_snapshot IS NULL", conn.fetchval.call_args.args[0])
        self.assertTrue(conn.closed)

    def test_apply_writes_legacy_snapshot_for_closed_rows(self):
        conn = _Connection([
            {
                "order_id": "order-1",
                "direction": "buy",
                "crypto": "usdt",
                "fiat_amount": 1200,
                "crypto_amount": 10,
                "rate": 120,
                "cashback_applied_rub": 0,
                "card_fee_pct": 0.1,
            }
        ])

        with patch.object(backfill_module.asyncpg, "connect", new=AsyncMock(return_value=conn)), patch(
            "backfill_order_economics_snapshots.build_economics_snapshot",
            return_value={"formula_version": "legacy_locked_v1", "service_profit_rub": 80.0},
        ):
            count = asyncio.run(backfill_module.backfill(dsn="postgres://test", apply=True, batch_size=10))

        self.assertEqual(count, 1)
        self.assertIn("status IN ('PAID', 'COMPLETED')", conn.query)
        self.assertIn("FOR UPDATE SKIP LOCKED", conn.query)
        snapshot_json = conn.execute.call_args.args[2]
        self.assertIn('"formula_version": "legacy_locked_v1"', snapshot_json)
        self.assertIn('"locked_at"', snapshot_json)
        self.assertTrue(conn.closed)


if __name__ == "__main__":
    unittest.main()
