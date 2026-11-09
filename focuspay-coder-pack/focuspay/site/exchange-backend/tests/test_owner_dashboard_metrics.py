"""Owner dashboard period bounds, deltas, empty ledger, auth surface."""
from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from owner_dashboard_metrics import (
    PERIOD_KEYS,
    _count_bot_new,
    _count_new_partners,
    _count_web_new,
    _delta,
    _expense_lines_from_pnl,
    _int_delta,
    _money_from_pnl,
    _orders_from_pnl,
    build_owner_dashboard,
    resolve_period_window,
)


class PeriodWindowTests(unittest.TestCase):
    def test_today_vs_yesterday(self):
        w = resolve_period_window("today", today=date(2026, 8, 12))
        self.assertEqual(w.current_from, date(2026, 8, 12))
        self.assertEqual(w.previous_from, date(2026, 8, 11))
        self.assertEqual(w.timezone, "Europe/Moscow")
        self.assertEqual(w.week_starts_on, "monday")

    def test_yesterday(self):
        w = resolve_period_window("yesterday", today=date(2026, 8, 12))
        self.assertEqual(w.current_from, date(2026, 8, 11))
        self.assertEqual(w.previous_from, date(2026, 8, 10))

    def test_week_starts_monday(self):
        # 2026-08-12 is Wednesday → Mon 10 Aug → today
        w = resolve_period_window("week", today=date(2026, 8, 12))
        self.assertEqual(w.current_from, date(2026, 8, 10))
        self.assertEqual(w.current_to, date(2026, 8, 12))
        self.assertEqual(w.previous_from, date(2026, 8, 3))
        self.assertEqual(w.previous_to, date(2026, 8, 5))

    def test_month_rolling_30_on_first(self):
        # 2026-09-01 → last 30 days, not calendar MTD (which would be 1 day).
        w = resolve_period_window("month", today=date(2026, 9, 1))
        self.assertEqual(w.current_from, date(2026, 8, 3))
        self.assertEqual(w.current_to, date(2026, 9, 1))
        self.assertEqual(w.previous_from, date(2026, 7, 4))
        self.assertEqual(w.previous_to, date(2026, 8, 2))

    def test_month_rolling_30_mid_month(self):
        w = resolve_period_window("month", today=date(2026, 3, 31))
        self.assertEqual(w.current_from, date(2026, 3, 2))
        self.assertEqual(w.current_to, date(2026, 3, 31))
        self.assertEqual(w.previous_from, date(2026, 1, 31))
        self.assertEqual(w.previous_to, date(2026, 3, 1))

    def test_year(self):
        w = resolve_period_window("year", today=date(2026, 8, 12))
        self.assertEqual(w.current_from, date(2026, 1, 1))
        self.assertEqual(w.previous_from, date(2025, 1, 1))
        self.assertEqual(w.previous_to, date(2025, 8, 12))

    def test_invalid_period(self):
        with self.assertRaises(ValueError):
            resolve_period_window("decade")


class DeltaTests(unittest.TestCase):
    def test_pct_when_previous_zero(self):
        d = _delta(100.0, 0.0)
        self.assertEqual(d["abs_change"], 100.0)
        self.assertIsNone(d["pct_change"])

    def test_pct_normal(self):
        d = _delta(150.0, 100.0)
        self.assertEqual(d["pct_change"], 50.0)

    def test_int_delta_zero_previous(self):
        d = _int_delta(5, 0)
        self.assertIsNone(d["pct_change"])
        self.assertEqual(d["abs_change"], 5)


class PnlMappingTests(unittest.TestCase):
    def test_orders_exclude_external(self):
        pnl = {
            "by_type": [
                {"type": "auto_buy", "orders": 3},
                {"type": "sell", "orders": 2},
                {"type": "external", "orders": 99},
                {"type": "casino", "orders": 77},
            ]
        }
        self.assertEqual(_orders_from_pnl(pnl), 5)

    def test_money_maps_owner_residual_as_net(self):
        pnl = {
            "by_type": [{"type": "auto_buy", "orders": 1}],
            "total": {
                "net_profit": 1000.0,
                "fiat_volume": 50000.0,
                "profit_after_costs": 800.0,
            },
            "payroll": {
                "owner_residual": 420.0,
                "operators_total": 100.0,
                "admin_salary": 50.0,
            },
            "costs": {"total": 200.0},
            "manual_expenses": {"total": 30.0},
        }
        m = _money_from_pnl(pnl)
        self.assertEqual(m["net_income_rub"], 420.0)
        self.assertEqual(m["gross_commissions_rub"], 1000.0)
        self.assertEqual(m["turnover_rub"], 50000.0)
        self.assertEqual(m["orders"], 1)


class ExpenseLinesTests(unittest.TestCase):
    def test_sums_waterfall_expenses_and_skips_noise(self):
        pnl = {
            "waterfall": [
                {"key": "margin", "label": "Маржа", "amount": 1000.0, "kind": "income"},
                {"key": "cashback", "label": "Кешбэк", "amount": -40.0, "kind": "expense"},
                {"key": "payroll", "label": "ЗП операторов", "amount": -100.5, "kind": "expense"},
                {"key": "dust", "label": "Пыль", "amount": -0.001, "kind": "expense"},
                {"key": "owner_residual", "label": "Остаток", "amount": 420.0, "kind": "total"},
            ]
        }
        total, lines = _expense_lines_from_pnl(pnl)
        self.assertEqual(total, 140.5)
        self.assertEqual(
            lines,
            [
                {"key": "cashback", "label": "Кешбэк", "amount_rub": 40.0},
                {"key": "payroll", "label": "ЗП операторов", "amount_rub": 100.5},
            ],
        )

    def test_empty_when_no_expense_rows(self):
        total, lines = _expense_lines_from_pnl({"waterfall": []})
        self.assertEqual(total, 0.0)
        self.assertEqual(lines, [])


class AudienceCountArgsTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_web_partner_counts_pass_from_and_to(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=3)
        d_from, d_to = date(2026, 8, 10), date(2026, 8, 12)
        self.assertEqual(await _count_bot_new(conn, d_from, d_to), 3)
        self.assertEqual(await _count_web_new(conn, d_from, d_to), 3)
        self.assertEqual(await _count_new_partners(conn, d_from, d_to), 3)
        for call in conn.fetchval.await_args_list:
            sql = call.args[0]
            self.assertIn("$1", sql)
            self.assertIn("$2", sql)
            self.assertEqual(list(call.args[1:]), [d_from, d_to])


class BuildOwnerDashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_ledger_not_fake_zeros(self):
        fake_pnl = {
            "by_type": [{"type": "auto_buy", "orders": 0}],
            "total": {
                "net_profit": 0.0,
                "fiat_volume": 0.0,
                "profit_after_costs": 0.0,
            },
            "payroll": {
                "owner_residual": 0.0,
                "operators_total": 0.0,
                "admin_salary": 0.0,
            },
            "costs": {"total": 0.0},
            "manual_expenses": {"total": 0.0},
        }

        async def _pnl(a, b):
            return fake_pnl

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.fetchval = AsyncMock(
            side_effect=[
                2,
                1,
                0,  # current audience
                1,
                0,
                0,  # previous audience
                True,  # ledger table exists
            ]
        )
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=ctx)

        fake_finance = MagicMock()
        fake_finance.compute_pnl = AsyncMock(side_effect=_pnl)
        fake_db = MagicMock()
        fake_db.get_pool = AsyncMock(return_value=pool)

        with patch.dict(
            "sys.modules",
            {"finance_pnl": fake_finance, "db": fake_db},
        ):
            out = await build_owner_dashboard("today", today=date(2026, 8, 12))

        self.assertEqual(out["currency"], "RUB")
        self.assertEqual(out["period"]["key"], "today")
        self.assertEqual(out["metrics"]["net_income"]["current"], 0.0)
        self.assertEqual(out["refunds"]["data_status"], "unavailable")
        self.assertEqual(out["ledger"]["data_status"], "empty")
        self.assertNotEqual(out["ledger"]["data_status"], "available")
        self.assertIn("today", PERIOD_KEYS)

    async def test_ledger_unavailable_when_table_missing(self):
        fake_pnl = {
            "by_type": [],
            "total": {"net_profit": 0, "fiat_volume": 0, "profit_after_costs": 0},
            "payroll": {"owner_residual": 0, "operators_total": 0, "admin_salary": 0},
            "costs": {"total": 0},
            "manual_expenses": {"total": 0},
        }

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(side_effect=[0, 0, 0, 0, 0, 0, False])
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=ctx)

        fake_finance = MagicMock()
        fake_finance.compute_pnl = AsyncMock(return_value=fake_pnl)
        fake_db = MagicMock()
        fake_db.get_pool = AsyncMock(return_value=pool)

        with patch.dict(
            "sys.modules",
            {"finance_pnl": fake_finance, "db": fake_db},
        ):
            out = await build_owner_dashboard("yesterday", today=date(2026, 8, 12))

        self.assertEqual(out["ledger"]["data_status"], "unavailable")
        self.assertEqual(out["ledger"]["reason"], "table_missing")

    async def test_daily_points_include_expense_lines(self):
        fake_pnl = {
            "by_type": [{"type": "auto_buy", "orders": 2}],
            "total": {
                "net_profit": 1000.0,
                "fiat_volume": 20000.0,
                "profit_after_costs": 800.0,
            },
            "payroll": {
                "owner_residual": 420.0,
                "operators_total": 100.0,
                "admin_salary": 50.0,
            },
            "costs": {"total": 200.0},
            "manual_expenses": {"total": 30.0},
            "waterfall": [
                {"key": "cashback", "label": "Кешбэк", "amount": -80.0, "kind": "expense"},
                {"key": "admin_salary", "label": "Зарплата админа", "amount": -50.0, "kind": "expense"},
                {"key": "manual_expense_work", "label": "Рабочие расходы", "amount": -30.0, "kind": "expense"},
                {"key": "owner_residual", "label": "Финальный остаток", "amount": 420.0, "kind": "total"},
            ],
        }

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.fetchval = AsyncMock(side_effect=[0, 0, 0, 0, 0, 0, False])
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=ctx)

        fake_finance = MagicMock()
        fake_finance.compute_pnl = AsyncMock(return_value=fake_pnl)
        fake_db = MagicMock()
        fake_db.get_pool = AsyncMock(return_value=pool)

        with patch.dict(
            "sys.modules",
            {"finance_pnl": fake_finance, "db": fake_db},
        ):
            out = await build_owner_dashboard("today", today=date(2026, 8, 12))

        series = out["income_by_day"]
        self.assertIs(out["pnl_by_day"], series)
        self.assertEqual(series["data_status"], "available")
        self.assertEqual(series["source"], "compute_pnl")
        self.assertEqual(len(series["points"]), 1)
        point = series["points"][0]
        self.assertEqual(point["date"], "2026-08-12")
        self.assertEqual(point["net_income_rub"], 420.0)
        self.assertEqual(point["expenses_total_rub"], 160.0)
        self.assertEqual(
            [row["label"] for row in point["expense_lines"]],
            ["Кешбэк", "Зарплата админа", "Рабочие расходы"],
        )
        self.assertEqual(point["expense_lines"][0]["amount_rub"], 80.0)


class OwnerDashboardPeriodValidationTests(unittest.TestCase):
    def test_period_keys_cover_required(self):
        self.assertEqual(
            set(PERIOD_KEYS),
            {"today", "yesterday", "week", "month", "year"},
        )


if __name__ == "__main__":
    unittest.main()
