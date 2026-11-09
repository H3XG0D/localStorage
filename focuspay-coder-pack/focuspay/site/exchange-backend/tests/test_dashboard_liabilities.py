"""Tests for dashboard project liabilities aggregation."""
import unittest
from unittest.mock import AsyncMock, patch

from routers.admin_dashboard import _build_liabilities


class DashboardLiabilitiesTests(unittest.IsolatedAsyncioTestCase):
    async def test_sections_sum_to_total_without_admin_double_count(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=10_000.0)  # buyers cashback
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"bal": 5_000.0, "pend": 500.0},  # referrers
                {"bal": 100.0, "pend": 10.0},  # external usd
            ]
        )
        conn.fetch = AsyncMock(
            return_value=[{"admins_rub": 20_000.0, "partners_rub": 30_000.0}]
        )

        with patch(
            "routers.admin_dashboard.pool_balance",
            AsyncMock(return_value={"available_rub": 40_000.0}),
        ), patch(
            "routers.admin_dashboard.market_prices_rub",
            AsyncMock(return_value={"usdt": 80.0}),
        ):
            data = await _build_liabilities(conn)

        by_id = {s["id"]: s for s in data["sections"]}
        self.assertEqual(by_id["operators"]["amount_rub"], 40_000.0)
        self.assertEqual(by_id["buyers"]["amount_rub"], 10_000.0)
        self.assertEqual(by_id["referrers"]["amount_rub"], 4_500.0)
        self.assertEqual(by_id["partners"]["amount_rub"], 30_000.0)
        self.assertEqual(by_id["admins"]["amount_rub"], 20_000.0)
        self.assertEqual(by_id["external"]["amount_usd"], 90.0)
        self.assertEqual(by_id["external"]["amount_rub"], 7_200.0)
        expected = 40_000 + 10_000 + 4_500 + 30_000 + 20_000 + 7_200
        self.assertEqual(data["total_rub"], expected)
        self.assertEqual(data["usdt_rub_rate"], 80.0)


if __name__ == "__main__":
    unittest.main()
