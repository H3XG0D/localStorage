"""Видимость заявок «в работе» у коллег: team_orders / assigned_operator."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from routers.operator import (
    _assigned_operator_from_row,
    _order_out,
    _withdrawal_out,
    get_operator_orders,
    get_operator_queue,
    lookup_operator_order,
)


class AssignedOperatorTests(unittest.TestCase):
    def test_from_row_with_display_name(self):
        op = _assigned_operator_from_row(
            {
                "operator_id": 2,
                "operator_username": "alice",
                "operator_display_name": "Alice Ops",
            }
        )
        self.assertEqual(op["id"], 2)
        self.assertEqual(op["display_name"], "Alice Ops")
        self.assertEqual(op["username"], "alice")

    def test_from_row_null_when_unassigned(self):
        self.assertIsNone(_assigned_operator_from_row({"operator_id": None}))

    def test_order_out_includes_assigned_operator_and_to_me(self):
        out = _order_out(
            {
                "order_id": "O1",
                "status": "COMPLETED",
                "direction": "buy",
                "crypto": "usdt",
                "fiat_amount": 1000,
                "crypto_amount": 10,
                "operator_id": 2,
                "operator_username": "bob",
                "operator_display_name": "Bob",
                "created_at": "2026-01-01T00:00:00+00:00",
            },
            current_operator_id=1,
        )
        self.assertFalse(out["assigned_to_me"])
        self.assertEqual(out["assigned_operator"]["display_name"], "Bob")
        self.assertNotIn("operator_username", out)

    def test_order_out_assigned_to_me_true(self):
        out = _order_out(
            {
                "order_id": "O2",
                "status": "PENDING",
                "direction": "buy",
                "crypto": "usdt",
                "fiat_amount": 500,
                "crypto_amount": 5,
                "operator_id": 3,
                "operator_username": "me",
                "created_at": "2026-01-01T00:00:00+00:00",
            },
            current_operator_id=3,
        )
        self.assertTrue(out["assigned_to_me"])

    def test_sell_payout_rail_awaiting_funding(self):
        out = _order_out(
            {
                "order_id": "S1",
                "status": "OPERATOR_PENDING",
                "direction": "sell",
                "crypto": "btc",
                "fiat_amount": 4800,
                "crypto_amount": 0.05,
                "crypto_confirmed_at": "2026-09-06T00:00:00+00:00",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
        self.assertEqual(out["payout_rail"]["stage"], "awaiting_funding")
        self.assertIsNone(out.get("payout_alloc_status"))

    def test_sell_payout_rail_paid_awaiting_client(self):
        out = _order_out(
            {
                "order_id": "S1",
                "status": "PENDING",
                "direction": "sell",
                "crypto": "btc",
                "fiat_amount": 4800,
                "crypto_amount": 0.05,
                "crypto_confirmed_at": "2026-09-06T00:00:00+00:00",
                "payout_alloc_status": "PAID",
                "payout_receipt_file": "a.pdf",
                "payout_client_confirmed_at": None,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
        self.assertEqual(out["payout_rail"]["stage"], "paid_awaiting_client")
        self.assertTrue(out["payout_rail"]["has_receipt"])
        self.assertFalse(out["payout_rail"]["client_confirmed"])

    def test_buy_has_no_payout_rail(self):
        out = _order_out(
            {
                "order_id": "O1",
                "status": "COMPLETED",
                "direction": "buy",
                "crypto": "usdt",
                "fiat_amount": 1000,
                "crypto_amount": 10,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
        self.assertIsNone(out["payout_rail"])

    def test_withdrawal_out_includes_assigned_operator(self):
        out = _withdrawal_out(
            {
                "id": 9,
                "referrer_user_id": 111,
                "amount_rub": 100,
                "method": "crypto",
                "requisites": "addr",
                "status": "pending",
                "operator_id": 4,
                "operator_username": "carol",
                "operator_display_name": "Carol",
                "created_at": "2026-01-01T00:00:00+00:00",
            },
            current_operator_id=1,
        )
        self.assertEqual(out["assigned_operator"]["display_name"], "Carol")
        self.assertFalse(out["assigned_to_me"])

    def test_withdrawal_out_aliases_client_and_quotes_crypto(self):
        out = _withdrawal_out(
            {
                "id": 47,
                "referrer_user_id": 555,
                "buyer_username": "alice",
                "buyer_first_name": "Алиса",
                "amount_rub": 2700,
                "payout_amount_rub": 2700,
                "network_fee_rub": 0,
                "method": "crypto",
                "crypto": "btc",
                "requisites": "bc1qexample",
                "status": "pending",
                "created_at": "2026-01-01T00:00:00+00:00",
            },
            rates={"btc": 1_000_000},
        )
        self.assertEqual(out["user_id"], 555)
        self.assertEqual(out["buyer_username"], "@alice")
        self.assertEqual(out["buyer_first_name"], "Алиса")
        self.assertEqual(out["rate_rub"], 1_000_000.0)
        self.assertAlmostEqual(out["payout_crypto_amount"], 0.0027, places=8)


def _pool_with_fetch(fetch_results: list):
    """fetch_results — список результатов по порядку вызовов conn.fetch."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=fetch_results)

    async def _queue_stats(_conn):
        return {
            "queue_count": 0,
            "ready_to_accept_count": 0,
            "awaiting_receipt_count": 0,
            "withdrawal_incoming_count": 0,
            "exchange_incoming_count": 0,
        }

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = ctx

    async def _get_pool():
        return pool

    return _get_pool, conn


class GetOperatorOrdersTeamTests(unittest.IsolatedAsyncioTestCase):
    async def test_team_orders_visible_to_other_operator(self):
        team_row = {
            "order_id": "TEAM1",
            "direction": "buy",
            "status": "COMPLETED",
            "crypto": "usdt",
            "fiat_amount": 1000,
            "crypto_amount": 10,
            "operator_id": 2,
            "operator_username": "alice",
            "operator_display_name": "Alice",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        get_pool, conn = _pool_with_fetch([[], [], [], [team_row], [], [], [], []])

        with patch("routers.operator.get_pool", new=get_pool), patch(
            "routers.operator._queue_stats", new=AsyncMock(return_value={"queue_count": 0})
        ), patch(
            "routers.operator._withdrawal_market_rates",
            new=AsyncMock(return_value={}),
        ):
            result = await get_operator_orders(op={"id": 1, "username": "viewer"})

        self.assertEqual(len(result["team_orders"]), 1)
        self.assertEqual(result["team_orders"][0]["order_id"], "TEAM1")
        self.assertEqual(result["team_orders"][0]["assigned_operator"]["display_name"], "Alice")
        self.assertFalse(result["team_orders"][0]["assigned_to_me"])
        self.assertEqual(result["orders"], [])
        self.assertEqual(result.get("client_holds"), [])
        self.assertEqual(conn.fetch.await_count, 8)


class LookupOperatorOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_flags_assigned_to_other(self):
        row = {
            "order_id": "LK1",
            "direction": "buy",
            "status": "COMPLETED",
            "crypto": "usdt",
            "fiat_amount": 1000,
            "crypto_amount": 10,
            "operator_id": 5,
            "operator_username": "dave",
            "operator_display_name": "Dave",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        async def _get_pool():
            return pool

        with patch("routers.operator.get_pool", new=_get_pool):
            result = await lookup_operator_order(order_id="lk1", op={"id": 1})

        self.assertTrue(result["assigned_to_other"])
        self.assertFalse(result["assigned_to_me"])
        self.assertEqual(result["assigned_operator"]["display_name"], "Dave")
        self.assertFalse(result["in_incoming"])


class GetOperatorQueueInProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_lists_all_in_progress_orders(self):
        row = {
            "order_id": "Q1",
            "direction": "buy",
            "status": "COMPLETED",
            "crypto": "usdt",
            "fiat_amount": 2000,
            "crypto_amount": 20,
            "operator_id": 2,
            "operator_username": "alice",
            "operator_display_name": "Alice",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T01:00:00+00:00",
        }
        conn = AsyncMock()
        conn.fetch = AsyncMock(side_effect=[[row], []])
        conn.fetchval = AsyncMock(side_effect=[1, 0])

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        async def _get_pool():
            return pool

        with patch("routers.operator.get_pool", new=_get_pool), patch(
            "routers.operator._queue_stats",
            new=AsyncMock(return_value={"queue_count": 0, "ready_to_accept_count": 0}),
        ), patch(
            "routers.operator._withdrawal_market_rates",
            new=AsyncMock(return_value={}),
        ):
            result = await get_operator_queue(op={"id": 1, "username": "viewer"})

        self.assertEqual(result["in_progress_count"], 1)
        self.assertEqual(len(result["in_progress_orders"]), 1)
        self.assertEqual(result["in_progress_orders"][0]["order_id"], "Q1")
        self.assertFalse(result["in_progress_orders"][0]["assigned_to_me"])


if __name__ == "__main__":
    unittest.main()
