"""Защищённое хранилище аудита Ops AI (redacted-only, TTL, access log)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException

from config import settings
from db import get_pool
from privacy_redaction import AUDIT_META_ALLOW, content_hash, redact_mapping, redact_text

logger = logging.getLogger("ops_ai_audit")
_security = logging.getLogger("security.ops_ai_audit")


def _ttl_days() -> int:
    try:
        d = int(getattr(settings, "ops_ai_audit_ttl_days", 30) or 30)
    except (TypeError, ValueError):
        d = 30
    return max(1, min(d, 365))


def _expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=_ttl_days())


async def record_event(
    *,
    correlation_id: str,
    actor_type: str,
    actor_id: int,
    tenant_scope: str,
    event_type: str,
    consent_version: str | None,
    request_hash: str,
    response_hash: str | None = None,
    redacted_request: dict | None = None,
    redacted_response: dict | None = None,
    meta: dict | None = None,
) -> Optional[int]:
    """Пишет только redacted payload. Без согласия — только technical event."""
    safe_req = redact_mapping(redacted_request or {}, allow=frozenset(redacted_request or {}))
    # Ограничиваем размер: только короткие redacted поля
    for k in list(safe_req.keys()):
        v = safe_req[k]
        if isinstance(v, str) and len(v) > 2000:
            safe_req[k] = v[:2000]
    safe_resp = {}
    if redacted_response:
        for k, v in redacted_response.items():
            if isinstance(v, str):
                safe_resp[str(k)] = redact_text(v, keep_short_ids=True)[:2000]
            elif isinstance(v, (int, float, bool)) or v is None:
                safe_resp[str(k)] = v
    safe_meta = redact_mapping(meta, allow=AUDIT_META_ALLOW)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ops_ai_audit_events (
                correlation_id, actor_type, actor_id, tenant_scope, event_type,
                consent_version, request_hash, response_hash,
                redacted_request, redacted_response, meta, expires_at
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8,
                $9::jsonb, $10::jsonb, $11::jsonb, $12
            )
            RETURNING id
            """,
            correlation_id[:64],
            actor_type[:32],
            int(actor_id),
            (tenant_scope or "global")[:64],
            event_type[:64],
            (consent_version or "")[:64] or None,
            request_hash[:128],
            (response_hash or "")[:128] or None,
            json.dumps(safe_req, ensure_ascii=False),
            json.dumps(safe_resp, ensure_ascii=False),
            json.dumps(safe_meta, ensure_ascii=False),
            _expires_at(),
        )
    eid = int(row["id"]) if row else None
    _security.info(
        "ops_ai_audit_write id=%s corr=%s type=%s actor=%s:%s",
        eid,
        correlation_id,
        event_type,
        actor_type,
        actor_id,
    )
    return eid


async def purge_expired() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM ops_ai_audit_events WHERE expires_at < now()"
        )
    try:
        return int(str(result).split()[-1])
    except Exception:
        return 0


async def delete_for_subject(
    *,
    actor_type: str,
    actor_id: int,
    deleted_by_type: str,
    deleted_by_id: int,
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            result = await conn.execute(
                """
                DELETE FROM ops_ai_audit_events
                WHERE actor_type = $1 AND actor_id = $2
                """,
                actor_type,
                int(actor_id),
            )
            await conn.execute(
                """
                INSERT INTO ops_ai_audit_access_log (
                    audit_id, accessor_type, accessor_id, action, detail
                ) VALUES (NULL, $1, $2, 'delete_subject', $3::jsonb)
                """,
                deleted_by_type,
                int(deleted_by_id),
                json.dumps({"actor_type": actor_type, "actor_id": actor_id}),
            )
    try:
        n = int(str(result).split()[-1])
    except Exception:
        n = 0
    _security.info(
        "ops_ai_audit_delete_subject actor=%s:%s by=%s:%s n=%s",
        actor_type,
        actor_id,
        deleted_by_type,
        deleted_by_id,
        n,
    )
    return n


async def _log_access(
    *,
    audit_id: int | None,
    accessor_type: str,
    accessor_id: int,
    action: str,
    detail: dict | None = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ops_ai_audit_access_log (
                audit_id, accessor_type, accessor_id, action, detail
            ) VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            audit_id,
            accessor_type,
            int(accessor_id),
            action[:64],
            json.dumps(detail or {}, ensure_ascii=False),
        )
    _security.info(
        "ops_ai_audit_access action=%s audit_id=%s by=%s:%s",
        action,
        audit_id,
        accessor_type,
        accessor_id,
    )


async def get_event(
    event_id: int,
    *,
    principal: dict,
    tenant_scope: str | None = None,
) -> dict:
    from permissions import PERM_AI_AUDIT_VIEW, has_permission

    if not has_permission(principal, PERM_AI_AUDIT_VIEW):
        raise HTTPException(403, "Недостаточно прав: ai.audit.view")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM ops_ai_audit_events
            WHERE id = $1 AND expires_at > now()
            """,
            int(event_id),
        )
    if not row:
        raise HTTPException(404, "Запись аудита не найдена или истекла")

    d = dict(row)
    # Object/tenant scope: admin видит всё; иначе только свой tenant + свои записи
    is_admin = bool(principal.get("is_admin"))
    if not is_admin:
        op_id = int(principal.get("id") or 0)
        if d.get("actor_type") != "operator" or int(d.get("actor_id") or 0) != op_id:
            raise HTTPException(404, "Запись аудита не найдена или истекла")
        if tenant_scope and d.get("tenant_scope") not in (tenant_scope, "global"):
            raise HTTPException(404, "Запись аудита не найдена или истекла")

    await _log_access(
        audit_id=int(d["id"]),
        accessor_type="admin" if is_admin else "operator",
        accessor_id=int(principal.get("id") or 0),
        action="read",
    )
    # Не отдаём сырые секреты — уже redacted
    for ts in ("created_at", "expires_at"):
        if d.get(ts) is not None:
            d[ts] = d[ts].isoformat()
    return d


async def list_events(
    *,
    principal: dict,
    actor_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    from permissions import PERM_AI_AUDIT_VIEW, has_permission

    if not has_permission(principal, PERM_AI_AUDIT_VIEW):
        raise HTTPException(403, "Недостаточно прав: ai.audit.view")

    is_admin = bool(principal.get("is_admin"))
    op_id = int(principal.get("id") or 0)
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    pool = await get_pool()
    async with pool.acquire() as conn:
        if is_admin:
            rows = await conn.fetch(
                """
                SELECT id, correlation_id, actor_type, actor_id, tenant_scope,
                       event_type, consent_version, request_hash, response_hash,
                       meta, created_at, expires_at
                FROM ops_ai_audit_events
                WHERE expires_at > now()
                  AND ($1::bigint IS NULL OR actor_id = $1)
                ORDER BY id DESC
                LIMIT $2 OFFSET $3
                """,
                actor_id,
                limit,
                offset,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, correlation_id, actor_type, actor_id, tenant_scope,
                       event_type, consent_version, request_hash, response_hash,
                       meta, created_at, expires_at
                FROM ops_ai_audit_events
                WHERE expires_at > now()
                  AND actor_type = 'operator' AND actor_id = $1
                ORDER BY id DESC
                LIMIT $2 OFFSET $3
                """,
                op_id,
                limit,
                offset,
            )

    await _log_access(
        audit_id=None,
        accessor_type="admin" if is_admin else "operator",
        accessor_id=op_id,
        action="list",
        detail={"limit": limit, "offset": offset, "actor_id": actor_id},
    )
    out = []
    for r in rows:
        d = dict(r)
        for ts in ("created_at", "expires_at"):
            if d.get(ts) is not None:
                d[ts] = d[ts].isoformat()
        out.append(d)
    return out


def summarize_response_for_audit(visible: str, escalate: dict | None = None) -> dict[str, Any]:
    esc = escalate or {}
    return {
        "answer_preview": redact_text((visible or "")[:400], keep_short_ids=True),
        "answer_hash": content_hash(visible or ""),
        "escalate": bool(esc.get("escalate")),
        "escalate_title": redact_text(str(esc.get("title") or "")[:120], keep_short_ids=True),
    }
