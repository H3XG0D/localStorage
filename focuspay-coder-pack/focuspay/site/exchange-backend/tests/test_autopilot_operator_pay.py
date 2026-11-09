"""Autopilot operator pay: presence pool, manual percent, hourly snapshot."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from unittest.mock import AsyncMock, patch

from operator_hourly_pay import (
    accrue_shift_hourly,
    attach_open_shift_hourly,
    hourly_amount_rub,
    hourly_snapshot_for_shift_start,
    payroll_ledger_kind,
    split_hourly_fund,
)
from operator_payroll_split import (
    calculate_order_pay,
    order_autopilot_paid,
    split_pool,
)


def _person(operator_id, role, weight, grade="junior"):
    return {
        "operator_id": operator_id,
        "role": role,
        "grade": grade,
        "grade_weight": Decimal(str(weight)),
        "weight": Decimal(str(weight)),
        "participant_snapshot": {"operator_id": operator_id, "role": role, "grade": grade},
    }


def _amounts(result):
    return {
        line["operator_id"]: line["amount_rub"]
        for line in result["lines"]
        if line.get("operator_id") is not None
    }


class AutopilotPayMathTests(unittest.TestCase):
    def test_autopilot_off_keeps_legacy_thirty_percent_pool(self):
        self.assertIsNone(calculate_order_pay(
            Decimal("1000"),
            {"autopilot_presence_percent": Decimal("5"), "autopilot_manual_percent": Decimal("10")},
            autopilot_on=False,
            autopilot_paid=True,
            shift_participants=[_person(1, "client", "1")],
        ))
        legacy = split_pool(Decimal("1000"), Decimal("30"), Decimal("30"), client_participants=[1], finance_participants=[2])
        self.assertEqual(legacy["pool_rub"], Decimal("300.00"))

    def test_presence_pool_splits_by_grade_and_keeps_the_kopeck(self):
        result = calculate_order_pay(
            Decimal("1000"),
            {"autopilot_presence_percent": Decimal("10")},
            autopilot_on=True,
            autopilot_paid=True,
            shift_participants=[
                _person(1, "client", "1.00", "junior"),
                _person(2, "finance", "1.25", "senior"),
            ],
        )
        self.assertEqual(result["pay_mode"], "autopilot_presence")
        self.assertEqual(result["pool_rub"], Decimal("100.00"))
        self.assertEqual(result["house_retained_rub"], Decimal("0.00"))
        self.assertEqual(_amounts(result), {1: Decimal("44.44"), 2: Decimal("55.56")})
        self.assertEqual(sum(line["amount_rub"] for line in result["lines"]), Decimal("100.00"))
        self.assertFalse(any(line["role"] == "unassigned" for line in result["lines"]))

    def test_empty_shift_keeps_presence_pool_with_the_house(self):
        result = calculate_order_pay(
            Decimal("1000"),
            {"autopilot_presence_percent": Decimal("5")},
            autopilot_on=True,
            autopilot_paid=True,
            shift_participants=[],
        )
        self.assertEqual(result["pool_rub"], Decimal("0.00"))
        self.assertEqual(result["house_retained_rub"], Decimal("50.00"))
        self.assertEqual(result["lines"], [])
        self.assertEqual(result["unassigned_client_pool_rub"], Decimal("0.00"))

    def test_manual_percent_pays_only_the_operator_who_did_the_order(self):
        result = calculate_order_pay(
            Decimal("1000"),
            {"autopilot_manual_percent": Decimal("12"), "client_operator_share_percent": Decimal("30")},
            autopilot_on=True,
            autopilot_paid=False,
            clients=[_person(7, "client", "1")],
            finances=[],
            shift_participants=[
                _person(7, "client", "1"),
                _person(8, "client", "1.25"),
            ],
        )
        self.assertEqual(result["pay_mode"], "autopilot_manual")
        self.assertEqual(result["pool_rub"], Decimal("120.00"))
        self.assertEqual(_amounts(result), {7: Decimal("120.00")})
        self.assertNotIn(8, _amounts(result))

    def test_manual_order_with_both_roles_uses_grade_pair_not_the_whole_shift(self):
        result = calculate_order_pay(
            Decimal("1000"),
            {"autopilot_manual_percent": Decimal("10"), "client_operator_share_percent": Decimal("30")},
            autopilot_on=True,
            autopilot_paid=False,
            clients=[_person(1, "client", "0.75", "trainee")],
            finances=[_person(2, "finance", "1.25", "senior")],
        )
        self.assertEqual(_amounts(result)[1], Decimal("20.00"))
        self.assertEqual(_amounts(result)[2], Decimal("80.00"))
        self.assertEqual(result["pool_rub"], Decimal("100.00"))

    def test_autopilot_paid_flag_requires_auto_confirm(self):
        self.assertTrue(order_autopilot_paid({"auto_served": True, "payout_confirmed_by": "auto"}))
        self.assertFalse(order_autopilot_paid({"auto_served": True, "payout_confirmed_by": "operator:4"}))
        self.assertFalse(order_autopilot_paid({"auto_served": False, "payout_confirmed_by": "auto"}))


class HourlyPayTests(unittest.IsolatedAsyncioTestCase):
    def test_two_and_a_half_hours(self):
        start = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(hourly_amount_rub(start, start + timedelta(minutes=150), 200), Decimal("500.00"))

    def test_zero_rate_and_backwards_shift_pay_nothing(self):
        start = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(hourly_amount_rub(start, start + timedelta(hours=2), 0), Decimal("0.00"))
        self.assertEqual(hourly_amount_rub(start, start - timedelta(minutes=5), 200), Decimal("0.00"))

    def test_fund_stays_with_whoever_was_already_sitting(self):
        start = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
        shares = split_hourly_fund(
            [
                {
                    "operator_id": 9,
                    "start": start,
                    "end": start + timedelta(hours=1),
                    "weight": Decimal("1.25"),
                },
                {
                    "operator_id": 2,
                    "start": start + timedelta(minutes=30),
                    "end": start + timedelta(hours=1),
                    "weight": Decimal("1.25"),
                },
            ],
            Decimal("220"),
        )
        self.assertEqual(shares[9], Decimal("165.00"))
        self.assertEqual(shares[2], Decimal("55.00"))

    def test_equal_grades_split_a_minute_three_ways(self):
        start = datetime(2026, 10, 12, 11, 33, tzinfo=timezone.utc)
        end = start + timedelta(minutes=12)
        weight = Decimal("1.25")
        shares = split_hourly_fund(
            [
                {"operator_id": operator_id, "start": start, "end": end, "weight": weight}
                for operator_id in (2, 7, 9)
            ],
            Decimal("220"),
        )
        self.assertEqual(sum(shares.values()), Decimal("44.00"))
        self.assertEqual(sorted(shares.values()), [Decimal("14.66"), Decimal("14.67"), Decimal("14.67")])

    async def test_shift_without_a_fund_is_not_paid(self):
        conn = AsyncMock()
        with patch("operator_hourly_pay._pool_rate", AsyncMock(return_value=Decimal("0"))):
            result = await accrue_shift_hourly(conn, {
                "id": 3,
                "operator_id": 9,
                "hourly_enabled": None,
                "hourly_rate_rub": None,
                "started_at": datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc),
                "ended_at": datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc),
            })
        self.assertEqual(result["reason"], "disabled")
        conn.execute.assert_not_called()

    async def test_hourly_accrues_once(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[None, 41])
        conn.execute = AsyncMock()
        start = datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc)
        end = datetime(2026, 10, 8, 10, 30, tzinfo=timezone.utc)
        shift = {
            "id": 4,
            "operator_id": 9,
            "hourly_enabled": True,
            "hourly_rate_rub": Decimal("200"),
            "started_at": start,
            "ended_at": end,
        }
        interval = {"operator_id": 9, "start": start, "end": end, "weight": Decimal("1")}
        with patch("operator_hourly_pay._pool_rate", AsyncMock(return_value=Decimal("200"))), patch(
            "operator_hourly_pay.fetch_hourly_intervals", AsyncMock(return_value=[interval])
        ):
            first = await accrue_shift_hourly(conn, shift)
            second = await accrue_shift_hourly(conn, shift)
        self.assertTrue(first["accrued"])
        self.assertEqual(first["amount_rub"], 500.0)
        self.assertEqual(second["reason"], "already")
        self.assertEqual(conn.execute.call_count, 1)
        self.assertIn("'hourly'", conn.execute.call_args[0][0])

    async def test_snapshot_stays_off_when_autopilot_or_toggle_is_off(self):
        with patch(
            "operator_hourly_pay.fetch_current_payroll_settings",
            AsyncMock(return_value={"autopilot_hourly_enabled": True, "autopilot_hourly_rate_rub": Decimal("150")}),
        ), patch("auto_settings.auto_mode_enabled", return_value=False):
            enabled, rate = await hourly_snapshot_for_shift_start(AsyncMock())
        self.assertFalse(enabled)
        self.assertEqual(rate, Decimal("0"))

        with patch(
            "operator_hourly_pay.fetch_current_payroll_settings",
            AsyncMock(return_value={"autopilot_hourly_enabled": False, "autopilot_hourly_rate_rub": Decimal("150")}),
        ), patch("auto_settings.auto_mode_enabled", return_value=True):
            enabled, rate = await hourly_snapshot_for_shift_start(AsyncMock())
        self.assertFalse(enabled)
        self.assertEqual(rate, Decimal("0"))

    def test_open_shift_earnings_include_the_live_hour_share(self):
        merged = attach_open_shift_hourly(
            {"orders_count": 2, "earnings_rub": 40.5},
            {"applies": True, "rate_rub": 220, "forecast_rub": 12.34},
        )
        self.assertEqual(merged["deal_earnings_rub"], 40.5)
        self.assertEqual(merged["hourly_forecast_rub"], 12.34)
        self.assertEqual(merged["earnings_rub"], 52.84)
        self.assertTrue(merged["hourly_applies"])

    def test_disabled_hourly_does_not_change_order_earnings(self):
        merged = attach_open_shift_hourly(
            {"earnings_rub": 40.5},
            {"applies": False, "rate_rub": 0, "forecast_rub": 99},
        )
        self.assertEqual(merged["earnings_rub"], 40.5)
        self.assertEqual(merged["hourly_forecast_rub"], 0.0)
        self.assertFalse(merged["hourly_applies"])

    def test_ledger_kind_labels(self):
        self.assertEqual(payroll_ledger_kind({"type": "hourly", "note": ""}), "hourly")
        self.assertEqual(payroll_ledger_kind({"type": "accrual", "note": "За смену · заявка 1"}), "presence")
        self.assertEqual(payroll_ledger_kind({"type": "accrual", "note": "Ручная заявка · 1 (client)"}), "manual")


if __name__ == "__main__":
    unittest.main()
