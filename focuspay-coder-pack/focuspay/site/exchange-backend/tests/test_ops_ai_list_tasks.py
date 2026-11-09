"""list_tasks: stable created_at/id ordering (no live DB required)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Local operator.py shadows stdlib; pin stdlib first when backend is on path.
import operator as _stdlib_operator

sys.modules["operator"] = _stdlib_operator

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# Lightweight stubs so ops_ai_service imports without asyncpg/config.
for _name in ("asyncpg", "db", "ops_ai_llm", "ops_ai_rag", "config", "telegram_notify"):
    sys.modules.setdefault(_name, MagicMock())

import ops_ai_service as svc  # noqa: E402


class ListTasksOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_orders_by_created_at_then_id_desc(self):
        conn = AsyncMock()
        newer = {"id": 2, "title": "b", "status": "review", "created_at": "2026-08-12T12:00:00Z"}
        older = {"id": 1, "title": "a", "status": "review", "created_at": "2026-08-12T11:00:00Z"}
        conn.fetch = AsyncMock(return_value=[newer, older])
        conn.fetchval = AsyncMock(return_value=2)

        pool = MagicMock()
        pool.acquire = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch.object(svc, "get_pool", new=AsyncMock(return_value=pool)):
            out = await svc.list_tasks(status="review", limit=50, offset=0)

        fetch_args = conn.fetch.await_args.args
        sql = fetch_args[0]
        self.assertIn("ORDER BY created_at DESC, id DESC", sql)
        self.assertIn("status = $1", sql)
        self.assertEqual(list(fetch_args[1:]), ["review", 50, 0])
        self.assertEqual(list(conn.fetchval.await_args.args[1:]), ["review"])
        self.assertEqual([t["id"] for t in out["tasks"]], [2, 1])
        self.assertEqual(out["total"], 2)


if __name__ == "__main__":
    unittest.main()
