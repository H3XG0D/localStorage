"""Bind API + /ops/profile: router, auth, opsbind_ формат, SPA-маршрут."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import operator as _stdlib_operator

sys.modules["operator"] = _stdlib_operator

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

for _name in ("asyncpg", "db", "config", "telegram_notify"):
    sys.modules.setdefault(_name, MagicMock())

import ops_ai_memory as mem  # noqa: E402
from ops_ai_ui_context import page_label  # noqa: E402


class OperatorAiTelegramRouteTests(unittest.TestCase):
    def test_bind_endpoints_require_operator_auth(self):
        src = (_BACKEND / "routers/operator_ai.py").read_text(encoding="utf-8")
        self.assertIn("@router.get(\"/ai/telegram\")", src)
        self.assertIn("@router.post(\"/ai/telegram/bind-link\")", src)
        self.assertIn("@router.delete(\"/ai/telegram\")", src)
        self.assertIn("Depends(get_current_operator)", src)
        self.assertIn("async def ai_telegram_bind_link", src)

    def test_main_includes_operator_ai_router(self):
        src = (_BACKEND / "main.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(operator_ai.router, prefix=\"/api/operator\"", src)

    def test_ops_profile_page_label(self):
        self.assertEqual(page_label("/ops/profile"), "Профиль оператора")

    def test_frontend_ops_profile_route_exists(self):
        routes = _ROOT / "focussite/frontend/src/panel/operator/OperatorRoutes.tsx"
        src = routes.read_text(encoding="utf-8")
        self.assertIn('to: "/ops/profile"', src)
        self.assertIn('path="profile"', src)
        self.assertIn("OperatorProfile", src)


class BindLinkFormatTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_bind_link_opsbind_and_command(self):
        row = {
            "id": 1,
            "username": "alice",
            "display_name": "Alice",
            "telegram_user_id": None,
            "ops_ai_digest_enabled": False,
            "ops_ai_digest_hour": 10,
            "telegram_bind_expires_at": None,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        pool = MagicMock()
        pool.acquire = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        sys.modules["config"].settings.telegram_bot_username = "focuspay1_bot"
        with patch.object(mem, "get_pool", new=AsyncMock(return_value=pool)):
            out = await mem.create_bind_link(1)
        self.assertTrue(out["token"])
        self.assertIn("opsbind_", out["deep_link"])
        self.assertTrue(out["command"].startswith("/ops_bind "))
        self.assertIn(out["token"], out["deep_link"])
        self.assertIn(out["token"], out["command"])

    async def test_bind_strips_opsbind_prefix(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {
                    "id": 4,
                    "username": "bob",
                    "display_name": "Bob",
                    "telegram_user_id": None,
                    "telegram_bind_expires_at": None,
                },
                {
                    "id": 4,
                    "username": "bob",
                    "display_name": "Bob",
                    "telegram_user_id": 77,
                    "ops_ai_digest_enabled": True,
                    "ops_ai_digest_hour": 10,
                },
            ]
        )
        conn.execute = AsyncMock()
        pool = MagicMock()
        pool.acquire = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        with patch.object(mem, "get_pool", new=AsyncMock(return_value=pool)):
            out = await mem.bind_operator_telegram("opsbind_ABCDEFGH12", 77)
        self.assertEqual(out["telegram_user_id"], 77)
        self.assertEqual(conn.fetchrow.await_args_list[0].args[1], "ABCDEFGH12")


if __name__ == "__main__":
    unittest.main()
