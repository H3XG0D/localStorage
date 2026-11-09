"""Admin users list attaches signed Telegram avatar URLs."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot_user_avatars import bot_user_avatar_public_url, prefetch_bot_user_avatars


class BotUserAvatarUrlTests(unittest.TestCase):
    def test_telegram_id_gets_signed_path(self):
        with patch("bot_user_avatars.make_attachment_access_token", return_value="tok"):
            url = bot_user_avatar_public_url(42)
        self.assertEqual(url, "/api/public/bot-user-avatars/42?access=tok")

    def test_skips_synthetic_web_ids(self):
        self.assertIsNone(bot_user_avatar_public_url(-7))
        self.assertIsNone(bot_user_avatar_public_url(0))
        self.assertIsNone(bot_user_avatar_public_url(None))


class PrefetchAvatarTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetches_missing_positive_ids_once(self):
        with patch("bot_user_avatars.resolve_bot_user_avatar_path", return_value=None), patch(
            "bot_user_avatars.fetch_and_cache_bot_user_avatar",
            AsyncMock(),
        ) as fetch:
            await prefetch_bot_user_avatars([0, -3, 10, 10, 11, "nope"])  # type: ignore[list-item]
        self.assertEqual([c.args[0] for c in fetch.call_args_list], [10, 11])

    async def test_skips_already_cached(self):
        with patch(
            "bot_user_avatars.resolve_bot_user_avatar_path",
            return_value="/tmp/10.jpg",
        ), patch(
            "bot_user_avatars.fetch_and_cache_bot_user_avatar",
            AsyncMock(),
        ) as fetch:
            await prefetch_bot_user_avatars([10])
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
