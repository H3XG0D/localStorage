from datetime import datetime, timezone
from unittest import TestCase

from routers.admin_stats import build_traffic_stats


class AdminTrafficStatsTests(TestCase):
    def test_aggregates_complete_result_set_in_moscow_time(self):
        rows = [
            {
                "status": "PAID",
                "fiat_amount": 999.99,
                "created_at": datetime(2026, 9, 1, 21, 30),  # 00:30 MSK
                "order_source": None,
            },
            {
                "status": "COMPLETED",
                "fiat_amount": 1_000,
                "created_at": datetime(2026, 9, 1, 22, 30, tzinfo=timezone.utc),  # 01:30 MSK
                "order_source": "site",
            },
            {
                "status": "PENDING",
                "fiat_amount": 100_000,
                "created_at": datetime(2026, 9, 1, 23, 30),  # 02:30 MSK
                "order_source": "",
            },
        ]

        stats = build_traffic_stats(rows)

        self.assertEqual(stats["summary"], {
            "orders": 3,
            "fiat_sum": 101_999.99,
            "paid_orders": 2,
            "paid_fiat_sum": 1_999.99,
        })
        self.assertEqual(len(stats["by_hour"]), 24)
        self.assertEqual(stats["by_hour"][0], {"hour": 0, "orders": 1, "fiat_sum": 999.99, "paid_orders": 1, "paid_fiat_sum": 999.99})
        self.assertEqual(stats["by_hour"][1], {"hour": 1, "orders": 1, "fiat_sum": 1000.0, "paid_orders": 1, "paid_fiat_sum": 1000.0})
        self.assertEqual(stats["by_hour"][2], {"hour": 2, "orders": 1, "fiat_sum": 100000.0, "paid_orders": 0, "paid_fiat_sum": 0.0})
        self.assertEqual(stats["amount_buckets"][0], {"key": "0-1", "orders": 1, "fiat_sum": 999.99})
        self.assertEqual(stats["amount_buckets"][1], {"key": "1-2", "orders": 1, "fiat_sum": 1000.0})
        self.assertEqual(stats["amount_buckets"][-1], {"key": "100+", "orders": 1, "fiat_sum": 100000.0})
        self.assertEqual(stats["by_source"], [
            {"source": "manual", "orders": 2, "fiat_sum": 100999.99},
            {"source": "site", "orders": 1, "fiat_sum": 1000.0},
        ])

    def test_keeps_empty_hours_and_all_amount_buckets(self):
        stats = build_traffic_stats([])

        self.assertEqual(stats["summary"], {"orders": 0, "fiat_sum": 0.0, "paid_orders": 0, "paid_fiat_sum": 0.0})
        self.assertEqual(len(stats["by_hour"]), 24)
        self.assertTrue(all(row["orders"] == 0 for row in stats["by_hour"]))
        self.assertEqual([row["key"] for row in stats["amount_buckets"]], [
            "0-1", "1-2", "2-3", "3-5", "5-10", "10-25", "25-50", "50-100", "100+",
        ])
