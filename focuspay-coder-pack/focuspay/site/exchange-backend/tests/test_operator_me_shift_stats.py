"""Regression coverage for role-aware KPIs returned by GET /operator/me."""
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from routers.operator import operator_me


class OperatorMeShiftStatsTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_shift_uses_role_aware_stats(self):
        started_at = datetime(2026, 8, 21, 20, 45, tzinfo=timezone.utc)
        shift_row = {
            "id": 203,
            "operator_id": 6,
            "started_at": started_at,
            "ended_at": None,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                shift_row,
                {"orders_count": 7, "fiat_total": 24245},
            ]
        )

        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=conn)
        context.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = context

        async def get_pool():
            return pool

        shift_stats = AsyncMock(
            return_value={
                "orders_count": 7,
                "fiat_total": 24245.0,
                "earnings_rub": 374.89,
                "service_profit_rub": 999.0,
                "accruals_rub": 10.0,
                "profit_rub": 989.0,
            }
        )
        legacy_stats = AsyncMock()
        shift_orders = AsyncMock()
        operator = {
            "id": 6,
            "username": "operator",
            "percent": 10,
        }

        hourly_preview = AsyncMock(
            return_value={
                "open": True,
                "applies": True,
                "rate_rub": 220.0,
                "forecast_rub": 18.33,
                "started_at": started_at.isoformat(),
            }
        )
        with patch("routers.operator.get_pool", new=get_pool), patch(
            "routers.operator._team_snapshot",
            new=AsyncMock(return_value={"on_shift": [], "on_shift_count": 0}),
        ), patch("routers.operator._queue_count", new=AsyncMock(return_value=0)), patch(
            "routers.operator._active_work_count", new=AsyncMock(return_value=0)
        ), patch(
            "routers.operator.stats_for_operator_shift_conn", new=shift_stats
        ), patch(
            "routers.operator.stats_from_orders_conn", new=legacy_stats
        ), patch(
            "routers.operator._shift_orders", new=shift_orders
        ), patch(
            "routers.operator._load_shift_balances", new=AsyncMock(return_value=[])
        ), patch(
            "operator_hourly_pay.open_shift_hourly_preview", new=hourly_preview
        ), patch(
            "routers.operator.operator_public_dict",
            new=lambda op: {"id": op["id"], "username": op["username"]},
        ):
            result = await operator_me(op=operator)

        shift_stats.assert_awaited_once_with(conn, 6, started_at, None, 10.0)
        legacy_stats.assert_not_awaited()
        shift_orders.assert_not_awaited()
        hourly_preview.assert_awaited_once_with(conn, 6)
        self.assertEqual(
            result["current_shift"],
            {
                "orders_count": 7,
                "fiat_total": 24245.0,
                "deal_earnings_rub": 374.89,
                "hourly_applies": True,
                "hourly_forecast_rub": 18.33,
                "hourly_rate_rub": 220.0,
                "earnings_rub": 393.22,
            },
        )


if __name__ == "__main__":
    unittest.main()
