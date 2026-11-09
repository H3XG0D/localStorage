"""Тесты единого баланса с партнёрской частью."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class UnifiedPartnerBalanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_unified_available_client_plus_partner(self):
        from services.user_unified_balance import unified_available

        conn = AsyncMock()

        async def fetchval_side_effect(query, *args):
            q = " ".join(query.split())
            if "user_cashback_ledger" in q and "user_id = $1" in q and "SUM" in q:
                return 1000.0
            if "user_referral_ledger" in q:
                return 0.0
            if "user_referral_withdrawals" in q and "pending" in q:
                return 0.0
            if "partner_ledger" in q and "campaign_id" in q:
                return 2000.0
            if "partner_withdrawals" in q:
                return 0.0
            return None

        conn.fetchval = AsyncMock(side_effect=fetchval_side_effect)
        conn.fetchrow = AsyncMock(
            return_value={"campaign_id": 7, "campaign_code": "PRCQ7MIS"}
        )

        avail = await unified_available(conn, 6918202952)
        self.assertAlmostEqual(avail, 3000.0)

    async def test_unified_available_pending_user_reserves_partner(self):
        from services.user_unified_balance import unified_available

        conn = AsyncMock()

        async def fetchval_side_effect(query, *args):
            q = " ".join(query.split())
            if "user_cashback_ledger" in q:
                return 1000.0
            if "user_referral_ledger" in q:
                return 0.0
            if "user_referral_withdrawals" in q:
                return 3000.0
            if "partner_ledger" in q:
                return 2000.0
            if "partner_withdrawals" in q:
                return 0.0
            return None

        conn.fetchval = AsyncMock(side_effect=fetchval_side_effect)
        conn.fetchrow = AsyncMock(
            return_value={"campaign_id": 7, "campaign_code": "PRCQ7MIS"}
        )

        avail = await unified_available(conn, 6918202952)
        self.assertAlmostEqual(avail, 0.0)

    async def test_deduct_unified_payout_three_buckets(self):
        from services.user_unified_balance import deduct_unified_payout

        conn = AsyncMock()
        calls = []

        async def fetchval_side_effect(query, *args):
            q = " ".join(query.split())
            if "user_cashback_ledger" in q and "SUM" in q:
                return 1000.0
            if "user_referral_ledger" in q and "SUM" in q:
                return 500.0
            if "partner_ledger" in q and "SUM" in q:
                return 2000.0
            if "user_referral_withdrawals" in q:
                return 0.0
            if "partner_withdrawals" in q:
                return 0.0
            return 0.0

        async def execute_side_effect(query, *args):
            calls.append((query.strip(), args))

        conn.fetchval = AsyncMock(side_effect=fetchval_side_effect)
        conn.fetchrow = AsyncMock(
            return_value={"campaign_id": 7, "campaign_code": "PRCQ7MIS"}
        )
        conn.execute = AsyncMock(side_effect=execute_side_effect)

        await deduct_unified_payout(conn, 42, 3000.0, 99)

        inserts = [c for c in calls if "INSERT INTO" in c[0]]
        self.assertEqual(len(inserts), 3)
        cb_ins = next(c for c in inserts if "user_cashback_ledger" in c[0])
        ref_ins = next(c for c in inserts if "user_referral_ledger" in c[0])
        pl_ins = next(c for c in inserts if "partner_ledger" in c[0])
        self.assertAlmostEqual(float(cb_ins[1][1]), -1000.0)
        self.assertAlmostEqual(float(ref_ins[1][1]), -500.0)
        self.assertAlmostEqual(float(pl_ins[1][1]), -1500.0)

    async def test_hold_includes_partner_remainder(self):
        from services.user_cashback_db import hold_cashback_for_order

        conn = AsyncMock()

        async def fetchval_side_effect(query, *args):
            q = " ".join(query.split())
            if "user_referral_ledger" in q:
                return 0.0
            return None

        conn.fetchval = AsyncMock(side_effect=fetchval_side_effect)
        conn.fetchrow = AsyncMock(
            return_value={"campaign_id": 7, "campaign_code": "X"}
        )
        conn.execute = AsyncMock()

        with patch(
            "services.user_cashback_db._cashback_spendable",
            new=AsyncMock(return_value=3000.0),
        ), patch(
            "services.user_cashback_db.get_cashback_balance_conn",
            new=AsyncMock(return_value=1000.0),
        ):
            held = await hold_cashback_for_order(conn, 42, "ORD1", 2500.0)

        self.assertAlmostEqual(held, 2500.0)
        insert_calls = [
            c[0][0] for c in conn.execute.call_args_list if "INSERT INTO" in c[0][0]
        ]
        self.assertTrue(any("partner_ledger" in q for q in insert_calls))


if __name__ == "__main__":
    unittest.main()
