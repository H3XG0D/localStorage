"""Tests for operator chat sticker sets and send validation."""
import unittest
from unittest.mock import AsyncMock, patch

from chat_stickers import fetch_operator_sticker_sets, sticker_file_id_allowed


class StickerSetConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_config_returns_no_sets(self):
        with patch(
            "chat_stickers.settings.operator_sticker_set_names",
            [],
        ), patch(
            "chat_stickers._operator_set_names",
            AsyncMock(return_value=[]),
        ):
            sets = await fetch_operator_sticker_sets(operator_id=1, force=True)
        self.assertEqual(sets, [])

    async def test_allowed_file_id_from_cached_sets(self):
        fake_sets = [
            {
                "name": "TestSet",
                "title": "Test",
                "stickers": [{"file_id": "AAA", "emoji": "👍"}],
            }
        ]
        with patch(
            "chat_stickers.fetch_operator_sticker_sets",
            AsyncMock(return_value=fake_sets),
        ):
            ok = await sticker_file_id_allowed("AAA", operator_id=5)
            bad = await sticker_file_id_allowed("ZZZ", operator_id=5)
        self.assertTrue(ok)
        self.assertFalse(bad)

    async def test_merge_global_and_personal_names(self):
        with patch(
            "chat_stickers.settings.operator_sticker_set_names",
            ["GlobalSet"],
        ), patch(
            "chat_stickers._operator_set_names",
            AsyncMock(return_value=["GlobalSet", "PersonalSet"]),
        ), patch(
            "chat_stickers._get_sticker_set",
            AsyncMock(
                side_effect=lambda name: {
                    "name": name,
                    "title": name,
                    "stickers": [{"file_id": f"id-{name}", "emoji": "👍"}],
                }
            ),
        ):
            sets = await fetch_operator_sticker_sets(operator_id=7, force=True)
        names = {s["name"] for s in sets}
        self.assertEqual(names, {"GlobalSet", "PersonalSet"})


class AdminSendStickerValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_unknown_file_id(self):
        from chat_service import admin_send_sticker

        with patch(
            "chat_stickers.sticker_file_id_allowed",
            AsyncMock(return_value=False),
        ):
            from fastapi import HTTPException

            with self.assertRaises(HTTPException) as ctx:
                await admin_send_sticker(1, "unknown-id", admin_user_id=1)
            self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
