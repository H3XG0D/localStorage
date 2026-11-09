"""Свипер осиротевших hold-* без живой заявки."""
import unittest
from unittest.mock import AsyncMock, patch

from services.user_cashback_db import (
    LIVE_ORDER_HOLD_STATUSES,
    order_id_from_hold_ledger_key,
    release_orphan_balance_holds,
)


class HoldLedgerKeyTests(unittest.TestCase):
    def test_cashback_hold_key(self):
        self.assertEqual(order_id_from_hold_ledger_key("hold-O123"), "O123")

    def test_referral_hold_key(self):
        self.assertEqual(order_id_from_hold_ledger_key("hold-O123:ref"), "O123")

    def test_partner_hold_key(self):
        self.assertEqual(order_id_from_hold_ledger_key("hold-O123:partner"), "O123")

    def test_ignores_spend_and_empty(self):
        self.assertIsNone(order_id_from_hold_ledger_key("spend-O123"))
        self.assertIsNone(order_id_from_hold_ledger_key("hold-"))
        self.assertIsNone(order_id_from_hold_ledger_key(""))


class ReleaseOrphanBalanceHoldsTests(unittest.IsolatedAsyncioTestCase):
    async def test_releases_hold_without_live_order(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {"ledger_key": "hold-ORPHAN1"},
                {"ledger_key": "hold-ORPHAN1:ref"},
                {"ledger_key": "hold-LIVE1"},
            ]
        )

        async def fetchval(query, order_id):
            if order_id == "LIVE1":
                return "CREATED"
            return None

        conn.fetchval = AsyncMock(side_effect=fetchval)
        release = AsyncMock()

        with patch(
            "services.user_cashback_db.release_cashback_for_order", new=release
        ):
            released = await release_orphan_balance_holds(conn=conn)

        self.assertEqual(released, ["ORPHAN1"])
        release.assert_awaited_once_with("ORPHAN1", conn=conn)
        self.assertIn("CREATED", LIVE_ORDER_HOLD_STATUSES)

    async def test_preserves_casino_holds_without_exchange_order(self):
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"ledger_key": "hold-casino-h-6de2f54ed55901e56417e6d12c46448a"},
            {"ledger_key": "hold-casino-h-6de2f54ed55901e56417e6d12c46448a:ref"},
            {"ledger_key": "hold-casino-h-6de2f54ed55901e56417e6d12c46448a:partner"},
        ]
        conn.fetchval.return_value = None
        with patch("services.user_cashback_db.release_cashback_for_order", new_callable=AsyncMock) as release:
            self.assertEqual(await release_orphan_balance_holds(conn=conn), [])
            release.assert_not_awaited()
        conn.fetchval.assert_not_awaited()

    async def test_skips_when_order_is_live(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[{"ledger_key": "hold-LIVE1"}])
        conn.fetchval = AsyncMock(return_value="OPERATOR_PENDING")
        release = AsyncMock()

        with patch(
            "services.user_cashback_db.release_cashback_for_order", new=release
        ):
            released = await release_orphan_balance_holds(conn=conn)

        self.assertEqual(released, [])
        release.assert_not_awaited()

    async def test_releases_hold_on_canceled_order(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[{"ledger_key": "hold-DEAD1:partner"}])
        conn.fetchval = AsyncMock(return_value="CANCELED")
        release = AsyncMock()

        with patch(
            "services.user_cashback_db.release_cashback_for_order", new=release
        ):
            released = await release_orphan_balance_holds(conn=conn)

        self.assertEqual(released, ["DEAD1"])
        release.assert_awaited_once_with("DEAD1", conn=conn)
