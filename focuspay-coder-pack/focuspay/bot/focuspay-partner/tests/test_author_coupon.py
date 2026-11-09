"""Первый ролик фиксирует купон, баннер уходит через sendVideo."""
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from banner_video import BANNER_NAME, banner_video_path, send_banner_video
from exchange_link import coupon_payload, lock_first_video_coupon


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE users(id INTEGER PRIMARY KEY, promo TEXT);
        CREATE TABLE videos(
          id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT
        );
        CREATE TABLE promo_codes(
          code TEXT PRIMARY KEY, author_id INTEGER, max_uses INTEGER, expires INTEGER, exchange_synced INTEGER DEFAULT 0
        );
        """
    )
    return conn


class FirstVideoCouponTests(unittest.TestCase):
    def test_locks_only_the_first_approved_video(self):
        conn = _db()
        conn.execute("INSERT INTO users(id, promo) VALUES(7, 'VOVA7K')")
        conn.execute("INSERT INTO videos(id, user_id, status) VALUES(1, 7, 'approved')")
        conn.execute("INSERT INTO promo_codes(code, author_id, max_uses, expires) VALUES('VOVA7K', 7, 10, 999)")
        conn.commit()
        self.assertEqual(lock_first_video_coupon(conn, 7), "VOVA7K")
        row = conn.execute("SELECT max_uses, expires FROM promo_codes WHERE code='VOVA7K'").fetchone()
        self.assertEqual(row, (100, 0))
        conn.execute("INSERT INTO videos(id, user_id, status) VALUES(2, 7, 'approved')")
        conn.commit()
        self.assertIsNone(lock_first_video_coupon(conn, 7))

    def test_pending_video_does_not_issue(self):
        conn = _db()
        conn.execute("INSERT INTO users(id, promo) VALUES(7, 'VOVA7K')")
        conn.execute("INSERT INTO videos(id, user_id, status) VALUES(1, 7, 'pending')")
        conn.commit()
        self.assertIsNone(lock_first_video_coupon(conn, 7))

    def test_payload_does_not_let_the_bot_set_the_discount(self):
        body = coupon_payload(code="VOVA7K", author_telegram_id=7, video_id=1, issued_for="first_video", author_name="@vova")
        self.assertEqual(body["code"], "VOVA7K")
        self.assertNotIn("discount_rub", body)
        self.assertNotIn("max_activations", body)
        self.assertEqual(body["issued_for"], "first_video")


class BannerVideoTests(unittest.IsolatedAsyncioTestCase):
    def test_finds_professional_filename(self):
        root = Path(__file__).resolve().parents[1] / "materials"
        found = banner_video_path(root)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, BANNER_NAME)
        self.assertEqual(found.suffix, ".mp4")
        self.assertGreater(found.stat().st_size, 1000)

    async def test_send_video_not_document(self):
        bot = AsyncMock()
        marker = object()
        await send_banner_video(bot, 15, Path("partner_banner.mp4"), "caption", video=marker)
        bot.send_video.assert_awaited_once()
        kwargs = bot.send_video.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], 15)
        self.assertIs(kwargs["video"], marker)
        self.assertIn("caption", kwargs)
        self.assertTrue(kwargs["supports_streaming"])
        bot.send_document.assert_not_called()
