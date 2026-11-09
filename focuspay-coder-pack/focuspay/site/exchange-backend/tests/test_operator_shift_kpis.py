"""Freeze: operator shift KPIs for admin overview cards.

Definitions (do not change payroll formulas here):
- turnover = fiat_total of PAID+COMPLETED orders matched to the active shift
  by payout_confirmed_at / updated_at / created_at
- earnings = legacy percent of payroll_base + role_split ledger lines
- in_work = open statuses, including role_split assignment; not accrued
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import unittest

from finance_access import can_view_finance_operator, shift_kpi_public_fields, strip_operator_profit_fields
from payroll_base import (
    IN_WORK_BY_OPERATOR_SQL,
    SHIFT_ORDERS_SQL,
    fetch_in_work_by_operator,
)


class ShiftKpiPublicFieldsTests(unittest.TestCase):
    def test_finance_viewer_gets_separate_turnover_and_earnings(self):
        fields = shift_kpi_public_fields(
            {"fiat_total": 10000.0, "orders_count": 2, "earnings_rub": 150.0},
            True,
        )
        self.assertEqual(fields["turnover"], 10000.0)
        self.assertEqual(fields["fiat_total"], 10000.0)
        self.assertEqual(fields["earnings"], 150.0)
        self.assertEqual(fields["earnings_rub"], 150.0)
        self.assertEqual(fields["orders_count"], 2)

    def test_no_finance_omits_earnings_instead_of_zero(self):
        fields = shift_kpi_public_fields(
            {"fiat_total": 10000.0, "orders_count": 2, "earnings_rub": 150.0},
            False,
        )
        self.assertEqual(fields["turnover"], 10000.0)
        self.assertNotIn("earnings", fields)
        self.assertNotIn("earnings_rub", fields)

    def test_missing_shift_stats_are_null_not_zero_earnings(self):
        fields = shift_kpi_public_fields(None, True)
        self.assertIsNone(fields["turnover"])
        self.assertNotIn("earnings", fields)
        self.assertNotIn("earnings_rub", fields)

    def test_finance_role_alone_does_not_grant_analytics(self):
        self.assertFalse(can_view_finance_operator({"operator_roles": ["finance"]}))
        self.assertTrue(
            can_view_finance_operator(
                {"operator_roles": ["finance"], "permissions": ["finance.analytics"]}
            )
        )

    def test_strip_keeps_turnover_and_earnings(self):
        stripped = strip_operator_profit_fields(
            {
                "fiat_total": 5000.0,
                "earnings_rub": 80.0,
                "service_profit_rub": 400.0,
                "profit_rub": 350.0,
                "accruals_rub": 50.0,
            }
        )
        self.assertEqual(stripped["fiat_total"], 5000.0)
        self.assertEqual(stripped["earnings_rub"], 80.0)
        self.assertNotIn("service_profit_rub", stripped)
        self.assertNotIn("profit_rub", stripped)
        self.assertNotIn("accruals_rub", stripped)


class OperatorTeamRoleGradesTests(unittest.IsolatedAsyncioTestCase):
    def _conn(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": 7,
                    "username": "finance-op",
                    "display_name": "Finance",
                    "avatar_file_id": None,
                    "operator_roles": ["finance"],
                    "role_grades": {"finance": "senior"},
                    "shift_id": None,
                    "shift_started_at": None,
                    "orders_in_progress": 0,
                    "withdrawals_in_progress": 0,
                }
            ]
        )
        return conn

    async def test_ordinary_operator_does_not_receive_role_grades(self):
        from routers.operator import _team_snapshot

        result = await _team_snapshot(self._conn(), {"id": 1, "permissions": []})

        self.assertNotIn("role_grades", result["operators"][0])

    async def test_finance_viewer_still_receives_role_grades(self):
        from routers.operator import _team_snapshot

        result = await _team_snapshot(
            self._conn(),
            {"id": 1, "permissions": ["finance.analytics"]},
        )

        self.assertEqual(
            result["operators"][0]["role_grades"],
            {"finance": "senior"},
        )


class InWorkAssignmentTests(unittest.IsolatedAsyncioTestCase):
    def test_in_work_sql_includes_role_split_assignment_not_payroll_statuses(self):
        self.assertIn("intake_operator_id", IN_WORK_BY_OPERATOR_SQL)
        self.assertIn("finance_operator_id", IN_WORK_BY_OPERATOR_SQL)
        self.assertIn("order_operator_participants", IN_WORK_BY_OPERATOR_SQL)
        self.assertIn("PAID", IN_WORK_BY_OPERATOR_SQL)
        self.assertNotIn("'CREATED'", IN_WORK_BY_OPERATOR_SQL)
        self.assertIn("PAID", SHIFT_ORDERS_SQL)
        self.assertIn("COMPLETED", SHIFT_ORDERS_SQL)
        self.assertIn("<> 'role_split'", SHIFT_ORDERS_SQL)

    async def test_fetch_in_work_groups_assigned_open_orders(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {"operator_id": 7, "orders_in_work": 2, "in_work_rub": 18000.0},
            ]
        )
        out = await fetch_in_work_by_operator(conn)
        self.assertEqual(out[7]["orders_in_work"], 2)
        self.assertEqual(out[7]["in_work_rub"], 18000.0)
        sql = conn.fetch.await_args.args[0]
        self.assertIn("intake_operator_id", sql)
        self.assertIn("finance_operator_id", sql)


class OperatorEarningsMapTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_shift_uses_role_split_aware_stats(self):
        from routers.admin_operators import _operator_earnings_map

        conn = AsyncMock()
        started = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
        conn.fetch = AsyncMock(
            side_effect=[
                [{"operator_id": 7, "accrued": 0.0, "paid": 0.0, "available": 0.0, "penalty": 0.0}],
                [
                    {
                        "id": 10,
                        "operator_id": 7,
                        "started_at": started,
                        "percent": 15,
                    }
                ],
            ]
        )
        with patch(
            "operator_payroll_pool.backfill_accruals",
            AsyncMock(),
        ), patch(
            "routers.admin_operators.stats_for_operator_shift_conn",
            AsyncMock(
                return_value={
                    "orders_count": 4,
                    "fiat_total": 42000.0,
                    "earnings_rub": 640.0,
                }
            ),
        ) as stats_mock:
            out = await _operator_earnings_map(conn)

        stats_mock.assert_awaited_once()
        self.assertEqual(out[7]["earnings_shift_rub"], 640.0)
        self.assertEqual(out[7]["turnover_shift_rub"], 42000.0)
        self.assertEqual(out[7]["earnings_accrued_rub"], 0.0)
        self.assertEqual(out[7]["payroll_available_rub"], 0.0)


if __name__ == "__main__":
    unittest.main()
