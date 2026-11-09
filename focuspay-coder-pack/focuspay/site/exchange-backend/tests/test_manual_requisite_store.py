"""Привязка MAN-кода к заявке на бэкенде."""
from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from manual_requisite_store import (
    SOURCE_MERCHANT,
    SOURCE_RAIL,
    SOURCE_REKI_BOT,
    apply_ticket_to_order,
    claim_ticket,
    normalize_ticket_code,
)


class NormalizeTests(unittest.TestCase):
    def test_accepts_man_codes(self):
        self.assertEqual(normalize_ticket_code(" man-ab12cd "), "MAN-AB12CD")
        self.assertEqual(normalize_ticket_code("AB12CD"), "MAN-AB12CD")
        self.assertIsNone(normalize_ticket_code("MAN-SHORT"))
        self.assertIsNone(normalize_ticket_code(""))


class ClaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_returns_row(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "code": "MAN-AB12CD",
                "source": SOURCE_RAIL,
                "sub_token": "SBPRUB",
                "amount_rub": Decimal("5400"),
                "bill": {"reciver": "7900"},
                "requisite_id": 7,
                "merchant_order_id": None,
            }
        )
        ticket = await claim_ticket(conn, "man-ab12cd", "ORD-1")
        self.assertEqual(ticket["code"], "MAN-AB12CD")
        self.assertEqual(ticket["requisite_id"], 7)
        conn.fetchrow.assert_awaited_once()

    async def test_claim_missing(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=None)
        self.assertIsNone(await claim_ticket(conn, "MAN-ZZZZZZ", "ORD-1"))

    async def test_apply_rail_updates_order_and_allocation(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        ticket = {
            "code": "MAN-AB12CD",
            "source": SOURCE_RAIL,
            "requisite_id": 7,
            "merchant_order_id": None,
        }
        await apply_ticket_to_order(conn, ticket, "ORD-1")
        self.assertEqual(conn.execute.await_count, 2)
        first_sql = conn.execute.await_args_list[0].args[0]
        self.assertIn("payin_requisite_id", first_sql)

    async def test_apply_merchant_sets_merchant_order_id(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        ticket = {
            "code": "MAN-AB12CD",
            "source": SOURCE_MERCHANT,
            "requisite_id": None,
            "merchant_order_id": "uuid-1",
        }
        await apply_ticket_to_order(conn, ticket, "ORD-2")
        self.assertEqual(conn.execute.await_count, 1)
        self.assertIn("merchant_order_id", conn.execute.await_args.args[0])

    async def test_apply_reki_writes_snapshot_not_merchant_column(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        ticket = {
            "code": "MAN-AB12CD",
            "source": SOURCE_REKI_BOT,
            "requisite_id": None,
            "merchant_order_id": "d84a6631-28dc-4afd-aa52-533a5b5bdaa3",
        }
        await apply_ticket_to_order(conn, ticket, "ORD-3")
        self.assertEqual(conn.execute.await_count, 1)
        sql = conn.execute.await_args.args[0]
        self.assertIn("payment_snapshot", sql)
        self.assertNotIn("merchant_order_id", sql)
        payload = conn.execute.await_args.args[2]
        self.assertIn("reki_payfast_id", payload)
        self.assertIn("d84a6631-28dc-4afd-aa52-533a5b5bdaa3", payload)


if __name__ == "__main__":
    unittest.main()
