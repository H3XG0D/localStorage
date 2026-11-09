"""Личный баланс оператора к выводу (не общий пул)."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from operator_payroll_pool import (
    apply_operator_penalty,
    create_payout_request,
    operator_balance,
    operator_payroll_snapshot,
    pool_balance,
)


class OperatorBalanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_operator_a_sees_only_own_balance(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[1000.0, -100.0, 0])
        bal = await operator_balance(conn, 1)
        self.assertEqual(bal["available_rub"], 1000.0)
        self.assertEqual(bal["pending_holds_rub"], 100.0)

    async def test_operator_b_not_mixed_with_a(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[500.0, 0.0, 0])
        bal = await operator_balance(conn, 2)
        self.assertEqual(bal["available_rub"], 500.0)

    async def test_pool_balance_sums_all_operators(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[1500.0, -100.0, 2])
        bal = await pool_balance(conn)
        self.assertEqual(bal["available_rub"], 1500.0)
        self.assertEqual(bal["pending_requests_count"], 2)


class CreatePayoutRequestTests(unittest.IsolatedAsyncioTestCase):
    def _mock_pool_conn(self, conn: MagicMock):
        tx_ctx = AsyncMock()
        tx_ctx.__aenter__.return_value = None
        tx_ctx.__aexit__.return_value = False
        conn.transaction.return_value = tx_ctx
        pool = MagicMock()
        acquire_ctx = AsyncMock()
        acquire_ctx.__aenter__.return_value = conn
        acquire_ctx.__aexit__.return_value = False
        pool.acquire.return_value = acquire_ctx
        return pool

    async def test_rejects_amount_above_operator_balance(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[None, 1000.0, 0.0, 0])
        pool = self._mock_pool_conn(conn)

        with patch("operator_payroll_pool.get_pool", AsyncMock(return_value=pool)):
            with self.assertRaises(ValueError) as ctx:
                await create_payout_request(
                    operator_id=1,
                    amount_rub=1500.0,
                    requisites="card 1234",
                )
        self.assertIn("Недостаточно на вашем балансе", str(ctx.exception))

    async def test_allows_amount_within_operator_balance(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[None, 1000.0, 0.0, 0])
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 42,
                "operator_id": 1,
                "amount_rub": 500.0,
                "requisites": "card 1234",
                "status": "pending",
            }
        )
        pool = self._mock_pool_conn(conn)

        with patch("operator_payroll_pool.get_pool", AsyncMock(return_value=pool)):
            row = await create_payout_request(
                operator_id=1,
                amount_rub=500.0,
                requisites="card 1234",
            )
        self.assertEqual(row["id"], 42)
        hold_calls = [
            c
            for c in conn.execute.call_args_list
            if "hold" in str(c).lower()
        ]
        self.assertTrue(hold_calls)


class ApplyOperatorPenaltyTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_empty_reason_without_db(self):
        conn = AsyncMock()
        with self.assertRaises(ValueError) as ctx:
            await apply_operator_penalty(conn, 1, 100.0, " ")
        self.assertIn("причину", str(ctx.exception))
        conn.execute.assert_not_called()

    async def test_rejects_amount_above_balance(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[1, 200.0, 0.0, 0])
        with self.assertRaises(ValueError) as ctx:
            await apply_operator_penalty(conn, 7, 500.0, "ошибка по заявке")
        self.assertIn("Недостаточно на балансе", str(ctx.exception))
        conn.fetchrow.assert_not_called()

    async def test_inserts_negative_penalty_row(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[1, 1000.0, 0.0, 0])
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 9,
                "type": "penalty",
                "amount_rub": -150.0,
                "operator_id": 7,
                "note": "Штраф · ошибка по заявке · admin",
            }
        )
        row = await apply_operator_penalty(
            conn, 7, 150.0, "ошибка по заявке", admin_label="admin"
        )
        self.assertEqual(row["type"], "penalty")
        self.assertEqual(row["amount_rub"], -150.0)
        insert_sql = conn.fetchrow.call_args[0][0]
        self.assertIn("'penalty'", insert_sql)
        self.assertEqual(conn.fetchrow.call_args[0][1], -150.0)
        self.assertIn("Штраф · ошибка по заявке · admin", conn.fetchrow.call_args[0][3])

    async def test_payroll_snapshot_maps_ledger_totals(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "available_rub": 800.0,
                "accrued_rub": 1200.0,
                "paid_rub": 300.0,
                "penalty_rub": 100.0,
            }
        )
        snap = await operator_payroll_snapshot(conn, 3)
        self.assertIn("hourly", conn.fetchrow.call_args[0][0])
        self.assertEqual(snap["available_rub"], 800.0)
        self.assertEqual(snap["accrued_rub"], 1200.0)
        self.assertEqual(snap["paid_rub"], 300.0)
        self.assertEqual(snap["penalty_rub"], 100.0)


if __name__ == "__main__":
    unittest.main()
