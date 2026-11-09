"""Регрессии security binding: startup import, guest cookie и атомарная CAPTCHA."""
from __future__ import annotations

import asyncio
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from starlette.requests import Request
from starlette.responses import Response

import math_captcha
from panel_cookies import guest_session_trusted, set_guest_cookie

ROOT = Path(__file__).resolve().parents[1]


def _request(*, cookie: str | None = None) -> Request:
    headers = []
    if cookie is not None:
        headers.append((b"cookie", f"focuspay_guest_session={cookie}".encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


class GuestBindingTests(unittest.TestCase):
    def test_cookie_must_match_header(self):
        self.assertTrue(guest_session_trusted(_request(cookie="same"), "same"))
        self.assertFalse(guest_session_trusted(_request(cookie="one"), "two"))

    def test_header_without_cookie_is_allowed_only_during_grace_period(self):
        before_grace_end = datetime(2026, 8, 27, tzinfo=timezone.utc)
        after_grace_end = datetime(2026, 8, 28, tzinfo=timezone.utc)

        self.assertTrue(
            guest_session_trusted(_request(), "legacy", now=before_grace_end)
        )
        self.assertFalse(
            guest_session_trusted(_request(), "legacy", now=after_grace_end)
        )

    def test_missing_header_is_not_a_trusted_guest_session(self):
        self.assertFalse(guest_session_trusted(_request(cookie="owner"), None))
        self.assertFalse(guest_session_trusted(_request(), None))

    def test_existing_cookie_cannot_be_overwritten_by_stolen_header(self):
        response = Response()
        self.assertFalse(set_guest_cookie(response, "stolen", _request(cookie="owner")))
        self.assertNotIn("set-cookie", response.headers)


class _Conn:
    def __init__(self, result):
        self.result = result
        self.sql = ""
        self.args = ()

    async def fetchval(self, sql, *args):
        self.sql = sql
        self.args = args
        return self.result

    async def fetchrow(self, sql, *args):
        return None


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_args):
        return None


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class CaptchaAtomicBindingTests(unittest.TestCase):
    def test_verify_is_single_atomic_update_with_client_bindings(self):
        conn = _Conn(7)
        fake_db = types.SimpleNamespace(get_pool=lambda: asyncio.sleep(0, result=_Pool(conn)))
        with patch.dict(sys.modules, {"db": fake_db}):
            ok = asyncio.run(
                math_captcha.verify_captcha(
                    "7",
                    "42",
                    guest_session="guest-id",
                    ip_address="203.0.113.9",
                    user_agent="browser",
                )
            )
        self.assertTrue(ok)
        self.assertIn("UPDATE captcha_challenges", conn.sql)
        self.assertIn("consumed_at IS NULL", conn.sql)
        self.assertIn("answer_hash = $2", conn.sql)
        self.assertIn("guest_session::text = $3", conn.sql)
        self.assertIn("ip_address = $4::inet", conn.sql)
        self.assertNotIn("ip_address::text = $4", conn.sql)
        self.assertIn("user_agent = $5", conn.sql)
        self.assertEqual(conn.args[2:], ("guest-id", "203.0.113.9", "browser"))

    def test_failed_atomic_update_rejects_replay_or_mismatch(self):
        conn = _Conn(None)
        fake_db = types.SimpleNamespace(get_pool=lambda: asyncio.sleep(0, result=_Pool(conn)))
        with patch.dict(sys.modules, {"db": fake_db}):
            ok = asyncio.run(math_captcha.verify_captcha("7", "wrong"))
        self.assertFalse(ok)


class StartupResponseImportTests(unittest.TestCase):
    def test_public_router_imports_response_used_in_signatures(self):
        source = (ROOT / "routers" / "public.py").read_text()
        self.assertIn("Request, Response", source)

    def test_human_check_alias_is_registered(self):
        from routers import public

        paths = {getattr(route, "path", None) for route in public.router.routes}
        self.assertIn("/captcha", paths)
        self.assertIn("/human-check", paths)


if __name__ == "__main__":
    unittest.main()
