"""Reconciliation / wallet-daily tests for dashboard live API."""
import unittest
from datetime import date as date_cls
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from routers.admin_dashboard import _build_live, _build_wallet_daily


def _bal(shift_id, op_id, started, ended, crypto, start, end, username="op", display="Op"):
    return {
        "shift_id": shift_id,
        "operator_id": op_id,
        "started_at": started,
        "ended_at": ended,
        "username": username,
        "display_name": display,
        "crypto": crypto,
        "balance_start": start,
        "balance_end": end,
    }


class DashboardLiveReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def test_operator_mismatch_when_two_snapshots_differ(self):
        conn = AsyncMock()
        now = datetime.now(timezone.utc)
        conn.fetch = AsyncMock(
            side_effect=[
                [
                    {
                        "shift_id": 10,
                        "operator_id": 1,
                        "started_at": now,
                        "username": "op_a",
                        "display_name": "Operator A",
                        "percent": 10,
                    },
                    {
                        "shift_id": 11,
                        "operator_id": 2,
                        "started_at": now,
                        "username": "op_b",
                        "display_name": "Operator B",
                        "percent": 10,
                    },
                ],
                [
                    {"id": 1, "username": "op_a", "display_name": "Operator A", "on_shift": True},
                    {"id": 2, "username": "op_b", "display_name": "Operator B", "on_shift": True},
                ],
            ]
        )

        async def fake_snapshot(c, op_id):
            if op_id == 1:
                return {"total_rub": 100_000.0, "total_usd": 1200.0}
            return {"total_rub": 95_000.0, "total_usd": 1150.0}

        with patch(
            "routers.admin_dashboard.operator_wallet_snapshot",
            side_effect=fake_snapshot,
        ), patch(
            "routers.admin_dashboard._compute_network_fees",
            AsyncMock(return_value=[]),
        ), patch(
            "routers.admin_dashboard.market_prices_rub",
            AsyncMock(return_value={"usdt": 85.0}),
        ), patch(
            "routers.admin_dashboard.fetch_in_work_by_operator",
            AsyncMock(return_value={}),
        ), patch(
            "routers.admin_dashboard.stats_for_operator_shift_conn",
            AsyncMock(
                return_value={
                    "orders_count": 0,
                    "fiat_total": 0.0,
                    "earnings_rub": 0.0,
                }
            ),
        ):
            data = await _build_live(conn, can_finance=False)

        types = {d["type"] for d in data["wallet"]["discrepancies"]}
        self.assertIn("operator_mismatch", types)
        self.assertEqual(data["wallet"]["total_rub"], 100_000.0)
        self.assertFalse(data["can_view_finance"])
        for op in data["operators"]:
            self.assertIn("turnover", op)
            self.assertNotIn("earnings", op)
            self.assertNotIn("earnings_rub", op)


    async def test_operator_cards_separate_turnover_and_earnings(self):
        conn = AsyncMock()
        now = datetime.now(timezone.utc)
        conn.fetch = AsyncMock(
            side_effect=[
                [
                    {
                        "shift_id": 10,
                        "operator_id": 7,
                        "started_at": now,
                        "username": "rrrrram",
                        "display_name": "Rrrrram",
                        "percent": 15,
                    },
                ],
                [
                    {
                        "id": 7,
                        "username": "rrrrram",
                        "display_name": "Rrrrram",
                        "on_shift": True,
                    },
                ],
            ]
        )

        async def fake_shift_stats(c, op_id, started, ended, percent):
            self.assertEqual(op_id, 7)
            self.assertIsNone(ended)
            self.assertEqual(percent, 15)
            return {
                "orders_count": 3,
                "fiat_total": 85000.0,
                "earnings_rub": 1275.5,
                "service_profit_rub": 9000.0,
                "profit_rub": 8500.0,
                "accruals_rub": 500.0,
            }

        with patch(
            "routers.admin_dashboard.operator_wallet_snapshot",
            AsyncMock(return_value={"total_rub": 12_000.0, "total_usd": 140.0}),
        ), patch(
            "routers.admin_dashboard._compute_network_fees",
            AsyncMock(return_value=[]),
        ), patch(
            "routers.admin_dashboard.market_prices_rub",
            AsyncMock(return_value={"usdt": 85.0}),
        ), patch(
            "routers.admin_dashboard.fetch_in_work_by_operator",
            AsyncMock(
                return_value={7: {"orders_in_work": 2, "in_work_rub": 18000.0}}
            ),
        ), patch(
            "routers.admin_dashboard.stats_for_operator_shift_conn",
            side_effect=fake_shift_stats,
        ), patch(
            "routers.admin_dashboard.pool_balance",
            AsyncMock(
                return_value={
                    "total_rub": 0,
                    "available_rub": 0,
                    "pending_requests_count": 0,
                }
            ),
        ), patch(
            "routers.admin_dashboard._operator_earnings_map",
            AsyncMock(return_value={}),
        ):
            data = await _build_live(conn, can_finance=True)

        self.assertTrue(data["can_view_finance"])
        self.assertEqual(len(data["operators"]), 1)
        card = data["operators"][0]
        self.assertEqual(card["name"], "Rrrrram")
        self.assertTrue(card["on_shift"])
        self.assertEqual(card["orders_in_work"], 2)
        self.assertEqual(card["in_work_rub"], 18000.0)
        self.assertEqual(card["turnover"], 85000.0)
        self.assertEqual(card["fiat_total"], 85000.0)
        self.assertEqual(card["orders_count"], 3)
        self.assertEqual(card["earnings"], 1275.5)
        self.assertEqual(card["earnings_rub"], 1275.5)
        self.assertNotIn("service_profit_rub", card)
        self.assertNotIn("profit_rub", card)

    async def test_missing_earnings_not_replaced_with_zero_without_finance(self):
        conn = AsyncMock()
        now = datetime.now(timezone.utc)
        conn.fetch = AsyncMock(
            side_effect=[
                [
                    {
                        "shift_id": 10,
                        "operator_id": 7,
                        "started_at": now,
                        "username": "rrrrram",
                        "display_name": "Rrrrram",
                        "percent": 15,
                    },
                ],
                [
                    {
                        "id": 7,
                        "username": "rrrrram",
                        "display_name": "Rrrrram",
                        "on_shift": True,
                    },
                ],
            ]
        )
        with patch(
            "routers.admin_dashboard.operator_wallet_snapshot",
            AsyncMock(return_value={"total_rub": 12_000.0, "total_usd": 140.0}),
        ), patch(
            "routers.admin_dashboard._compute_network_fees",
            AsyncMock(return_value=[]),
        ), patch(
            "routers.admin_dashboard.market_prices_rub",
            AsyncMock(return_value={"usdt": 85.0}),
        ), patch(
            "routers.admin_dashboard.fetch_in_work_by_operator",
            AsyncMock(return_value={}),
        ), patch(
            "routers.admin_dashboard.stats_for_operator_shift_conn",
            AsyncMock(
                return_value={
                    "orders_count": 3,
                    "fiat_total": 85000.0,
                    "earnings_rub": 1275.5,
                }
            ),
        ):
            data = await _build_live(conn, can_finance=False)

        card = data["operators"][0]
        self.assertEqual(card["turnover"], 85000.0)
        self.assertNotIn("earnings", card)
        self.assertNotIn("earnings_rub", card)


class DashboardWalletDailyTests(unittest.IsolatedAsyncioTestCase):
    async def test_portfolio_delta_includes_btc_ltc_usdt(self):
        """Выплатили BTC, завели USDT — портфель в $ = сумма монет."""
        conn = AsyncMock()
        started = datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc)
        ended = datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc)
        # BTC 0.01 → 0.005 (−0.005 BTC = −$500), USDT 100 → 600 (+500)
        # LTC flat 1.0
        conn.fetch = AsyncMock(
            return_value=[
                _bal(1, 1, started, ended, "btc", 0.01, 0.005),
                _bal(1, 1, started, ended, "ltc", 1.0, 1.0),
                _bal(1, 1, started, ended, "usdt", 100.0, 600.0),
            ]
        )
        # btc_rub=8_000_000 → 1 BTC = $100_000 at usdt=80
        # ltc_rub=8000 → 1 LTC = $100
        market = {"usdt": 80.0, "btc": 8_000_000.0, "ltc": 8_000.0}

        with patch(
            "routers.admin_dashboard.market_prices_rub",
            AsyncMock(return_value=market),
        ):
            data = await _build_wallet_daily(
                conn, date_cls(2026, 7, 15), date_cls(2026, 7, 15)
            )

        day = data["chart"][0]
        cryptos = {a["crypto"]: a for a in day["assets"]}
        self.assertIn("BTC", cryptos)
        self.assertIn("LTC", cryptos)
        self.assertIn("USDT", cryptos)
        self.assertEqual(cryptos["BTC"]["delta_usd"], -500.0)
        self.assertEqual(cryptos["USDT"]["delta_usd"], 500.0)
        self.assertEqual(cryptos["LTC"]["delta_usd"], 0.0)
        # portfolio flat: −500 BTC +500 USDT
        self.assertEqual(day["delta_usd"], 0.0)
        self.assertEqual(day["total_start_usd"], 1200.0)  # 1000 BTC + 100 LTC + 100 USDT
        self.assertEqual(day["total_end_usd"], 1200.0)  # 500 + 100 + 600

    async def test_day_uses_first_start_and_last_end(self):
        conn = AsyncMock()
        s1 = datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc)
        e1 = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        s2 = datetime(2026, 7, 15, 13, 0, tzinfo=timezone.utc)
        e2 = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
        conn.fetch = AsyncMock(
            return_value=[
                _bal(1, 1, s1, e1, "usdt", 50.0, 70.0, "a", "A"),
                _bal(2, 2, s2, e2, "usdt", 70.0, 40.0, "b", "B"),
            ]
        )

        with patch(
            "routers.admin_dashboard.market_prices_rub",
            AsyncMock(return_value={"usdt": 100.0}),
        ):
            data = await _build_wallet_daily(
                conn, date_cls(2026, 7, 15), date_cls(2026, 7, 15)
            )

        day = data["chart"][0]
        self.assertEqual(day["total_start_usd"], 50.0)
        self.assertEqual(day["total_end_usd"], 40.0)
        self.assertEqual(day["delta_usd"], -10.0)
        self.assertEqual(day["shifts_count"], 2)

    async def test_skip_without_end(self):
        conn = AsyncMock()
        # query filters NULL ends — empty fetch
        conn.fetch = AsyncMock(return_value=[])
        with patch(
            "routers.admin_dashboard.market_prices_rub",
            AsyncMock(return_value={"usdt": 85.0}),
        ):
            data = await _build_wallet_daily(
                conn, date_cls(2026, 7, 15), date_cls(2026, 7, 15)
            )
        self.assertEqual(data["chart"][0]["shifts_count"], 0)


if __name__ == "__main__":
    unittest.main()
