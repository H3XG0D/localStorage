"""Команда /reki в боте внештатников и подсказка при отказе в реквизите."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

if "asyncpg" not in sys.modules:  # локальный прогон без драйвера БД
    sys.modules["asyncpg"] = MagicMock()

import exchanger_bot_handlers as handlers  # noqa: E402
from exchanger_bot_commands import is_reki_command
from reki_snapshot import SUB_TOKEN_CARD, SUB_TOKEN_SBP, parse_reki_snapshot, reki_public_out
from reki_store import load_reki_snapshot

SAMPLE = """🟢 Количество активных СБП: 2
💸 Доступно всего: 5503 RUB
🟢 2403 RUB - 2403 RUB
💸 Доступно: 2403 RUB
🟢 3000 RUB - 3100 RUB
💸 Доступно: 3100 RUB

🟢 Количество активных C2C: 1
💸 Доступно всего: 2500 RUB
🟢 2500 RUB - 2500 RUB
💸 Доступно: 2500 RUB"""

MEMBER = {"telegram_user_id": 777, "exchanger_id": 5, "role": "owner"}


def _conn(meta_rows, band_rows):
    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=[meta_rows, band_rows])
    return conn


def _pool(conn):
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire)
    return pool


def _fresh_rows():
    now = datetime.now(timezone.utc)
    meta = [
        {"sub_token": SUB_TOKEN_SBP, "count": 2, "total_rub": Decimal("5503.00"), "snapshot_at": now},
        {"sub_token": SUB_TOKEN_CARD, "count": 1, "total_rub": Decimal("2500.00"), "snapshot_at": now},
    ]
    bands = [
        {"sub_token": SUB_TOKEN_SBP, "min_rub": Decimal("2403"), "max_rub": Decimal("2403"), "available_rub": Decimal("2403")},
        {"sub_token": SUB_TOKEN_SBP, "min_rub": Decimal("3000"), "max_rub": Decimal("3100"), "available_rub": Decimal("3100")},
        {"sub_token": SUB_TOKEN_CARD, "min_rub": Decimal("2500"), "max_rub": Decimal("2500"), "available_rub": Decimal("2500")},
    ]
    return meta, bands


class CommandTests(unittest.TestCase):
    def test_reki_command_aliases(self):
        for text in ("/reki", "/reki@shopbot", "реки", "Реквизиты"):
            self.assertTrue(is_reki_command(text), text)
        for text in ("сбп 5400", "баланс", "/who", ""):
            self.assertFalse(is_reki_command(text), text)


class StoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_snapshot(self):
        meta, bands = _fresh_rows()
        snapshot = await load_reki_snapshot(_conn(meta, bands))
        self.assertEqual(len(snapshot.bands(SUB_TOKEN_SBP)), 2)
        self.assertEqual(snapshot.section(SUB_TOKEN_CARD).total_rub, Decimal("2500.00"))
        self.assertTrue(snapshot.is_fresh())

    async def test_missing_table_is_not_fatal(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(side_effect=RuntimeError("relation does not exist"))
        self.assertIsNone(await load_reki_snapshot(conn))

    async def test_empty_meta(self):
        self.assertIsNone(await load_reki_snapshot(_conn([], [])))


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_reki_lists_free_bands(self):
        meta, bands = _fresh_rows()
        pool = _pool(_conn(meta, bands))
        send = AsyncMock()
        with patch.object(handlers, "get_pool", AsyncMock(return_value=pool)), patch.object(
            handlers, "send_message", send
        ):
            await handlers._handle_reki("tok", MEMBER)
        text = send.await_args.args[2]
        self.assertIn("СБП", text)
        self.assertIn("3 000 – 3 100 ₽", text)
        self.assertEqual(send.await_args.kwargs["parse_mode"], "HTML")

    async def test_reki_without_snapshot(self):
        pool = _pool(_conn([], []))
        send = AsyncMock()
        with patch.object(handlers, "get_pool", AsyncMock(return_value=pool)), patch.object(
            handlers, "send_message", send
        ):
            await handlers._handle_reki("tok", MEMBER)
        self.assertIn("нет", send.await_args.args[2])

    async def test_refusal_carries_nearest_window(self):
        meta, bands = _fresh_rows()
        pool = _pool(_conn(meta, bands))
        send = AsyncMock()
        with patch.object(handlers, "get_pool", AsyncMock(return_value=pool)), patch.object(
            handlers, "send_message", send
        ), patch.object(
            handlers,
            "create_cabinet_deal_with_payin",
            AsyncMock(side_effect=HTTPException(status_code=409, detail="Нет свободных реквизитов")),
        ):
            await handlers._handle_requisite("tok", MEMBER, 2950.0, SUB_TOKEN_SBP)
        text = send.await_args.args[2]
        self.assertIn("Нет свободных реквизитов", text)
        self.assertIn("3 000", text)
        self.assertIn("больше запрошенной", text)

    async def test_refusal_without_snapshot_keeps_original_text(self):
        pool = _pool(_conn([], []))
        send = AsyncMock()
        with patch.object(handlers, "get_pool", AsyncMock(return_value=pool)), patch.object(
            handlers, "send_message", send
        ), patch.object(
            handlers,
            "create_cabinet_deal_with_payin",
            AsyncMock(side_effect=HTTPException(status_code=409, detail="Нет свободных реквизитов")),
        ):
            await handlers._handle_requisite("tok", MEMBER, 2950.0, SUB_TOKEN_SBP)
        self.assertEqual(send.await_args.args[2], "Нет свободных реквизитов")

    async def test_parsed_sample_matches_store_shape(self):
        snapshot = parse_reki_snapshot(SAMPLE, taken_at=datetime.now(timezone.utc))
        meta, bands = _fresh_rows()
        stored = await load_reki_snapshot(_conn(meta, bands))
        self.assertEqual(
            [(b.min_rub, b.max_rub) for b in snapshot.bands(SUB_TOKEN_SBP)],
            [(b.min_rub, b.max_rub) for b in stored.bands(SUB_TOKEN_SBP)],
        )


class PublicOutTests(unittest.TestCase):
    def test_fresh_snapshot_payload(self):
        snapshot = parse_reki_snapshot(SAMPLE, taken_at=datetime.now(timezone.utc))
        out = reki_public_out(snapshot)
        self.assertFalse(out["stale"])
        self.assertEqual(len(out["sections"]), 2)
        sbp = next(s for s in out["sections"] if s["sub_token"] == SUB_TOKEN_SBP)
        self.assertEqual(sbp["count"], 2)
        self.assertEqual(len(sbp["bands"]), 2)
        self.assertEqual(sbp["bands"][0]["min_rub"], 2403.0)
        self.assertIsNotNone(out["snapshot_at"])

    def test_empty_is_stale(self):
        out = reki_public_out(None)
        self.assertTrue(out["stale"])
        self.assertEqual(out["sections"][0]["bands"], [])
        self.assertIsNone(out["snapshot_at"])


if __name__ == "__main__":
    unittest.main()
