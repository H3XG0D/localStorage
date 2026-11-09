"""Согласие, allowlist-контекст и политики Ops AI privacy."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from config import settings
from db import get_pool
from privacy_redaction import (
    UI_CONTEXT_ALLOW,
    content_hash,
    correlation_id,
    redact_mapping,
    redact_text,
)

logger = logging.getLogger("ops_ai_privacy")
# Отдельный канал: без сырых prompt/response
_security = logging.getLogger("security.ops_ai")


def current_consent_version() -> str:
    return (settings.ops_ai_consent_version or "ops-ai-privacy-v1").strip()


async def get_consent(*, subject_type: str, subject_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, subject_type, subject_id, consent_version, scopes,
                   source, granted_at, revoked_at
            FROM ops_ai_consent
            WHERE subject_type = $1 AND subject_id = $2
              AND revoked_at IS NULL
            ORDER BY granted_at DESC
            LIMIT 1
            """,
            subject_type,
            int(subject_id),
        )
    return dict(row) if row else None


async def has_valid_consent(
    *,
    subject_type: str,
    subject_id: int,
    need_scope: str | None = None,
) -> bool:
    row = await get_consent(subject_type=subject_type, subject_id=subject_id)
    if not row:
        return False
    if str(row.get("consent_version") or "") != current_consent_version():
        return False
    if need_scope:
        scopes = row.get("scopes") or []
        if isinstance(scopes, str):
            import json

            try:
                scopes = json.loads(scopes)
            except Exception:
                scopes = []
        if need_scope not in set(scopes):
            return False
    return True


async def record_consent(
    *,
    subject_type: str,
    subject_id: int,
    scopes: list[str],
    source: str,
    actor_id: int | None = None,
) -> dict:
    import json

    version = current_consent_version()
    clean_scopes = sorted({str(s).strip() for s in scopes if str(s).strip()})
    if "llm" not in clean_scopes:
        clean_scopes.append("llm")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE ops_ai_consent
                SET revoked_at = now()
                WHERE subject_type = $1 AND subject_id = $2 AND revoked_at IS NULL
                """,
                subject_type,
                int(subject_id),
            )
            row = await conn.fetchrow(
                """
                INSERT INTO ops_ai_consent (
                    subject_type, subject_id, consent_version, scopes, source, actor_id
                ) VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                RETURNING id, subject_type, subject_id, consent_version, scopes,
                          source, granted_at, revoked_at
                """,
                subject_type,
                int(subject_id),
                version,
                json.dumps(clean_scopes),
                (source or "api")[:120],
                actor_id,
            )
    _security.info(
        "ops_ai_consent_granted subject=%s:%s version=%s scopes=%s",
        subject_type,
        subject_id,
        version,
        clean_scopes,
    )
    return dict(row)


async def revoke_consent(*, subject_type: str, subject_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE ops_ai_consent
            SET revoked_at = now()
            WHERE subject_type = $1 AND subject_id = $2 AND revoked_at IS NULL
            """,
            subject_type,
            int(subject_id),
        )
    # asyncpg: "UPDATE N"
    try:
        n = int(str(result).split()[-1])
    except Exception:
        n = 0
    _security.info("ops_ai_consent_revoked subject=%s:%s n=%s", subject_type, subject_id, n)
    return n


async def require_llm_consent(operator_id: int) -> None:
    ok = await has_valid_consent(
        subject_type="operator", subject_id=operator_id, need_scope="llm"
    )
    if not ok:
        # Админский FAB использует отрицательный actor id (−admin_id)
        path = (
            "/api/admin/ai/consent"
            if int(operator_id) < 0
            else "/api/operator/ai/consent"
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "Нужно согласие на обработку данных Ops AI "
                f"(версия {current_consent_version()}). "
                f"Нажмите «Разрешить» в AI-помощнике или POST {path}"
            ),
        )


def sanitize_question(text: str) -> str:
    return redact_text((text or "")[:8000], keep_short_ids=True)


def sanitize_context_block(text: str) -> str:
    return redact_text((text or "")[:24000], keep_short_ids=True)


def sanitize_ui_context(ui: dict[str, Any] | None) -> dict[str, Any]:
    return redact_mapping(ui, allow=UI_CONTEXT_ALLOW)


def images_allowed_for_llm(*, consent_has_images: bool) -> bool:
    if not bool(getattr(settings, "ops_ai_allow_images", False)):
        return False
    return bool(consent_has_images)


async def prepare_llm_payload(
    *,
    operator_id: int,
    question: str,
    context: str,
    history: list[dict[str, str]],
    image_data_urls: list[str] | None,
    ui_context: dict | None = None,
) -> dict[str, Any]:
    """Готовит redacted payload + метаданные. Без согласия — исключение."""
    await require_llm_consent(operator_id)
    consent = await get_consent(subject_type="operator", subject_id=operator_id)
    raw_scopes = (consent or {}).get("scopes") or []
    if isinstance(raw_scopes, str):
        import json

        try:
            raw_scopes = json.loads(raw_scopes)
        except Exception:
            raw_scopes = []
    scopes = {str(s) for s in raw_scopes}

    q = sanitize_question(question)
    ctx = sanitize_context_block(context)
    hist: list[dict[str, str]] = []
    for h in history[-8:]:
        role = h.get("role")
        content = h.get("content")
        if role in ("user", "assistant") and content:
            hist.append({"role": role, "content": sanitize_question(str(content))[:4000]})

    allow_images = images_allowed_for_llm(consent_has_images="images" in scopes)
    images = []
    if allow_images and image_data_urls:
        # Не сохраняем и не аудитим байты — только счётчик; в LLM уходит максимум 1 кадр
        # и только если явно разрешено (по умолчанию False).
        images = list(image_data_urls)[:1]
    elif image_data_urls:
        _security.info(
            "ops_ai_images_blocked op=%s count=%s",
            operator_id,
            len(image_data_urls),
        )

    corr = correlation_id("op", operator_id, content_hash(q)[:16])
    return {
        "question": q,
        "context": ctx,
        "history": hist,
        "image_data_urls": images,
        "ui_safe": sanitize_ui_context(ui_context),
        "correlation_id": corr,
        "consent_version": current_consent_version(),
        "question_hash": content_hash(q),
        "context_hash": content_hash(ctx),
        "has_images": bool(images),
        "images_blocked": bool(image_data_urls) and not images,
    }
