"""Broadcast AI: default off, allowlist, redaction, no UI/RAG/LIVE leakage."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

import broadcast_ai

FAKE_LIVE = [
    {"id": "AgADnews01", "emoji": "📝", "file_id": "fid-news"},
    {"id": "AgADpromo01", "emoji": "✨", "file_id": "fid-promo"},
]


def _live_catalog():
    return patch("broadcast_stickers.list_live_catalog", AsyncMock(return_value=FAKE_LIVE))


class BroadcastAiGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_explicit_opt_in(self):
        with self.assertRaises(HTTPException) as ctx:
            await broadcast_ai.improve_draft(
                text="Привет клиентам",
                ai_enabled=False,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_disabled_by_default(self):
        with patch.object(broadcast_ai.settings, "broadcast_ai_enabled", False):
            with self.assertRaises(HTTPException) as ctx:
                await broadcast_ai.improve_draft(
                    text="Привет клиентам",
                    ai_enabled=True,
                )
        self.assertEqual(ctx.exception.status_code, 503)

    async def test_unknown_profile_rejected(self):
        with patch.object(broadcast_ai.settings, "broadcast_ai_enabled", True):
            with self.assertRaises(HTTPException) as ctx:
                await broadcast_ai.improve_draft(
                    text="Привет",
                    ai_enabled=True,
                    ai_provider_profile="openai-secret",
                )
        self.assertEqual(ctx.exception.status_code, 400)


class BroadcastAiRedactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_redacts_and_does_not_send_ui_or_rates(self):
        captured = {}

        async def fake_complete(messages, temperature=0.2, model_override=None):
            captured["messages"] = messages
            return '{"improved_text": "Готово", "suggested_sticker_ids": ["AgADnews01"]}'

        with patch.object(broadcast_ai.settings, "broadcast_ai_enabled", True), patch.object(
            broadcast_ai.settings, "ops_ai_provider", "offline"
        ), patch.object(
            broadcast_ai.settings, "broadcast_ai_provider_allowlist", "openai,openrouter,offline"
        ), patch(
            "ops_ai_llm.complete", fake_complete
        ), patch(
            "ops_ai_llm.provider_configured", lambda: True
        ), _live_catalog():
            result = await broadcast_ai.improve_draft(
                text="Напиши a@b.co api_key=sk-live-SECRETTOKEN123",
                ai_enabled=True,
                ai_provider_profile="default",
            )
        self.assertIsNone(result["error"])
        self.assertEqual(result["improved_text"], "Готово")
        self.assertEqual(result["suggested_sticker_ids"], ["AgADnews01"])
        blob = " ".join(str(m.get("content") or "") for m in captured["messages"])
        user_blob = " ".join(
            str(m.get("content") or "") for m in captured["messages"] if m.get("role") == "user"
        )
        self.assertNotIn("sk-live-SECRETTOKEN123", blob)
        self.assertNotIn("a@b.co", blob)
        self.assertIn("[REDACTED]", user_blob)
        self.assertNotIn("Rapira", blob)
        self.assertNotIn("помощник операторов", blob)
        self.assertFalse(any("LIVE RATES / SETTINGS" in str(m.get("content") or "") for m in captured["messages"]))
        system_blob = " ".join(
            str(m.get("content") or "") for m in captured["messages"] if m.get("role") == "system"
        )
        self.assertIn("жирный заголовок", system_blob)
        self.assertIn("CTA", system_blob)
        self.assertIn("премиум-пака FocusPay", system_blob)
        self.assertIn("✅", system_blob)
        self.assertIn("🚀", system_blob)
        self.assertIn("РОВНО 1", system_blob)
        self.assertIn("📝", system_blob)
        self.assertNotIn("без эмодзи-спама", system_blob)
        self.assertNotIn("помощник операторов", system_blob)

    async def test_uses_lelouch_temperature_and_optional_model(self):
        captured = {}

        async def fake_complete(messages, temperature=0.2, model_override=None):
            captured["temperature"] = temperature
            captured["model_override"] = model_override
            return '{"improved_text": "Ок", "suggested_sticker_ids": ["AgADnews01"]}'

        with patch.object(broadcast_ai.settings, "broadcast_ai_enabled", True), patch.object(
            broadcast_ai.settings, "ops_ai_provider", "offline"
        ), patch.object(
            broadcast_ai.settings, "broadcast_ai_model", "claude-fable-5"
        ), patch(
            "ops_ai_llm.complete", fake_complete
        ), patch(
            "ops_ai_llm.provider_configured", lambda: True
        ), _live_catalog():
            result = await broadcast_ai.improve_draft(text="Новости сервиса", ai_enabled=True)
        self.assertIsNone(result["error"])
        self.assertEqual(captured["temperature"], 0.7)
        self.assertEqual(captured["model_override"], "claude-fable-5")

    async def test_provider_error_keeps_original(self):
        async def boom(*_a, **_k):
            raise RuntimeError("provider down")

        with patch.object(broadcast_ai.settings, "broadcast_ai_enabled", True), patch.object(
            broadcast_ai.settings, "ops_ai_provider", "offline"
        ), patch(
            "ops_ai_llm.complete", boom
        ), patch(
            "ops_ai_llm.provider_configured", lambda: True
        ), _live_catalog():
            result = await broadcast_ai.improve_draft(
                text="Исходный текст",
                ai_enabled=True,
            )
        self.assertEqual(result["original_text"], "Исходный текст")
        self.assertIsNone(result["improved_text"])
        self.assertTrue(result["error"])

    async def test_filters_unknown_suggested_ids(self):
        async def fake_complete(messages, temperature=0.2, model_override=None):
            return '{"improved_text": "Ок", "suggested_sticker_ids": ["AgADnews01", "CAACAgIA"]}'

        with patch.object(broadcast_ai.settings, "broadcast_ai_enabled", True), patch.object(
            broadcast_ai.settings, "ops_ai_provider", "offline"
        ), patch(
            "ops_ai_llm.complete", fake_complete
        ), patch(
            "ops_ai_llm.provider_configured", lambda: True
        ), _live_catalog():
            result = await broadcast_ai.improve_draft(text="Новости", ai_enabled=True)
        self.assertEqual(result["suggested_sticker_ids"], ["AgADnews01"])

    async def test_caps_suggested_stickers_to_one(self):
        async def fake_complete(messages, temperature=0.2, model_override=None):
            return '{"improved_text": "Ок", "suggested_sticker_ids": ["AgADnews01", "AgADpromo01"]}'

        with patch.object(broadcast_ai.settings, "broadcast_ai_enabled", True), patch.object(
            broadcast_ai.settings, "ops_ai_provider", "offline"
        ), patch(
            "ops_ai_llm.complete", fake_complete
        ), patch(
            "ops_ai_llm.provider_configured", lambda: True
        ), _live_catalog():
            result = await broadcast_ai.improve_draft(text="Новости", ai_enabled=True)
        self.assertEqual(result["suggested_sticker_ids"], ["AgADnews01"])

    async def test_fills_sticker_when_model_omits_it(self):
        async def fake_complete(messages, temperature=0.2, model_override=None):
            return '{"improved_text": "Розыгрыш скидки", "suggested_sticker_ids": []}'

        with patch.object(broadcast_ai.settings, "broadcast_ai_enabled", True), patch.object(
            broadcast_ai.settings, "ops_ai_provider", "offline"
        ), patch(
            "ops_ai_llm.complete", fake_complete
        ), patch(
            "ops_ai_llm.provider_configured", lambda: True
        ), _live_catalog():
            result = await broadcast_ai.improve_draft(text="Розыгрыш", ai_enabled=True)
        self.assertIsNone(result["error"])
        self.assertEqual(result["suggested_sticker_ids"], ["AgADpromo01"])
        self.assertNotIn("tg-emoji", result["improved_text"] or "")

    async def test_upgrades_pack_emoji_in_draft(self):
        async def fake_complete(messages, temperature=0.2, model_override=None):
            return '{"improved_text": "<b>Сервис</b> ✅", "suggested_sticker_ids": ["AgADnews01"]}'

        with patch.object(broadcast_ai.settings, "broadcast_ai_enabled", True), patch.object(
            broadcast_ai.settings, "ops_ai_provider", "offline"
        ), patch(
            "ops_ai_llm.complete", fake_complete
        ), patch(
            "ops_ai_llm.provider_configured", lambda: True
        ), _live_catalog():
            result = await broadcast_ai.improve_draft(text="Запустили сервис", ai_enabled=True)
        self.assertIn("5206607081334906820", result["improved_text"] or "")
        self.assertNotIn("🚀", result["improved_text"] or "")


if __name__ == "__main__":
    unittest.main()
