"""Concurrency and retry contracts for PostgreSQL digest delivery claims."""
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from digest_delivery import claim_digest_delivery


class DigestDeliveryClaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_is_one_atomic_upsert_with_unique_delivery_key(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"claim_token": "winner"})
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        with patch("digest_delivery.get_pool", new=AsyncMock(return_value=pool)):
            token = await claim_digest_delivery(
                digest_kind="operator",
                recipient_key="42",
                delivery_date=date(2026, 8, 21),
            )

        self.assertEqual(token, "winner")
        sql = conn.fetchrow.await_args.args[0]
        self.assertIn("ON CONFLICT (digest_kind, recipient_key, delivery_date)", sql)
        self.assertIn("digest_deliveries.status <> 'sent'", sql)
        self.assertIn("claimed_until <= now()", sql)
        conn.transaction.assert_not_called()

    async def test_losing_worker_gets_no_claim(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        with patch("digest_delivery.get_pool", new=AsyncMock(return_value=pool)):
            token = await claim_digest_delivery(
                digest_kind="business",
                recipient_key="-100500",
                delivery_date=date(2026, 8, 20),
            )

        self.assertIsNone(token)


if __name__ == "__main__":
    unittest.main()
