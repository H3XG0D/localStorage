"""Операторские фразы антиспама: валидация и CRUD."""
from __future__ import annotations

import inspect
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from group_spam_phrases import (
    BUILTIN_PHRASE_LABELS,
    PHRASE_MIN_LEN,
    normalize_for_phrases,
    validate_operator_phrase,
)
from routers import operator_antispam

_PERMS = {"id": 1, "operator_roles": ["client"], "permissions": ["antispam.phrases"]}


def _enrich(op):
    out = dict(op)
    out["permissions"] = list(op.get("permissions") or ["antispam.phrases"])
    return out


def _pool(conn) -> MagicMock:
    mock_pool = MagicMock()
    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire
    return mock_pool


class NormalizeTests(unittest.TestCase):
    def test_homoglyphs_and_yo(self):
        self.assertEqual(normalize_for_phrases("Пишите в лc"), "пишите в лс")
        self.assertEqual(normalize_for_phrases("Ёлка"), "елка")

    def test_too_short(self):
        with self.assertRaises(ValueError):
            validate_operator_phrase("абв")

    def test_ok_phrase(self):
        display, normalized = validate_operator_phrase("  KLD777  ")
        self.assertEqual(display, "KLD777")
        self.assertEqual(normalized, normalize_for_phrases("KLD777"))
        self.assertGreaterEqual(len(normalized), PHRASE_MIN_LEN)

    def test_builtin_not_empty(self):
        self.assertGreaterEqual(len(BUILTIN_PHRASE_LABELS), 5)


class PhraseRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_returns_items_and_builtin(self):
        created = datetime(2026, 9, 1, tzinfo=timezone.utc)
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": 7,
                    "phrase": "KLD777",
                    "normalized": "kld777",
                    "created_by_operator_id": 1,
                    "created_at": created,
                }
            ]
        )
        with (
            patch(
                "routers.operator_antispam.enrich_operator_permissions",
                AsyncMock(side_effect=_enrich),
            ),
            patch("routers.operator_antispam.get_pool", AsyncMock(return_value=_pool(conn))),
        ):
            out = await operator_antispam.list_phrases(operator=dict(_PERMS))
        self.assertEqual(out["items"][0]["id"], 7)
        self.assertEqual(out["items"][0]["phrase"], "KLD777")
        self.assertIn("боты распределители", out["builtin"])

    async def test_create_conflict(self):
        class UniqueViolationError(Exception):
            pass

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=UniqueViolationError())
        with (
            patch(
                "routers.operator_antispam.enrich_operator_permissions",
                AsyncMock(side_effect=_enrich),
            ),
            patch("routers.operator_antispam.get_pool", AsyncMock(return_value=_pool(conn))),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await operator_antispam.create_phrase(
                    body=operator_antispam.PhraseBody(phrase="KLD777"),
                    operator=dict(_PERMS),
                )
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_create_rejects_short(self):
        with patch(
            "routers.operator_antispam.enrich_operator_permissions",
            AsyncMock(side_effect=_enrich),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await operator_antispam.create_phrase(
                    body=operator_antispam.PhraseBody(phrase="нет"),
                    operator=dict(_PERMS),
                )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_delete_missing(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        with (
            patch(
                "routers.operator_antispam.enrich_operator_permissions",
                AsyncMock(side_effect=_enrich),
            ),
            patch("routers.operator_antispam.get_pool", AsyncMock(return_value=_pool(conn))),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await operator_antispam.delete_phrase(9, operator=dict(_PERMS))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_routes_require_operator(self):
        for name in ("list_phrases", "create_phrase", "delete_phrase"):
            src = inspect.getsource(getattr(operator_antispam, name))
            self.assertIn("get_current_operator", src)

    def test_main_includes_router(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn("operator_antispam.router", src)


if __name__ == "__main__":
    unittest.main()
