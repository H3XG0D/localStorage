"""Operator digest delivery semantics."""
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from ops_ai_memory import run_due_digests


class OperatorDigestDeliveryTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _pool(rows):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx
        return pool

    async def test_losing_worker_does_not_send(self):
        pool = self._pool([{"id": 7, "telegram_user_id": 700, "username": "op"}])
        sender = AsyncMock(return_value=11)
        with patch("ops_ai_memory.get_pool", new=AsyncMock(return_value=pool)), patch(
            "digest_delivery.claim_digest_delivery", new=AsyncMock(return_value=None)
        ), patch("telegram_notify.send_admin_message", new=sender):
            sent = await run_due_digests(datetime.fromisoformat("2026-08-21T10:10:00+03:00"))

        self.assertEqual(sent, 0)
        sender.assert_not_awaited()

    async def test_none_from_telegram_releases_for_retry(self):
        pool = self._pool([{"id": 7, "telegram_user_id": 700, "username": "op"}])
        release = AsyncMock()
        complete = AsyncMock(return_value=True)
        with patch("ops_ai_memory.get_pool", new=AsyncMock(return_value=pool)), patch(
            "ops_ai_memory.build_digest_text", new=AsyncMock(return_value="digest")
        ), patch("digest_delivery.claim_digest_delivery", new=AsyncMock(return_value="claim")), patch(
            "digest_delivery.complete_digest_delivery", new=complete
        ), patch("digest_delivery.release_digest_delivery", new=release), patch(
            "telegram_notify.send_admin_message", new=AsyncMock(return_value=None)
        ):
            sent = await run_due_digests(datetime.fromisoformat("2026-08-21T10:10:00+03:00"))

        self.assertEqual(sent, 0)
        complete.assert_not_awaited()
        release.assert_awaited_once_with("claim")


if __name__ == "__main__":
    unittest.main()
