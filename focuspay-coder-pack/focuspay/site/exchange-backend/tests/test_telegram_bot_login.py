"""Casino bot-start login: cauth_ parse, casino return_path, one-shot wait/ticket."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from telegram_bot_login import (  # noqa: E402
    CAUTH_PREFIX,
    TTL_SECONDS,
    attach_telegram_to_start,
    cauth_deep_link,
    consume_ticket,
    consume_wait,
    create_bot_login,
    extract_cauth_token,
    hash_login_token,
    sanitize_casino_return_path,
)


def _pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    return pool


class ExtractCauthTests(unittest.TestCase):
    def test_prefix_and_start(self):
        token = "a" * 32
        self.assertEqual(extract_cauth_token(f"cauth_{token}"), token)
        self.assertEqual(extract_cauth_token(f"/start cauth_{token}"), token)
        self.assertEqual(extract_cauth_token(token), None)
        self.assertIsNone(extract_cauth_token("cauth_short"))
        self.assertIsNone(extract_cauth_token("opsbind_ABCDEFGH12"))
        self.assertIsNone(extract_cauth_token("ref_abc123xyz999"))
        self.assertIsNone(extract_cauth_token(""))
        self.assertIsNone(extract_cauth_token(None))

    def test_deep_link_uses_casino_bot(self):
        token = "b" * 32
        settings = MagicMock()
        settings.telegram_bot_username = "focuspay1_bot"
        settings.casino_bot_username = "focusludka_bot"
        with patch("config.settings", settings):
            url = cauth_deep_link(token)
        self.assertEqual(url, f"https://t.me/focusludka_bot?start={CAUTH_PREFIX}{token}")
        self.assertNotIn("focuspay1_bot", url)
        self.assertLessEqual(len(f"{CAUTH_PREFIX}{token}"), 64)

    def test_deep_link_falls_back_to_ludka(self):
        settings = MagicMock()
        settings.telegram_bot_username = "focuspay1_bot"
        settings.casino_bot_username = ""
        with patch("config.settings", settings):
            url = cauth_deep_link("c" * 32)
        self.assertIn("t.me/focusludka_bot?start=cauth_", url)

    def test_ttl_is_ten_minutes(self):
        self.assertEqual(TTL_SECONDS, 600)


class ReturnPathTests(unittest.TestCase):
    def test_casino_only(self):
        self.assertEqual(sanitize_casino_return_path("/casino"), "/casino")
        self.assertEqual(
            sanitize_casino_return_path("/casino/play/roulette?mode=house"),
            "/casino/play/roulette?mode=house",
        )
        self.assertEqual(sanitize_casino_return_path("/cabinet"), "/casino")
        self.assertEqual(sanitize_casino_return_path("/login"), "/casino")
        self.assertEqual(sanitize_casino_return_path("/login/telegram"), "/casino")
        self.assertEqual(sanitize_casino_return_path("//evil"), "/casino")
        self.assertEqual(sanitize_casino_return_path("https://evil.com/casino"), "/casino")
        self.assertEqual(sanitize_casino_return_path(None), "/casino")


class BotLoginDbTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_inserts_hashed_start_token(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        settings = MagicMock()
        settings.telegram_bot_username = "focuspay1_bot"
        settings.casino_bot_username = "focusludka_bot"
        settings.public_site_url = "https://focuspay.org"
        with (
            patch("telegram_bot_login._pool", new=AsyncMock(return_value=_pool(conn))),
            patch("config.settings", settings),
        ):
            out = await create_bot_login("/casino/wallet")
        self.assertIn("cauth_", out["deep_link"])
        self.assertEqual(len(out["wait_token"]), 32)
        self.assertEqual(out["return_path"], "/casino/wallet")
        inserted_hash = conn.execute.await_args.args[1]
        self.assertEqual(inserted_hash, hash_login_token(out["wait_token"]))
        self.assertNotEqual(inserted_hash, out["wait_token"])

    async def test_attach_then_wait_consumes_once(self):
        token = "c" * 32
        expires = datetime.now(timezone.utc) + timedelta(minutes=5)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"return_path": "/casino/me", "expires_at": expires},
                {
                    "telegram_user_id": 77,
                    "tg_username": "alice",
                    "tg_first_name": "Alice",
                    "return_path": "/casino/me",
                    "wait_consumed_at": None,
                },
            ]
        )
        with patch("telegram_bot_login._pool", new=AsyncMock(return_value=_pool(conn))):
            attached = await attach_telegram_to_start(
                f"cauth_{token}", 77, username="alice", first_name="Alice"
            )
            self.assertEqual(attached["return_path"], "/casino/me")
            self.assertEqual(len(attached["ticket"]), 32)
            self.assertIn("ticket=", attached["url"])

            status, row = await consume_wait(token)
        self.assertEqual(status, "ready")
        self.assertEqual(row["telegram_user_id"], 77)
        wait_sql = conn.fetchrow.await_args_list[1].args[0]
        self.assertIn("wait_consumed_at = now()", wait_sql)
        self.assertIn("wait_consumed_at IS NULL", wait_sql)

    async def test_wait_pending_when_no_telegram(self):
        token = "d" * 32
        expires = datetime.now(timezone.utc) + timedelta(minutes=5)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                None,
                {
                    "telegram_user_id": None,
                    "wait_consumed_at": None,
                    "expires_at": expires,
                },
            ]
        )
        with patch("telegram_bot_login._pool", new=AsyncMock(return_value=_pool(conn))):
            status, _row = await consume_wait(token)
        self.assertEqual(status, "pending")

    async def test_wait_expired_unknown_token(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, None])
        with patch("telegram_bot_login._pool", new=AsyncMock(return_value=_pool(conn))):
            status, row = await consume_wait("e" * 32)
        self.assertEqual(status, "expired")
        self.assertIsNone(row)

    async def test_ticket_one_shot(self):
        ticket = "f" * 32
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"telegram_user_id": 9, "return_path": "/casino"},
                None,
            ]
        )
        with patch("telegram_bot_login._pool", new=AsyncMock(return_value=_pool(conn))):
            first = await consume_ticket(ticket)
            second = await consume_ticket(ticket)
        self.assertEqual(first["telegram_user_id"], 9)
        self.assertIsNone(second)
        sql = conn.fetchrow.await_args_list[0].args[0]
        self.assertIn("ticket_consumed_at IS NULL", sql)

    async def test_router_has_three_endpoints(self):
        src = (_BACKEND / "routers/auth_router.py").read_text(encoding="utf-8")
        self.assertIn('@router.post("/telegram/bot-start")', src)
        self.assertIn('@router.get("/telegram/bot-wait")', src)
        self.assertIn('@router.post("/telegram/bot-complete")', src)
        self.assertIn('@router.post("/telegram/bot-attach")', src)
        self.assertIn("upsert_web_user_from_telegram", src)
        login_src = (_BACKEND / "telegram_bot_login.py").read_text(encoding="utf-8")
        self.assertIn("casino_bot_username", login_src)
        self.assertIn("focusludka_bot", login_src)


if __name__ == "__main__":
    unittest.main()
