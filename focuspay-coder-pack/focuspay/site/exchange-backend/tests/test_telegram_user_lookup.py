"""Поиск клиента по @username."""
import unittest
from unittest.mock import AsyncMock, patch

from telegram_user_lookup import (
    looks_like_telegram_username,
    normalize_search_term,
    resolve_single_recipient,
    search_client_by_telegram,
    user_hit,
)


class TelegramUserLookupTests(unittest.TestCase):
    def test_normalize_strips_at(self):
        self.assertEqual(normalize_search_term("  @Ivan_Test  "), "Ivan_Test")

    def test_username_pattern(self):
        self.assertTrue(looks_like_telegram_username("focus_user"))
        self.assertFalse(looks_like_telegram_username("ab"))
        self.assertFalse(looks_like_telegram_username("12345"))

    def test_user_hit_display(self):
        h = user_hit(99, "alice", "Алиса")
        self.assertEqual(h["display"], "@alice")
        self.assertEqual(h["user_id"], 99)
        self.assertFalse(h["is_banned"])
        self.assertIsNone(h["ban_type"])

    def test_user_hit_soft_ban(self):
        h = user_hit(1, "x", "Y", is_banned=True, ban_type="soft")
        self.assertTrue(h["is_banned"])
        self.assertEqual(h["ban_type"], "soft")


class TelegramUserLookupAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_api_first_when_username_changed(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchrow = AsyncMock(
            return_value={"is_banned": True, "ban_type": "soft"}
        )
        api_hit = user_hit(7099845324, "spokkiinokkii", "Test")

        with patch(
            "telegram_user_lookup._resolve_username_via_api_first",
            new=AsyncMock(return_value=api_hit),
        ):
            hits = await search_client_by_telegram(conn, "@spokkiinokkii", limit=5)

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["user_id"], 7099845324)
        self.assertEqual(hits[0]["username"], "spokkiinokkii")
        self.assertTrue(hits[0]["is_banned"])
        self.assertEqual(hits[0]["ban_type"], "soft")

    async def test_resolve_single_recipient_prefers_api_over_stale_db(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "is_banned": False,
                "ban_type": "hard",
            }
        )
        api_hit = user_hit(7099845324, "spokkiinokkii", "Actual")

        with patch(
            "telegram_user_lookup._resolve_username_via_api_first",
            new=AsyncMock(return_value=api_hit),
        ):
            hit = await resolve_single_recipient(conn, "spokkiinokkii")

        self.assertEqual(hit["user_id"], 7099845324)
        # enrich_hit_ban calls fetchrow for ban fields
        conn.fetchrow.assert_awaited()

    async def test_resolve_single_recipient_falls_back_to_db(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "user_id": 111,
                "username": "spokkiinokkii",
                "first_name": "FromDb",
                "is_banned": True,
                "ban_type": "soft",
            }
        )

        with patch(
            "telegram_user_lookup._resolve_username_via_api_first",
            new=AsyncMock(return_value=None),
        ):
            hit = await resolve_single_recipient(conn, "spokkiinokkii")

        self.assertEqual(hit["user_id"], 111)
        self.assertTrue(hit["is_banned"])
        self.assertEqual(hit["ban_type"], "soft")
        self.assertEqual(hit["user_id"], 111)
        conn.fetchrow.assert_called_once()


if __name__ == "__main__":
    unittest.main()
