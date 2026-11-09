"""Tests for auto buy payout link delivery to client chat."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
NOTIFY_SRC = (ROOT / "buyer_payout_notify.py").read_text(encoding="utf-8")
INTERNAL_SRC = (ROOT / "routers" / "chat_internal.py").read_text(encoding="utf-8")
ORDER_SRC = (ROOT / "order_service.py").read_text(encoding="utf-8")


class BuyerPayoutNotifySourceTests(unittest.TestCase):
    def test_delivers_via_admin_chat(self):
        self.assertIn("admin_send_message", NOTIFY_SRC)
        self.assertIn("format_paid_chat_message", NOTIFY_SRC)

    def test_internal_endpoint_requires_token_and_paid_buy(self):
        self.assertIn('@router.post("/buyer/buy-payout-notify")', INTERNAL_SRC)
        self.assertIn("deliver_buy_payout_chat_message", INTERNAL_SRC)
        self.assertIn('reason": "not_paid"', INTERNAL_SRC)

    def test_public_order_response_exposes_explorer_url(self):
        self.assertIn('"payout_tx_hash"', ORDER_SRC)
        self.assertIn('"payout_explorer_url"', ORDER_SRC)

    def test_active_order_includes_recent_payout(self):
        web = (ROOT / "routers" / "web_orders.py").read_text(encoding="utf-8")
        self.assertIn("recent_payout_sent", NOTIFY_SRC)
        self.assertIn("payout_sent", web)


class RecentPayoutSentTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_paid_buy(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from buyer_payout_notify import recent_payout_sent

        row = {
            "order_id": "317",
            "crypto": "btc",
            "crypto_amount": 0.001,
            "fiat_amount": 5000,
            "requisites": "bc1qexample",
            "payout_tx_hash": "ab" * 32,
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=row)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx
        with patch("buyer_payout_notify.get_pool", new=AsyncMock(return_value=pool)):
            out = await recent_payout_sent(5)
        self.assertEqual(out["order_id"], "317")
        self.assertEqual(out["coin"], "BTC")
        self.assertIn("mempool.space/tx/", out["explorer_url"])


if __name__ == "__main__":
    unittest.main()
