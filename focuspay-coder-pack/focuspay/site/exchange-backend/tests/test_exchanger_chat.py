"""Тесты Payfast ID и чата внештатников."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from external_deal_payin import deal_public_out
from chat_service import admin_list_threads, exchanger_snapshot, get_or_create_exchanger_thread


class DealPublicOutPayfastTests(unittest.TestCase):
    def test_includes_payfast_fields(self):
        deal = {
            "id": 42,
            "status": "pending",
            "amount_rub": 10000,
            "client_pays_rub": 11500,
            "principal_usdt": 123.45,
            "markup_pct": 15,
            "markup_mode": "on_deal",
            "merchant_order_id": "EXT-42",
            "payment_snapshot": '{"merchant_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}',
        }
        out = deal_public_out(deal)
        self.assertEqual(out["payfast_ref"], "EXT-42")
        self.assertEqual(out["payfast_order_id"], "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertIsNone(out.get("expires_at"))

    def test_includes_expires_at(self):
        deal = {
            "id": 7,
            "status": "awaiting_receipt",
            "amount_rub": 1000,
            "client_pays_rub": 1150,
            "principal_usdt": 12.0,
            "expires_at": "2026-08-20T12:00:00+00:00",
            "client_transaction_id": "shop-1",
        }
        out = deal_public_out(deal)
        self.assertEqual(out["expires_at"], "2026-08-20T12:00:00+00:00")
        self.assertEqual(out["client_transaction_id"], "shop-1")


class GetOrCreateExchangerThreadTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_thread_when_missing(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                None,
                {
                    "id": 7,
                    "external_exchanger_id": 3,
                    "source": "exchanger",
                    "admin_unread": 0,
                    "order_id": None,
                    "telegram_user_id": None,
                    "telegram_dm_chat_id": None,
                    "business_connection_id": None,
                    "created_at": None,
                    "last_message_at": None,
                },
            ]
        )
        thread = await get_or_create_exchanger_thread(conn, 3)
        self.assertEqual(thread["id"], 7)
        self.assertEqual(thread["source"], "exchanger")
        self.assertEqual(conn.fetchrow.await_count, 2)

    async def test_returns_existing_thread(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 9,
                "external_exchanger_id": 5,
                "source": "exchanger",
                "admin_unread": 1,
                "order_id": None,
                "telegram_user_id": None,
                "telegram_dm_chat_id": None,
                "business_connection_id": None,
                "created_at": None,
                "last_message_at": None,
            }
        )
        thread = await get_or_create_exchanger_thread(conn, 5)
        self.assertEqual(thread["id"], 9)
        self.assertEqual(conn.fetchrow.await_count, 1)


class ExchangerSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_multiple_active_deal_ids(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"id": 3, "name": "Partner", "username": "partner1"}
        )
        conn.fetch = AsyncMock(return_value=[{"id": 101}, {"id": 99}])

        snap = await exchanger_snapshot(conn, 3)
        self.assertEqual(snap["active_deal_ids"], [101, 99])
        self.assertEqual(snap["active_deal_id"], 101)
        self.assertEqual(snap["active_deal_count"], 2)


class AdminListThreadsSourceFilterTests(unittest.IsolatedAsyncioTestCase):
    async def test_exchanger_filter_in_sql(self):
        pool = MagicMock()
        conn = AsyncMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        conn.fetchval = AsyncMock(return_value=0)
        conn.fetch = AsyncMock(return_value=[])

        import chat_service

        old_pool = chat_service.get_pool
        try:
            chat_service.get_pool = AsyncMock(return_value=pool)
            await admin_list_threads(source_filter="exchanger", limit=10)
        finally:
            chat_service.get_pool = old_pool

        count_sql = conn.fetchval.await_args.args[0]
        list_sql = conn.fetch.await_args.args[0]
        self.assertIn("t.source = 'exchanger'", count_sql)
        self.assertIn("t.source = 'exchanger'", list_sql)


if __name__ == "__main__":
    unittest.main()
