"""Подбор чеков под реквизит: точное попадание, долив, пары/тройки, отсечения."""
from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from payout_requisite_matcher import (
    Candidate,
    build_plan,
    from_kop,
    load_candidates,
    load_pool_orders,
    matcher_limits,
    pool_order_payload,
    to_kop,
    unreserved_remaining_rub,
)

ROOT = Path(__file__).resolve().parents[1]


def cand(order_id: str, rub) -> Candidate:
    return Candidate(order_id=order_id, amount_kop=to_kop(rub))


class BuildPlanTests(unittest.TestCase):
    def test_exact_single_check_wins(self):
        plan = build_plan(
            10000,
            [cand("A", 10000), cand("B", 6000), cand("C", 4000)],
            max_checks=3,
            doliv_limit_rub=500,
        )
        self.assertIsNotNone(plan)
        self.assertEqual([c.order_id for c in plan.orders], ["A"])
        self.assertEqual(plan.checks_count, 1)
        self.assertEqual(plan.doliv_kop, 0)
        self.assertTrue(plan.closes)

    def test_single_plus_doliv_when_no_exact(self):
        plan = build_plan(
            10000,
            [cand("A", 9700), cand("B", 3000)],
            max_checks=3,
            doliv_limit_rub=500,
        )
        self.assertEqual([c.order_id for c in plan.orders], ["A"])
        self.assertEqual(from_kop(plan.doliv_kop), Decimal("300.00"))
        self.assertEqual(plan.leftover_kop, 0)
        self.assertEqual(plan.checks_count, 2)

    def test_single_plus_doliv_beats_two_exact(self):
        plan = build_plan(
            10000,
            [cand("A", 9700), cand("B", 6000), cand("C", 4000)],
            max_checks=3,
            doliv_limit_rub=500,
        )
        self.assertEqual([c.order_id for c in plan.orders], ["A"])
        self.assertEqual(from_kop(plan.doliv_kop), Decimal("300.00"))
        self.assertTrue(plan.closes)

    def test_exact_single_still_beats_single_plus_doliv(self):
        plan = build_plan(
            10000,
            [cand("A", 9700), cand("EXACT", 10000), cand("B", 6000), cand("C", 4000)],
            max_checks=3,
            doliv_limit_rub=500,
        )
        self.assertEqual([c.order_id for c in plan.orders], ["EXACT"])
        self.assertEqual(plan.doliv_kop, 0)
        self.assertEqual(plan.checks_count, 1)

    def test_max_checks_two_forbids_pair_plus_doliv(self):
        plan = build_plan(
            10000,
            [cand("A", 6000), cand("B", 3500)],
            max_checks=2,
            doliv_limit_rub=1500,
        )
        self.assertEqual(sorted(c.order_id for c in plan.orders), ["A", "B"])
        self.assertEqual(plan.doliv_kop, 0)
        self.assertEqual(from_kop(plan.leftover_kop), Decimal("500.00"))

    def test_max_checks_three_allows_pair_plus_doliv(self):
        plan = build_plan(
            10000,
            [cand("A", 6000), cand("B", 3500)],
            max_checks=3,
            doliv_limit_rub=1500,
        )
        self.assertTrue(plan.closes)
        self.assertEqual(from_kop(plan.doliv_kop), Decimal("500.00"))
        self.assertEqual(plan.checks_count, 3)

    def test_triple_closes_exactly(self):
        plan = build_plan(
            10000,
            [cand("A", 5000), cand("B", 3000), cand("C", 2000), cand("D", 1500)],
            max_checks=3,
            doliv_limit_rub=0,
        )
        self.assertEqual(sorted(c.order_id for c in plan.orders), ["A", "B", "C"])
        self.assertTrue(plan.closes)

    def test_max_checks_one_forbids_pairs(self):
        plan = build_plan(
            10000,
            [cand("B", 6000), cand("C", 4000)],
            max_checks=1,
            doliv_limit_rub=0,
        )
        self.assertEqual(len(plan.orders), 1)
        self.assertFalse(plan.closes)
        self.assertEqual(from_kop(plan.leftover_kop), Decimal("4000.00"))

    def test_max_checks_two_forbids_triples(self):
        plan = build_plan(
            10000,
            [cand("A", 5000), cand("B", 3000), cand("C", 2000)],
            max_checks=2,
            doliv_limit_rub=0,
        )
        self.assertEqual(len(plan.orders), 2)
        self.assertEqual(from_kop(plan.leftover_kop), Decimal("2000.00"))

    def test_oversized_candidates_ignored(self):
        plan = build_plan(
            5000,
            [cand("BIG", 9000), cand("OK", 5000)],
            max_checks=3,
            doliv_limit_rub=0,
        )
        self.assertEqual([c.order_id for c in plan.orders], ["OK"])

    def test_pure_doliv_only_inside_limit(self):
        plan = build_plan(400, [], max_checks=3, doliv_limit_rub=500)
        self.assertEqual(plan.orders, [])
        self.assertEqual(from_kop(plan.doliv_kop), Decimal("400.00"))
        self.assertTrue(plan.closes)

        self.assertIsNone(build_plan(4000, [], max_checks=3, doliv_limit_rub=500))

    def test_exact_client_beats_pure_doliv(self):
        plan = build_plan(500, [cand("A", 500)], max_checks=3, doliv_limit_rub=500)
        self.assertEqual([c.order_id for c in plan.orders], ["A"])
        self.assertEqual(plan.doliv_kop, 0)

    def test_kopecks_are_not_rounded_away(self):
        plan = build_plan(
            Decimal("10000.55"),
            [cand("A", Decimal("10000.55"))],
            max_checks=3,
            doliv_limit_rub=0,
        )
        self.assertTrue(plan.closes)
        self.assertEqual(plan.orders[0].amount_rub, Decimal("10000.55"))

    def test_zero_remaining_has_no_plan(self):
        self.assertIsNone(build_plan(0, [cand("A", 100)]))

    def test_greedy_fill_used_above_exact_depth(self):
        plan = build_plan(
            10000,
            [cand("A", 4000), cand("B", 3000), cand("C", 2000), cand("D", 1000)],
            max_checks=4,
            doliv_limit_rub=0,
        )
        self.assertEqual(len(plan.orders), 4)
        self.assertTrue(plan.closes)


class MatcherLimitsTests(unittest.TestCase):
    def test_first_hour_is_solo_without_doliv(self):
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
        row = {
            "max_checks": 3,
            "doliv_limit_rub": 2000,
            "created_at": now - timedelta(minutes=8),
        }
        self.assertEqual(matcher_limits(row, now=now), (1, 0))

    def test_payin_up_to_2000_stays_one_check_without_doliv(self):
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
        row = {
            "direction": "payin",
            "amount_rub": Decimal("2000"),
            "max_checks": 3,
            "doliv_limit_rub": 2000,
            "created_at": now - timedelta(hours=3),
        }
        self.assertEqual(matcher_limits(row, now=now), (1, 0))
        row["amount_rub"] = Decimal("2000.01")
        self.assertEqual(matcher_limits(row, now=now), (3, 2000))
        row["direction"] = "payout"
        row["amount_rub"] = Decimal("1500")
        self.assertEqual(matcher_limits(row, now=now), (3, 2000))

    def test_after_hour_uses_card_limits(self):
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
        row = {
            "max_checks": 3,
            "doliv_limit_rub": 2000,
            "created_at": now - timedelta(minutes=61),
        }
        self.assertEqual(matcher_limits(row, now=now), (3, 2000))

    def test_fresh_card_does_not_close_on_3300(self):
        plan = build_plan(
            5000,
            [cand("A", 3300)],
            max_checks=1,
            doliv_limit_rub=0,
        )
        self.assertEqual([c.order_id for c in plan.orders], ["A"])
        self.assertFalse(plan.closes)
        self.assertEqual(plan.doliv_kop, 0)

    def test_after_hour_3300_plus_doliv_closes_5000(self):
        plan = build_plan(
            5000,
            [cand("A", 3300)],
            max_checks=2,
            doliv_limit_rub=2000,
        )
        self.assertEqual([c.order_id for c in plan.orders], ["A"])
        self.assertEqual(from_kop(plan.doliv_kop), Decimal("1700.00"))
        self.assertTrue(plan.closes)
        self.assertEqual(plan.checks_count, 2)


class CandidateQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_filters_direction_status_and_allocations(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "order_id": "S1",
                    "user_id": 7,
                    "fiat_amount": Decimal("9700.00"),
                    "crypto": "usdt",
                    "sub_token": "CARDRUB",
                    "created_at": None,
                }
            ]
        )
        out = await load_candidates(conn, method="card", max_amount_rub=Decimal("10000.00"))
        self.assertEqual([c.order_id for c in out], ["S1"])
        self.assertEqual(out[0].amount_kop, 970000)

        sql = conn.fetch.await_args.args[0]
        self.assertIn("lower(o.direction) = 'sell'", sql)
        self.assertIn("crypto_confirmed_at IS NOT NULL", sql)
        self.assertIn("payout_requisite_allocations", sql)
        self.assertIn("expires_at IS NULL OR o.expires_at > now()", sql)
        args = conn.fetch.await_args.args
        self.assertEqual(args[1], ["PENDING", "OPERATOR_PENDING"])
        self.assertEqual(args[2], "CARDRUB")
        self.assertEqual(args[3], Decimal("10000.00"))
        self.assertEqual(args[4], ["RESERVED", "PAID"])

    async def test_pool_orders_skip_method_and_amount_filters(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "order_id": "S9",
                    "user_id": 1,
                    "fiat_amount": Decimal("5900.00"),
                    "crypto": "btc",
                    "sub_token": None,
                    "created_at": None,
                }
            ]
        )
        out = await load_pool_orders(conn)
        self.assertEqual([c.order_id for c in out], ["S9"])
        sql = conn.fetch.await_args.args[0]
        self.assertIn("crypto_confirmed_at IS NOT NULL", sql)
        self.assertIn("NOT EXISTS", sql)
        self.assertIn("payout_requisite_allocations", sql)
        self.assertIn("source_sell_order_id", sql)
        args = conn.fetch.await_args.args
        self.assertEqual(args[1], ["PENDING", "OPERATOR_PENDING"])
        self.assertIsNone(args[2])
        self.assertIsNone(args[3])
        self.assertEqual(args[4], ["RESERVED", "PAID"])
        self.assertIn("QUEUED", args[5])

    async def test_pool_payload_exposes_order_fields(self):
        candidate = Candidate(
            order_id="S9",
            amount_kop=590000,
            crypto="btc",
            sub_token=None,
            created_at=None,
            requisites="2202200112345678 Сбер",
        )
        payload = pool_order_payload(candidate)
        self.assertEqual(payload["order_id"], "S9")
        self.assertEqual(payload["fiat_amount"], 5900.0)
        self.assertEqual(payload["crypto"], "btc")
        self.assertEqual(payload["requisites"], "2202200112345678 Сбер")

    async def test_sbp_requisite_maps_to_sbp_orders(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        await load_candidates(conn, method="sbp", max_amount_rub=1000)
        self.assertEqual(conn.fetch.await_args.args[2], "SBPRUB")

    async def test_reserved_amount_reduces_free_remaining(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=Decimal("2500.00"))
        row = {"id": 1, "amount_rub": Decimal("10000.00"), "paid_rub": Decimal("1000.00")}
        free = await unreserved_remaining_rub(conn, row)
        self.assertEqual(free, Decimal("6500.00"))

    async def test_free_remaining_never_negative(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=Decimal("99999.00"))
        row = {"id": 1, "amount_rub": Decimal("1000.00"), "paid_rub": Decimal("0")}
        self.assertEqual(await unreserved_remaining_rub(conn, row), Decimal("0.00"))

    async def test_solo_window_drops_non_closing_sell_plan(self):
        from datetime import datetime, timedelta, timezone

        from payout_requisite_matcher import plan_for_requisite

        now = datetime.now(timezone.utc)
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=Decimal("0"))
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "order_id": "S1",
                    "user_id": 1,
                    "fiat_amount": Decimal("3300.00"),
                    "crypto": "btc",
                    "sub_token": "SBPRUB",
                    "created_at": now,
                }
            ]
        )
        row = {
            "id": 1,
            "direction": "payout",
            "method": "sbp",
            "amount_rub": Decimal("5000.00"),
            "paid_rub": Decimal("0"),
            "max_checks": 3,
            "doliv_limit_rub": 2000,
            "created_at": now - timedelta(minutes=8),
        }
        plan, free = await plan_for_requisite(conn, row)
        self.assertIsNone(plan)
        self.assertEqual(free, Decimal("5000.00"))

        row["created_at"] = now - timedelta(minutes=61)
        plan, free = await plan_for_requisite(conn, row)
        self.assertIsNotNone(plan)
        self.assertTrue(plan.closes)
        self.assertEqual(from_kop(plan.doliv_kop), Decimal("1700.00"))

    async def test_triangle_plan_is_leftover_doliv_not_forecast(self):
        from datetime import datetime, timedelta, timezone

        from payout_requisite_matcher import plan_for_requisite

        now = datetime.now(timezone.utc)
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=Decimal("0"))
        conn.fetch = AsyncMock(return_value=[])
        row = {
            "id": 1,
            "direction": "payin",
            "source_sell_order_id": "S1",
            "method": "sbp",
            "amount_rub": Decimal("5000.00"),
            "paid_rub": Decimal("3300.00"),
            "max_checks": 3,
            "doliv_limit_rub": 2000,
            "created_at": now - timedelta(hours=2),
        }
        plan, free = await plan_for_requisite(conn, row)
        self.assertEqual(free, Decimal("1700.00"))
        self.assertIsNotNone(plan)
        self.assertTrue(plan.closes)
        self.assertEqual(from_kop(plan.doliv_kop), Decimal("1700.00"))
        self.assertEqual((plan.extra or {}).get("kind"), "triangle")
        conn.fetch.assert_not_called()


class MigrationShapeTests(unittest.TestCase):
    def test_migration_declares_tables_and_guards(self):
        sql = (ROOT / "migrations" / "add_payout_requisites.sql").read_text()
        self.assertIn("operator_payout_requisites", sql)
        self.assertIn("payout_requisite_allocations", sql)
        self.assertIn("payout_requisite_plans", sql)
        self.assertIn("ux_payout_alloc_active_order", sql)
        self.assertIn("cost_pct", sql)
        self.assertIn("direction", sql)
        self.assertIn("payin", sql)
        self.assertIn("DEFAULT 2000", sql)
        self.assertIn("client_confirmed_at", sql)
        self.assertIn("source_sell_order_id", sql)
        self.assertIn("ux_payout_req_source_sell_live", sql)
        # order_id намеренно без FK: orders живёт в схеме бота.
        self.assertNotIn("REFERENCES orders", sql)


if __name__ == "__main__":
    unittest.main()
