"""Периодическая статистика внештатных обменов."""
import unittest
from datetime import date
from unittest.mock import AsyncMock

from external_exchange_stats import (
    empty_period_summary,
    empty_stats,
    fetch_exchanger_ops_stats,
    fetch_exchanger_period_daily,
    fetch_exchanger_period_stats,
    fetch_history,
    fetch_period_summary,
    stats_from_row,
)


class ExternalPeriodSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_period_summary_converts_payout_fee(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "deal_count": 2,
                "turnover_base_rub": 10000.0,
                "turnover_client_rub": 12000.0,
                "deal_profit_usd": 5.5,
                "deal_profit_rub": 495.0,
                "payout_count": 1,
                "payout_fee_usd": 3.0,
            }
        )
        result = await fetch_period_summary(
            conn, date(2026, 7, 1), date(2026, 7, 5), usdt_rub_rate=90.0
        )
        self.assertEqual(result["deal_count"], 2)
        self.assertEqual(result["house_profit_usd"], 8.5)
        self.assertEqual(result["payout_fee_rub"], 270.0)
        self.assertEqual(result["house_profit_rub"], 765.0)

    def test_empty_period_summary(self):
        e = empty_period_summary()
        self.assertEqual(e["house_profit_usd"], 0.0)
        self.assertEqual(e["deal_count"], 0)

    async def test_fetch_history_maps_deal_fields(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=2)
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "kind": "deal",
                    "id": 7,
                    "at": "2026-07-05T12:00:00",
                    "amount_rub": 1000.0,
                    "client_pays_rub": 1200.0,
                    "amount_usd": 10.0,
                    "house_profit_usd": 1.2,
                    "house_profit_rub": 108.0,
                    "crypto": "usdt",
                    "note": None,
                    "created_by": "admin",
                    "status": "pending",
                    "merchant_order_id": "m-1",
                    "payfast_fee_rub": 144.0,
                    "operator_earnings_rub": 20.0,
                    "has_receipt": True,
                    "gross_usd": None,
                    "net_usd": None,
                    "fee_usd": None,
                    "crypto_amount": None,
                    "principal_usdt": 9.0,
                    "reward_usdt": 1.0,
                    "net_profit_rub": 160.0,
                }
            ]
        )
        items, total = await fetch_history(conn, 1, limit=50, offset=0)
        self.assertEqual(total, 2)
        self.assertEqual(items[0]["status"], "pending")
        self.assertTrue(items[0]["has_receipt"])
        self.assertEqual(items[0]["house_profit_rub"], 108.0)
        self.assertEqual(items[0]["merchant_order_id"], "m-1")

    async def test_fetch_history_passes_date_range(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=0)
        conn.fetch = AsyncMock(return_value=[])
        await fetch_history(
            conn, 9, date_from=date(2026, 8, 1), date_to=date(2026, 8, 21)
        )
        count_args = conn.fetchval.call_args[0]
        self.assertEqual(count_args[1], 9)
        self.assertEqual(count_args[2], date(2026, 8, 1))
        self.assertEqual(count_args[3], date(2026, 8, 21))
        self.assertIn("d.created_at::date >= $2", count_args[0])
        list_args = conn.fetch.call_args[0]
        self.assertEqual(list_args[-2:], (50, 0))
        self.assertIn("LIMIT $4 OFFSET $5", list_args[0])


class ExchangerOpsStatsTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_exchanger_ops_stats(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "confirmed_count": 5,
                "failed_count": 1,
                "total_turnover_rub": 25000.0,
                "last_confirmed_at": None,
            }
        )
        result = await fetch_exchanger_ops_stats(conn, 3)
        self.assertEqual(result["confirmed_count"], 5)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["conversion_pct"], 83.3)
        self.assertEqual(result["total_turnover_rub"], 25000.0)
        self.assertIsNone(result["last_confirmed_at"])


class ExchangerPeriodStatsTests(unittest.IsolatedAsyncioTestCase):
    def test_stats_from_row_status_counts(self):
        stats = stats_from_row(
            {
                "balance_usd": 12.5,
                "deal_count": 4,
                "payout_count": 1,
                "turnover_base_rub": 1000,
                "turnover_client_rub": 1200,
                "total_credited_usd": 10,
                "total_paid_out_usd": 3,
                "deal_profit_usd": 1.5,
                "payout_fee_usd": 0.5,
                "last_deal_at": None,
                "last_payout_at": None,
                "deals_confirmed": 4,
                "deals_failed": 2,
                "deals_awaiting": 1,
                "deals_pending": 3,
                "deals_cancelled": 2,
            }
        )
        self.assertEqual(stats["deals_open"], 4)
        self.assertEqual(stats["deals_cancelled"], 2)
        self.assertEqual(stats["conversion_pct"], 66.7)
        self.assertEqual(stats["house_profit_usd"], 2.0)
        self.assertEqual(empty_stats()["deals_open"], 0)

    async def test_fetch_exchanger_period_stats(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "deal_count": 3,
                "deals_confirmed": 3,
                "deals_failed": 1,
                "deals_awaiting": 0,
                "deals_pending": 2,
                "deals_cancelled": 1,
                "payout_count": 1,
                "turnover_base_rub": 9000.0,
                "turnover_client_rub": 10800.0,
                "total_credited_usd": 90.0,
                "total_paid_out_usd": 40.0,
                "deal_profit_usd": 4.0,
                "payout_fee_usd": 3.0,
                "last_deal_at": None,
                "last_payout_at": None,
                "balance_usd": 0.0,
            }
        )
        result = await fetch_exchanger_period_stats(
            conn, 4, date(2026, 8, 1), date(2026, 8, 21)
        )
        self.assertEqual(result["deal_count"], 3)
        self.assertEqual(result["deals_cancelled"], 1)
        self.assertEqual(result["deals_open"], 2)
        self.assertEqual(result["house_profit_usd"], 7.0)
        conn.fetchrow.assert_awaited_once()
        self.assertEqual(
            conn.fetchrow.call_args[0][1:],
            (4, date(2026, 8, 1), date(2026, 8, 21)),
        )

    async def test_fetch_exchanger_period_daily(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "day": date(2026, 8, 10),
                    "deal_profit_usd": 1.25,
                    "turnover_rub": 5000.0,
                    "deal_count": 2,
                    "cancelled_count": 1,
                }
            ]
        )
        rows = await fetch_exchanger_period_daily(
            conn, 4, date(2026, 8, 1), date(2026, 8, 21)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-08-10")
        self.assertEqual(rows[0]["deal_count"], 2)
        self.assertEqual(rows[0]["cancelled_count"], 1)
        self.assertEqual(rows[0]["profit_usd"], 1.25)


if __name__ == "__main__":
    unittest.main()
