"""Historical BUY reprice policy and audit behaviour."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import reprice_closed_buy_economics as reprice


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Connection:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []
        self.closed = False

    def transaction(self):
        return _Transaction()

    async def fetch(self, query, *params):
        self.last_fetch_query = query
        self.last_fetch_params = params
        if "order_economics_snapshot_revisions" in query:
            return []
        after_id = int(params[0]) if len(params) == 2 else 0
        batch_size = int(params[-1]) if params else len(self.rows)
        return [row for row in self.rows if row["id"] > after_id][:batch_size]

    async def execute(self, query, *params):
        self.executed.append((query, params))
        if "INSERT INTO order_economics_snapshot_revisions" in query:
            return "INSERT 0 1"
        if "UPDATE orders" in query:
            return "UPDATE 1"
        return "UPDATE 1"

    async def close(self):
        self.closed = True


def _order(*, order_id="buy-1", created_at, source="site", fee=0.12, manual_spread=None):
    return {
        "id": int(order_id.rsplit("-", 1)[-1]) if order_id.rsplit("-", 1)[-1].isdigit() else 1,
        "order_id": order_id,
        "direction": "buy",
        "crypto": "usdt",
        "fiat_amount": 1200,
        "crypto_amount": 10,
        "rate": 120,
        "cashback_applied_rub": 50,
        "card_fee_pct": fee,
        "economics_snapshot": {"service_profit_rub": 80, "formula_version": "legacy_locked_v1"},
        "created_at": created_at,
        "order_source": source,
        "manual_spread_pct": manual_spread,
        "merchant_order_id": "merchant-1",
        "payment_snapshot": {"merchant_uuid": "uuid"},
    }


class RepricePolicyTests(unittest.TestCase):
    def test_pre_cutoff_buy_uses_twenty_percent(self):
        policy, markup = reprice.reprice_policy(
            _order(created_at=datetime(2026, 8, 16, 20, tzinfo=timezone.utc))
        )
        self.assertEqual(policy, reprice.POLICY_HISTORICAL_20)
        self.assertEqual(markup, 1.20)

    def test_recent_auto_buy_uses_twenty_one_percent(self):
        policy, markup = reprice.reprice_policy(
            _order(created_at=datetime(2026, 8, 17, tzinfo=timezone.utc), fee=0.12)
        )
        self.assertEqual(policy, reprice.POLICY_RECENT_AUTO_21)
        self.assertEqual(markup, 1.21)

    def test_recent_operator_fallback_uses_twenty_two_percent(self):
        policy, markup = reprice.reprice_policy(
            _order(
                created_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
                source="site",
                fee=0.14,
            )
        )
        self.assertEqual(policy, reprice.POLICY_RECENT_MANUAL_22)
        self.assertEqual(markup, 1.22)

    def test_historical_intermediate_fee_uses_the_nearest_origin(self):
        auto_policy, auto_markup = reprice.reprice_policy(
            _order(created_at=datetime(2026, 8, 17, tzinfo=timezone.utc), fee=0.125)
        )
        manual_policy, manual_markup = reprice.reprice_policy(
            _order(created_at=datetime(2026, 8, 17, tzinfo=timezone.utc), fee=0.135)
        )

        self.assertEqual((auto_policy, auto_markup), (reprice.POLICY_RECENT_AUTO_21, 1.21))
        self.assertEqual((manual_policy, manual_markup), (reprice.POLICY_RECENT_MANUAL_22, 1.22))

    def test_manual_operator_individual_spread_is_excluded(self):
        policy, markup = reprice.reprice_policy(
            _order(
                created_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
                source="manual_operator",
                fee=0.14,
                manual_spread=18,
            )
        )
        self.assertEqual(policy, reprice.POLICY_MANUAL_OPERATOR_EXCLUDED)
        self.assertIsNone(markup)

    def test_rebuilt_snapshot_preserves_final_amounts_cashback_and_fee(self):
        order = _order(created_at=datetime(2026, 8, 16, tzinfo=timezone.utc), fee=0.14)
        snapshot = reprice.rebuilt_snapshot(
            order,
            policy=reprice.POLICY_HISTORICAL_20,
            markup=1.20,
            run_id="repr-1",
        )
        self.assertEqual(snapshot["buy_markup"], 1.20)
        self.assertEqual(snapshot["card_fee_pct"], 0.14)
        self.assertEqual(snapshot["cashback_applied_rub"], 50)
        self.assertEqual(snapshot["market_rate"], 100)
        self.assertEqual(snapshot["reprice_run_id"], "repr-1")


class _RollbackConnection:
    def __init__(self, *, update_result="UPDATE 1"):
        self.update_result = update_result
        self.executed = []
        self.closed = False
        self.rows = [
            {
                "order_id": "buy-1",
                "old_snapshot": {"formula_version": "legacy_locked_v1"},
                "new_snapshot": {"formula_version": "repriced_buy_v1"},
            }
        ]

    def transaction(self):
        return _Transaction()

    async def fetch(self, query, *params):
        if self.rows:
            rows, self.rows = self.rows, []
            return rows
        return []

    async def execute(self, query, *params):
        self.executed.append((query, params))
        if "UPDATE orders" in query:
            return self.update_result
        return "UPDATE 1"

    async def close(self):
        self.closed = True


class RepriceApplyTests(unittest.TestCase):
    def test_apply_writes_revision_before_snapshot_update(self):
        conn = _Connection([
            _order(order_id="buy-1", created_at=datetime(2026, 8, 16, tzinfo=timezone.utc)),
            _order(
                order_id="buy-2",
                created_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
                source="manual_operator",
                manual_spread=18,
                fee=0.14,
            ),
        ])
        with patch.object(reprice.asyncpg, "connect", new=AsyncMock(return_value=conn)):
            result = asyncio.run(reprice.apply(dsn="postgres://test", run_id="repr-1", batch_size=10))

        self.assertEqual(result["updated"], 1)
        self.assertEqual(result[reprice.POLICY_MANUAL_OPERATOR_EXCLUDED], 1)
        self.assertIn("FOR UPDATE SKIP LOCKED", conn.last_fetch_query)
        revision_index = next(
            index for index, (query, _) in enumerate(conn.executed)
            if "INSERT INTO order_economics_snapshot_revisions" in query
        )
        update_index = next(
            index for index, (query, _) in enumerate(conn.executed)
            if "UPDATE orders" in query
        )
        self.assertLess(revision_index, update_index)
        self.assertTrue(conn.closed)

    def test_dry_run_reports_exclusions_without_writes(self):
        conn = _Connection([
            _order(
                created_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
                source="manual_operator",
                manual_spread=18,
            )
        ])
        with patch.object(reprice.asyncpg, "connect", new=AsyncMock(return_value=conn)):
            result = asyncio.run(reprice.dry_run(dsn="postgres://test", run_id="dry-run"))

        self.assertEqual(result["candidates"], 0)
        self.assertEqual(result["excluded"], 1)
        self.assertFalse(conn.executed)
        self.assertTrue(conn.closed)

    def test_apply_skips_a_duplicate_revision_for_same_run(self):
        conn = _Connection([
            _order(order_id="buy-1", created_at=datetime(2026, 8, 16, tzinfo=timezone.utc))
        ])

        async def execute(query, *params):
            conn.executed.append((query, params))
            if "INSERT INTO order_economics_snapshot_revisions" in query:
                return "INSERT 0 0"
            return "UPDATE 1"

        conn.execute = execute
        with patch.object(reprice.asyncpg, "connect", new=AsyncMock(return_value=conn)):
            result = asyncio.run(reprice.apply(dsn="postgres://test", run_id="repr-1", batch_size=10))

        self.assertEqual(result["already_revised"], 1)
        self.assertNotIn("updated", result)
        self.assertFalse(any("UPDATE orders" in query for query, _ in conn.executed))

    def test_apply_deletes_new_revision_when_snapshot_changed_concurrently(self):
        conn = _Connection([
            _order(order_id="buy-1", created_at=datetime(2026, 8, 16, tzinfo=timezone.utc))
        ])

        async def execute(query, *params):
            conn.executed.append((query, params))
            if "UPDATE orders" in query:
                return "UPDATE 0"
            return "INSERT 0 1" if "INSERT INTO" in query else "DELETE 1"

        conn.execute = execute
        with patch.object(reprice.asyncpg, "connect", new=AsyncMock(return_value=conn)):
            result = asyncio.run(reprice.apply(dsn="postgres://test", run_id="repr-1", batch_size=10))

        self.assertEqual(result["concurrent_change"], 1)
        statements = [query for query, _ in conn.executed]
        self.assertTrue(any("DELETE FROM order_economics_snapshot_revisions" in query for query in statements))


class RepriceRollbackTests(unittest.TestCase):
    def test_rollback_restores_old_snapshot_and_keeps_revision(self):
        conn = _RollbackConnection()
        with patch.object(reprice.asyncpg, "connect", new=AsyncMock(return_value=conn)):
            result = asyncio.run(reprice.rollback(dsn="postgres://test", run_id="repr-1", batch_size=10))

        self.assertEqual(result["restored"], 1)
        statements = [query for query, _ in conn.executed]
        self.assertTrue(any("UPDATE orders" in query for query in statements))
        self.assertTrue(any("SET reverted_at = now()" in query for query in statements))
        self.assertFalse(any("DELETE FROM order_economics_snapshot_revisions" in query for query in statements))
        self.assertTrue(conn.closed)

    def test_rollback_preserves_a_subsequent_snapshot_change(self):
        conn = _RollbackConnection(update_result="UPDATE 0")
        with patch.object(reprice.asyncpg, "connect", new=AsyncMock(return_value=conn)):
            result = asyncio.run(reprice.rollback(dsn="postgres://test", run_id="repr-1", batch_size=10))

        self.assertEqual(result["skipped_changed"], 1)
        statements = [query for query, _ in conn.executed]
        self.assertTrue(any("SET rollback_skipped_at = now()" in query for query in statements))


if __name__ == "__main__":
    unittest.main()
