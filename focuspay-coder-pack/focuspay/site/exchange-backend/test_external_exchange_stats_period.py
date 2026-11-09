"""Периодическая статистика внештатных обменов."""
import unittest
from datetime import date
from unittest.mock import AsyncMock

from external_exchange_stats import (
    empty_period_summary,
    fetch_history,
    fetch_period_summary,
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


if __name__ == "__main__":
    unittest.main()
