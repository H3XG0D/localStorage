"""Isolated AI draft for admin/operator broadcast. Never sends UI/RAG/LIVE RATES/secrets."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from fastapi import HTTPException

from config import settings
from privacy_redaction import content_hash, redact_text

logger = logging.getLogger("broadcast_ai")

ALLOWED_PROFILES = frozenset({"default"})
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
BROADCAST_AI_TEMPERATURE = 0.7
MAX_SUGGESTED_STICKERS = 1

SYSTEM_PROMPT = """Ты пишешь короткие клиентские рассылки FocusPay в Telegram. Говори как живой человек: тепло, коротко, без канцелярита.

Верни СТРОГО JSON-объект без markdown fences:
{{"improved_text": "", "suggested_sticker_ids": []}}

Правила improved_text:
- Тот же смысл и факты, ничего не выдумывай.
- Формат: жирный заголовок (<b>…</b>), 1–2 коротких абзаца, при пользе — строки с • , в конце явный CTA.
- Смайлы — только из премиум-пака FocusPay. Бот отправит их как премиум-эмодзи. Разрешены только эти символы: {premium_chars}
- Поставь 4–8 таких эмодзи: в заголовок, буллеты и CTA. Не используй чужие смайлы вроде 🚀⚠️🎁🎉🔒. Не пиши <tg-emoji> и токены {{{{gift}}}}.
- Только Telegram HTML: b i a code u s br. Без markdown.
- Без ссылок на админку, /x8, /ops, внутренние URL.
- Не запрашивай и не повторяй секреты, токены, cookies, курсы, UI-контекст, RAG.
- Не предлагай автодеплой, LIVE RATES или изменения /exchange.

suggested_sticker_ids: РОВНО 1 id из каталога ниже. Возьми стикер с тем же emoji, что в заголовке. Пустой список нельзя.

Каталог стикеров (id emoji): {catalog}
"""


def _max_chars() -> int:
    return max(1, min(int(settings.broadcast_ai_max_chars or 4096), 4096))


def _timeout_sec() -> float:
    return max(1.0, min(float(settings.broadcast_ai_timeout_sec or 20), 60.0))


def _current_provider() -> str:
    return (settings.ops_ai_provider or "openai").strip().lower()


def _current_model() -> str:
    provider = _current_provider()
    if provider == "openrouter":
        return (settings.ops_ai_openrouter_model or settings.ops_ai_openai_model or "").strip()
    if provider == "anthropic":
        return (settings.ops_ai_anthropic_model or "").strip()
    if provider == "offline":
        return "offline"
    return (settings.ops_ai_openai_model or "").strip()


def _broadcast_model() -> str:
    override = (getattr(settings, "broadcast_ai_model", None) or "").strip()
    return override or _current_model()


def _model_override() -> str | None:
    override = (getattr(settings, "broadcast_ai_model", None) or "").strip()
    return override or None


def _provider_allowed() -> bool:
    allow = set(settings.broadcast_ai_provider_names())
    if not allow:
        return False
    return _current_provider() in allow


def _model_allowed() -> bool:
    allow = settings.broadcast_ai_model_names()
    if not allow:
        return True
    model = _broadcast_model()
    return bool(model) and model in allow


def _empty_result(original: str, error: str) -> dict[str, Any]:
    return {
        "original_text": original,
        "improved_text": None,
        "suggested_sticker_ids": [],
        "error": error,
        "provider_profile": "default",
    }


def _parse_model_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = _JSON_FENCE_RE.sub("", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


async def improve_draft(
    *,
    text: str,
    ai_enabled: bool,
    ai_provider_profile: str = "default",
) -> dict[str, Any]:
    original = (text or "").strip()
    if not original:
        raise HTTPException(status_code=400, detail="Введите текст")
    if len(original) > _max_chars():
        raise HTTPException(status_code=400, detail=f"Максимум {_max_chars()} символов")
    if not ai_enabled:
        raise HTTPException(status_code=400, detail="Включите AI явно")

    profile = (ai_provider_profile or "default").strip().lower() or "default"
    if profile not in ALLOWED_PROFILES:
        raise HTTPException(status_code=400, detail="Неизвестный AI-профиль")

    if not settings.broadcast_ai_enabled:
        raise HTTPException(status_code=503, detail="AI рассылки выключен")
    if not _provider_allowed() or not _model_allowed():
        logger.info("broadcast_ai denied: provider/model not on allowlist hash=%s", content_hash(original))
        raise HTTPException(status_code=503, detail="AI рассылки недоступен")

    from broadcast_emoji import apply_premium_emoji, fit_premium_text, premium_chars
    from broadcast_stickers import catalog_ids_from, list_live_catalog, pick_fallback_sticker_id, validate_sticker_ids
    from ops_ai_llm import complete, provider_configured

    if not provider_configured() and _current_provider() != "offline":
        raise HTTPException(status_code=503, detail="AI рассылки недоступен")

    redacted = redact_text(original, keep_short_ids=True)[: _max_chars()]
    live = await list_live_catalog()
    known = catalog_ids_from(live)
    catalog = "; ".join(
        f"{item['id']} {item.get('emoji') or ''}".strip() for item in live
    )
    system = SYSTEM_PROMPT.format(catalog=catalog, premium_chars=premium_chars() or "⭐ ✅")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": redacted},
    ]
    logger.info("broadcast_ai request hash=%s chars=%s", content_hash(redacted), len(redacted))

    try:
        raw = await asyncio.wait_for(
            complete(
                messages,
                temperature=BROADCAST_AI_TEMPERATURE,
                model_override=_model_override(),
            ),
            timeout=_timeout_sec(),
        )
    except asyncio.TimeoutError:
        logger.info("broadcast_ai timeout hash=%s", content_hash(redacted))
        return _empty_result(original, "AI не ответил вовремя")
    except Exception:
        logger.warning("broadcast_ai provider error hash=%s", content_hash(redacted))
        return _empty_result(original, "Не удалось улучшить текст")

    try:
        data = _parse_model_json(raw)
    except Exception:
        logger.info("broadcast_ai bad json hash=%s", content_hash(redacted))
        return _empty_result(original, "Не удалось улучшить текст")

    improved_raw = data.get("improved_text")
    improved = redact_text(str(improved_raw or ""), keep_short_ids=True).strip()
    improved = fit_premium_text(apply_premium_emoji(improved), _max_chars())
    if not improved:
        return _empty_result(original, "Не удалось улучшить текст")

    suggested_raw = data.get("suggested_sticker_ids") or []
    if not isinstance(suggested_raw, list):
        suggested_raw = []
    try:
        suggested = validate_sticker_ids(
            [str(x) for x in suggested_raw if x],
            max_count=MAX_SUGGESTED_STICKERS,
            catalog_ids=known,
        )
    except HTTPException:
        suggested = [
            sid for sid in (str(x).strip() for x in suggested_raw) if sid in known
        ][:MAX_SUGGESTED_STICKERS]
    if not suggested:
        picked = pick_fallback_sticker_id(improved, live)
        if picked:
            suggested = [picked]

    logger.info(
        "broadcast_ai ok hash=%s suggested=%s",
        content_hash(improved),
        len(suggested),
    )
    return {
        "original_text": original,
        "improved_text": improved,
        "suggested_sticker_ids": suggested,
        "error": None,
        "provider_profile": profile,
    }
