"""News privacy: admin gate, targeting, rate/frequency, pseudonyms."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.news_privacy import pseudo_chat, pseudo_user
from services.news_subscriptions import ALLOWED_CATEGORIES, _norm_categories


class NewsPrivacyTests(unittest.TestCase):
    def test_pseudonyms_hide_raw_ids(self):
        p = pseudo_chat(-100123)
        self.assertTrue(p.startswith("chat_"))
        self.assertNotIn("100123", p)
        self.assertNotEqual(pseudo_user(1), pseudo_user(2))

    def test_categories(self):
        self.assertEqual(_norm_categories(["promo", "x", "promo"]), ["promo"])
        self.assertEqual(_norm_categories(None), ["general"])
        self.assertTrue(ALLOWED_CATEGORIES)


class NewsBroadcastGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limit_blocks(self):
        from services import news_broadcast as nb

        nb._rate_bucket.clear()
        with patch.object(nb, "rate_per_min", return_value=1):
            self.assertTrue(nb._rate_ok())
            self.assertFalse(nb._rate_ok())

    async def test_create_job_requires_frequency_cap(self):
        from services import news_broadcast as nb

        nb._rate_bucket.clear()

        class Conn:
            async def fetchrow(self, *a, **k):
                # pretend recent job exists
                return {"id": 1}

            async def execute(self, *a, **k):
                return "OK"

        class Pool:
            def acquire(self):
                return self

            async def __aenter__(self):
                return Conn()

            async def __aexit__(self, *a):
                return False

        with patch.object(nb, "get_pool", new=AsyncMock(return_value=Pool())):
            with patch.object(nb, "_rate_ok", return_value=True):
                with self.assertRaises(PermissionError):
                    await nb.create_job(
                        actor_id=1,
                        body_html="hi",
                        category="general",
                        idempotency_key="k1",
                    )


class NewsAdminGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_admin_cannot_send(self):
        from handlers import news_subscribe as hs

        update = MagicMock()
        update.effective_user.id = 999001
        update.message = AsyncMock()
        context = MagicMock()
        with patch.object(hs, "TELEGRAM_ADMIN_IDS", [1, 2]):
            await hs.news_send(update, context)
        update.message.reply_text.assert_awaited()
        args = update.message.reply_text.await_args[0][0]
        self.assertIn("Только админ", args)


if __name__ == "__main__":
    unittest.main()
