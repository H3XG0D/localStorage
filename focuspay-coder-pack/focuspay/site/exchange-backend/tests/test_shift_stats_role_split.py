"""Shift KPIs must include role_split orders and split-line earnings."""
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from payroll_base import stats_for_operator_shift_conn, stats_from_operator_orders, stats_from_orders


class ShiftStatsRoleSplitTests(unittest.IsolatedAsyncioTestCase):
    async def test_stats_for_operator_shift_merges_legacy_and_role_split(self):
        started = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)
        legacy_order = {
            "order_id": "legacy-1",
            "fiat_amount": 1000,
            "crypto": "usdt",
            "direction": "buy",
            "cashback_applied_rub": 0,
            "card_fee_pct": 0,
            "rate": 100,
            "crypto_amount": 10,
            "payroll_model": "legacy",
        }
        role_split_order = {
            "order_id": "split-1",
            "fiat_amount": 5000,
            "payroll_model": "role_split",
        }

        conn = AsyncMock()
        conn.fetch = AsyncMock(
            side_effect=[
                [legacy_order],
                [role_split_order],
            ]
        )
        conn.fetchval = AsyncMock(return_value=42.5)
        conn.fetch.side_effect = None

        async def fetch_side_effect(query, *args):
            if "payroll_model, 'legacy') <> 'role_split'" in query:
                return [legacy_order]
            if "payroll_model, 'legacy') = 'role_split'" in query:
                return [role_split_order]
            if "user_cashback_ledger" in query or "user_referral_ledger" in query:
                return []
            raise AssertionError(f"unexpected query: {query[:120]}")

        conn.fetch = AsyncMock(side_effect=fetch_side_effect)

        stats = await stats_for_operator_shift_conn(conn, 7, started, None, 10.0)

        self.assertEqual(stats["orders_count"], 2)
        self.assertEqual(stats["fiat_total"], 6000.0)
        legacy_earn = stats_from_orders([legacy_order], 10.0, {})["earnings_rub"]
        self.assertEqual(stats["earnings_rub"], round(legacy_earn + 42.5, 2))

    def test_legacy_stats_remain_unchanged_for_non_split_orders(self):
        order = {
            "order_id": "legacy-2",
            "fiat_amount": 2000,
            "crypto": "btc",
            "direction": "sell",
            "cashback_applied_rub": 0,
            "card_fee_pct": 0,
            "rate": 100,
            "crypto_amount": 0.01,
        }
        stats = stats_from_orders([order], 10.0, {})
        self.assertEqual(stats["orders_count"], 1)
        self.assertEqual(stats["fiat_total"], 2000.0)
        self.assertGreater(stats["earnings_rub"], 0)

    def test_operator_orders_merge_legacy_and_role_split_without_percent_on_split(self):
        legacy = {
            "order_id": "legacy-3",
            "fiat_amount": 2000,
            "crypto": "usdt",
            "direction": "buy",
            "cashback_applied_rub": 0,
            "card_fee_pct": 0,
            "rate": 100,
            "crypto_amount": 10,
            "payroll_model": "legacy",
        }
        split = {
            "order_id": "split-3",
            "fiat_amount": 8000,
            "payroll_model": "role_split",
        }
        mixed = stats_from_operator_orders(
            [legacy, split],
            10.0,
            {},
            {"split-3": 55.0},
        )
        legacy_only = stats_from_orders([legacy], 10.0, {})
        self.assertEqual(mixed["orders_count"], 2)
        self.assertEqual(mixed["fiat_total"], 10000.0)
        self.assertEqual(mixed["earnings_rub"], round(legacy_only["earnings_rub"] + 55.0, 2))
        self.assertEqual(mixed["profit_rub"], legacy_only["profit_rub"])


if __name__ == "__main__":
    unittest.main()
