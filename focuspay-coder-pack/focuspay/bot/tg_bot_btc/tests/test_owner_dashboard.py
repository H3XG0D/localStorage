"""Unit tests for owner dashboard aggregation and stale payout SQL shape."""
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from services.owner_analytics import aggregate_owner_profit
from services.owner_dashboard import format_stale_payout_alert
from services.stats_period import parse_stats_period_arg


class AggregateOwnerProfitTests(unittest.TestCase):
    def test_empty_orders(self):
        count, turnover, profit = aggregate_owner_profit([])
        self.assertEqual(count, 0)
        self.assertEqual(turnover, 0.0)
        self.assertEqual(profit, 0.0)

    def test_buy_profit_uses_service_profit(self):
        orders = [
            {
                "direction": "buy",
                "crypto": "usdt",
                "fiat_amount": 12000,
                "crypto_amount": 100,
                "rate": 120,
                "cashback_applied_rub": 0,
                "card_fee_pct": 0.12,
            }
        ]
        count, turnover, profit = aggregate_owner_profit(orders)
        self.assertEqual(count, 1)
        self.assertEqual(turnover, 12000.0)
        self.assertGreater(profit, 0)


class StatsPeriodTests(unittest.TestCase):
    def test_parse_days(self):
        async def _days(n):
            return []

        async def _date(d):
            return []

        getter, kw = parse_stats_period_arg(
            "7",
            get_paid_for_date=_date,
            get_paid_for_days=_days,
        )
        self.assertFalse(kw["by_date"])
        self.assertEqual(kw["days"], 7)

    def test_parse_date(self):
        async def _days(n):
            return []

        async def _date(d):
            self.assertEqual(d, date(2026, 3, 15))
            return []

        getter, kw = parse_stats_period_arg(
            "15.03.2026",
            get_paid_for_date=_date,
            get_paid_for_days=_days,
        )
        self.assertTrue(kw["by_date"])
        self.assertEqual(kw["date_label"], "15.03.2026")


class StalePayoutAlertTests(unittest.TestCase):
    def test_alert_contains_order_id(self):
        text, kb = format_stale_payout_alert(
            {
                "order_id": "ORD-99",
                "fiat_amount": 5000,
                "crypto": "usdt",
                "crypto_amount": 50,
                "age_minutes": 18,
                "updated_at": None,
            }
        )
        self.assertIn("ORD-99", text)
        self.assertIn("5 000", text)
        self.assertTrue(kb["inline_keyboard"])


class StaleCompletedQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_query_filters_buy_completed(self):
        from services import db
        from unittest.mock import MagicMock

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = ctx

        async def _pool():
            return mock_pool

        with patch.object(db, "get_pool", side_effect=_pool):
            await db.get_stale_completed_buy_orders(10)

        mock_conn.fetch.assert_awaited_once()
        sql = mock_conn.fetch.await_args[0][0]
        self.assertIn("direction = 'buy'", sql)
        self.assertIn("status = 'COMPLETED'", sql)
        self.assertIn("interval '1 minute'", sql)
        self.assertEqual(mock_conn.fetch.await_args[0][1], 10)


if __name__ == "__main__":
    unittest.main()
