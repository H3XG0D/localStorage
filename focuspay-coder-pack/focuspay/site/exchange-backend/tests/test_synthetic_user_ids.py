"""Tests for shared synthetic user id allocation / collision remediation."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from synthetic_user_ids import (
    ORPHAN_FLOOR,
    allocate_synthetic_user_id,
    is_orphan_user_id,
    orphan_user_id,
    remediate_client_guest_collisions,
    synthetic_id_is_taken,
)


class OrphanHelpersTests(unittest.TestCase):
    def test_orphan_user_id_formula(self):
        self.assertEqual(orphan_user_id(-56), -(ORPHAN_FLOOR + 56))
        self.assertEqual(orphan_user_id(56), -(ORPHAN_FLOOR + 56))
        self.assertTrue(is_orphan_user_id(orphan_user_id(-56)))
        self.assertFalse(is_orphan_user_id(-56))

    def test_orphan_rejects_already_orphan(self):
        with self.assertRaises(ValueError):
            orphan_user_id(-(ORPHAN_FLOOR + 1))


class AllocateSyntheticTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_taken_ids(self):
        conn = AsyncMock()
        # sequence exists
        conn.fetchval = AsyncMock(
            side_effect=[
                True,  # _sequence_exists synthetic
                -56,  # nextval → taken
                True,  # exists again
                -700,  # free
            ]
        )

        async def is_taken(_conn, uid):
            return uid == -56

        import synthetic_user_ids as mod

        original = mod.synthetic_id_is_taken
        mod.synthetic_id_is_taken = is_taken
        try:
            uid = await allocate_synthetic_user_id(conn)
        finally:
            mod.synthetic_id_is_taken = original
        self.assertEqual(uid, -700)

    async def test_taken_query_runs(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        self.assertTrue(await synthetic_id_is_taken(conn, -56))
        conn.fetchval.assert_awaited()
        sql = conn.fetchval.await_args.args[0]
        self.assertIn("web_guest_sessions", sql)
        self.assertIn("web_users", sql)
        self.assertIn("user_cashback_ledger", sql)


class RemediateTests(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_does_not_write(self):
        conn = AsyncMock()
        reg = datetime(2026, 9, 11, 17, 24, 4, tzinfo=timezone.utc)
        conn.fetch = AsyncMock(
            side_effect=[
                [
                    {
                        "web_id": 322,
                        "username": "nice124",
                        "uid": -56,
                        "reg_at": reg,
                        "guest_sessions": 1,
                    }
                ],
                [{"order_id": "252972695357", "created_at": datetime(2026, 6, 14), "status": "PAID"}],
                [{"id": 8, "amount_rub": 19.56, "type": "accrual", "created_at": datetime(2026, 6, 15, tzinfo=timezone.utc)}],
                [],  # referral
            ]
        )
        conn.execute = AsyncMock()
        report = await remediate_client_guest_collisions(conn, dry_run=True)
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["balance_moved_rub"], 19.56)
        self.assertEqual(report[0]["orphan"], -(ORPHAN_FLOOR + 56))
        conn.execute.assert_not_awaited()

    async def test_apply_moves_guest_and_pre_reg_finance(self):
        conn = AsyncMock()
        reg = datetime(2026, 9, 11, 17, 24, 4, tzinfo=timezone.utc)
        conn.fetch = AsyncMock(
            side_effect=[
                [
                    {
                        "web_id": 322,
                        "username": "nice124",
                        "uid": -56,
                        "reg_at": reg,
                        "guest_sessions": 1,
                    }
                ],
                [{"order_id": "1", "created_at": datetime(2026, 6, 14), "status": "PAID"}],
                [{"id": 1, "amount_rub": 19.56, "type": "accrual", "created_at": reg}],
                [],
            ]
        )
        conn.fetchval = AsyncMock(return_value=False)  # orphan not taken
        conn.execute = AsyncMock()
        report = await remediate_client_guest_collisions(conn, dry_run=False)
        self.assertEqual(report[0]["orders_moved"], 1)
        self.assertGreaterEqual(conn.execute.await_count, 3)
        guest_sql = conn.execute.await_args_list[0].args[0]
        self.assertIn("web_guest_sessions", guest_sql)


if __name__ == "__main__":
    unittest.main()
