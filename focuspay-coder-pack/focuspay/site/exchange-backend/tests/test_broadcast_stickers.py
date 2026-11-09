"""Allowlist, fallback, and empty-catalog behavior for broadcast stickers."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

import broadcast_stickers as bst
import broadcast_service as bs

PROMO = {"id": "AgADpromo01", "emoji": "✨", "file_id": "fid-promo", "label": "✨"}
NEWS = {"id": "AgADnews01", "emoji": "📝", "file_id": "fid-news", "label": "📝"}
STAR = {"id": "AgADstar01", "emoji": "⭐", "file_id": "fid-star", "label": "⭐"}
CATALOG = [PROMO, NEWS, STAR]
KNOWN = {item["id"] for item in CATALOG}


class CatalogAllowlistTests(unittest.TestCase):
    def test_unknown_sticker_id_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            bst.validate_sticker_ids(["not_a_slug"], catalog_ids=KNOWN)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_old_brand_slug_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            bst.validate_sticker_ids(["09_news"], catalog_ids=KNOWN)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_telegram_file_id_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            bst.validate_sticker_ids(["CAACAgIAAxkBAAI"], catalog_ids=KNOWN)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_known_unique_id_accepted(self):
        self.assertEqual(
            bst.validate_sticker_ids(["AgADnews01"], catalog_ids=KNOWN),
            ["AgADnews01"],
        )

    def test_max_one(self):
        with self.assertRaises(HTTPException) as ctx:
            bst.validate_sticker_ids(["AgADnews01", "AgADpromo01"], catalog_ids=KNOWN)
        self.assertEqual(ctx.exception.status_code, 400)


class FallbackTests(unittest.TestCase):
    def test_promo_maps_to_sparkles(self):
        self.assertEqual(bst.pick_fallback_sticker_id("Новый промокод на скидку", CATALOG), "AgADpromo01")

    def test_raffle_maps_to_sparkles(self):
        self.assertEqual(bst.pick_fallback_sticker_id("еженедельный розыгрыш", CATALOG), "AgADpromo01")

    def test_default_star(self):
        self.assertEqual(bst.pick_fallback_sticker_id("Обновление сервиса", CATALOG), "AgADnews01")

    def test_auto_empty_selection_uses_fallback(self):
        ids, status = bst.plan_sticker_ids(
            sticker_mode="auto",
            selected_sticker_ids=[],
            text="Курс вырос",
            catalog=CATALOG,
        )
        self.assertEqual(ids, ["AgADstar01"])
        self.assertEqual(status, bst.STICKER_STATUS_AUTO)

    def test_none_mode_no_stickers(self):
        ids, status = bst.plan_sticker_ids(
            sticker_mode="none",
            selected_sticker_ids=["AgADnews01"],
            text="hello",
            catalog=CATALOG,
        )
        self.assertEqual(ids, [])
        self.assertEqual(status, bst.STICKER_STATUS_NONE)


class ResolveAndJobRowTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_sets_skip_without_file_id(self):
        with patch(
            "broadcast_stickers.list_live_catalog",
            AsyncMock(return_value=[]),
        ):
            fids, status = await bst.resolve_sticker_file_ids(["AgADnews01"])
        self.assertEqual(fids, [])
        self.assertEqual(status, bst.STICKER_STATUS_SKIPPED_EMPTY)

    async def test_resolve_matches_unique_id_from_allowlisted_set(self):
        with patch(
            "broadcast_stickers.list_live_catalog",
            AsyncMock(return_value=CATALOG),
        ):
            fids, status = await bst.resolve_sticker_file_ids(["AgADnews01"])
        self.assertEqual(fids, ["fid-news"])
        self.assertIsNone(status)

    def test_old_job_row_without_sticker_columns(self):
        row = {
            "id": 1,
            "sender_role": "admin",
            "sender_id": 1,
            "segment": "all",
            "message_text": "hi",
            "status": "done",
            "total_count": 1,
            "sent_count": 1,
            "failed_count": 0,
        }
        job = bs._job_row(row)
        self.assertEqual(job["sticker_ids"], [])
        self.assertEqual(job["sticker_mode"], "none")
        self.assertEqual(job["sticker_status"], "none")
        self.assertEqual(job["stickers"], [])

    async def test_preview_and_plan_ignore_auto_when_disabled(self):
        with patch(
            "broadcast_stickers.list_live_catalog",
            AsyncMock(return_value=CATALOG),
        ):
            preview = await bs.preview_stickers(
                sticker_mode="auto",
                selected_sticker_ids=[],
                text="Новый промокод на скидку",
                apply_stickers=True,
            )
            planned_ids, status, mode = await bs._plan_stickers(
                apply_stickers=True,
                sticker_mode="auto",
                selected_sticker_ids=[],
                text="Новый промокод на скидку",
            )
        self.assertEqual(preview["stickers"], [])
        self.assertEqual(preview["sticker_mode"], "none")
        self.assertEqual(planned_ids, [])
        self.assertEqual(status, bst.STICKER_STATUS_NONE)
        self.assertEqual(mode, "none")


class CreateJobStickerCompatTests(unittest.IsolatedAsyncioTestCase):
    async def test_omitted_mode_does_not_attach_stickers(self):
        captured = {}

        class FakeConn:
            async def fetchval(self, query, *args):
                return 0

            async def fetchrow(self, query, *args):
                captured["args"] = args
                return {
                    "id": 9,
                    "sender_role": args[0],
                    "sender_id": args[1],
                    "sender_label": args[2],
                    "segment": args[3],
                    "message_text": args[4],
                    "photo_file_id": args[5],
                    "status": "pending",
                    "total_count": 0,
                    "sent_count": 0,
                    "failed_count": 0,
                    "sticker_ids": args[6],
                    "sticker_mode": args[7],
                    "sticker_status": args[8],
                    "scheduled_at": args[9],
                    "schedule_id": args[10],
                    "created_at": None,
                    "started_at": None,
                    "finished_at": None,
                    "error_summary": None,
                }

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class FakePool:
            def acquire(self):
                return FakeConn()

        with patch("broadcast_service.get_pool", AsyncMock(return_value=FakePool())), patch(
            "broadcast_service.kick_worker"
        ):
            job = await bs.create_job(
                sender_role="admin",
                sender_id=1,
                sender_label="a",
                segment="all",
                message_text="hello",
            )
        self.assertEqual(job["sticker_ids"], [])
        self.assertEqual(captured["args"][7], "none")
        self.assertIsNone(captured["args"][6])
        self.assertIsNone(captured["args"][9])

    def test_broadcast_stickers_stay_disabled(self):
        self.assertFalse(bs.BROADCAST_STICKERS_ENABLED)

    async def test_auto_mode_does_not_attach_when_stickers_disabled(self):
        captured = {}

        class FakeConn:
            async def fetchval(self, query, *args):
                return 0

            async def fetchrow(self, query, *args):
                captured["args"] = args
                return {
                    "id": 11,
                    "sender_role": args[0],
                    "sender_id": args[1],
                    "sender_label": args[2],
                    "segment": args[3],
                    "message_text": args[4],
                    "photo_file_id": args[5],
                    "status": "pending",
                    "total_count": 0,
                    "sent_count": 0,
                    "failed_count": 0,
                    "sticker_ids": args[6],
                    "sticker_mode": args[7],
                    "sticker_status": args[8],
                    "scheduled_at": args[9],
                    "schedule_id": args[10],
                    "created_at": None,
                    "started_at": None,
                    "finished_at": None,
                    "error_summary": None,
                }

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class FakePool:
            def acquire(self):
                return FakeConn()

        with patch("broadcast_service.get_pool", AsyncMock(return_value=FakePool())), patch(
            "broadcast_service.kick_worker"
        ), patch(
            "broadcast_stickers.list_live_catalog",
            AsyncMock(return_value=CATALOG),
        ):
            job = await bs.create_job(
                sender_role="operator",
                sender_id=2,
                sender_label="op",
                segment="all",
                message_text="Новый промокод на скидку",
                sticker_mode="auto",
                apply_stickers=True,
            )
        self.assertEqual(job["sticker_ids"], [])
        self.assertEqual(job["sticker_mode"], "none")
        self.assertEqual(captured["args"][7], "none")
        self.assertIsNone(captured["args"][6])


class CatalogDisabledTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_project_stickers_empty_when_disabled(self):
        from routers import broadcast_handlers as bh

        with patch(
            "broadcast_stickers.list_live_catalog",
            AsyncMock(return_value=CATALOG),
        ):
            out = await bh.list_project_stickers()
        self.assertEqual(out["stickers"], [])
        self.assertTrue(out["catalog_empty"])


if __name__ == "__main__":
    unittest.main()
