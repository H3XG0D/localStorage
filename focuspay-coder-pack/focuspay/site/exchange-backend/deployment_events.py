"""Deployment events: idempotent ingest, operator confirmation, daily changelog."""
from __future__ import annotations

import hashlib
import hmac
import html
import logging
import re
from datetime import date, datetime, timezone
from typing import Any

import requests

from config import settings
from db import get_pool

logger = logging.getLogger("deployment_events")

_ALLOWED_STATUS = frozenset({"pending", "success", "failed", "unknown", "confirmed"})
_SECRET_RE = re.compile(
    r"(?i)((?:api[_-]?key|secret(?:_key)?|password|token|authorization)\s*[=:]\s*)([^\s,;]+)"
    r"|(bearer\s+[a-z0-9._\-]+)"
    r"|(sk-[a-z0-9]+)"
    r"|(-----begin[^-]+-----[\s\S]*?-----end[^-]+-----)"
)


def _scrub_plain(text: str | None, *, limit: int = 4000) -> str:
    """Store without HTML entities (UI escapes); still redact secrets."""
    s = (text or "").strip()
    if not s:
        return ""

    def _sub(m: re.Match) -> str:
        if m.group(1):
            return f"{m.group(1)}[REDACTED]"
        return "[REDACTED]"

    s = _SECRET_RE.sub(_sub, s)
    return s[:limit]


def _scrub(text: str | None, *, limit: int = 4000) -> str:
    return html.escape(_scrub_plain(text, limit=limit), quote=False)


def verify_deploy_signature(body: bytes, signature: str | None) -> bool:
    secret = (settings.deploy_webhook_secret or "").strip()
    if not secret:
        return False
    if not signature:
        return False
    sig = signature.strip()
    if sig.lower().startswith("sha256="):
        sig = sig.split("=", 1)[1].strip()
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _row_to_dict(row) -> dict[str, Any]:
    d = dict(row)
    for k in ("created_at", "updated_at", "confirmed_at", "notify_sent_at"):
        v = d.get(k)
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    sectors = d.get("sectors") or []
    if isinstance(sectors, str):
        sectors = [sectors]
    d["sectors"] = list(sectors)
    return d


async def _audit(
    conn,
    event_id: int,
    *,
    actor_type: str,
    actor_id: int | None,
    action: str,
    detail: dict | None = None,
) -> None:
    import json

    await conn.execute(
        """
        INSERT INTO deployment_event_audit (event_id, actor_type, actor_id, action, detail)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        """,
        event_id,
        actor_type,
        actor_id,
        action,
        json.dumps(detail or {}, ensure_ascii=False),
    )


async def upsert_deploy_event(payload: dict[str, Any]) -> dict[str, Any]:
    key = str(payload.get("idempotency_key") or "").strip()
    if not key or len(key) > 200:
        raise ValueError("idempotency_key required")
    status = str(payload.get("status") or "pending").strip().lower()
    if status not in _ALLOWED_STATUS or status == "confirmed":
        # webhook cannot set confirmed — only operator confirm can
        if status == "confirmed":
            status = "success"
        elif status not in _ALLOWED_STATUS:
            status = "unknown"

    env = str(payload.get("environment") or "production").strip()[:64] or "production"
    title = _scrub_plain(payload.get("title") or "Deployment", limit=200)
    sectors = payload.get("sectors") or []
    if isinstance(sectors, str):
        sectors = [s.strip() for s in sectors.split(",") if s.strip()]
    sectors = [str(s)[:64] for s in sectors][:20]
    technical = _scrub_plain(payload.get("technical_summary"), limit=4000)
    impact = _scrub_plain(payload.get("user_impact"), limit=2000)
    plain = _scrub_plain(payload.get("plain_explanation"), limit=2000)
    commit_sha = str(payload.get("commit_sha") or "")[:64] or None
    build_id = str(payload.get("build_id") or "")[:128] or None
    actor = str(payload.get("actor") or "")[:128] or None
    logs_url = str(payload.get("logs_url") or "")[:500] or None
    source = str(payload.get("source") or "webhook")[:64]
    task_id = payload.get("ops_ai_task_id")
    try:
        task_id_int = int(task_id) if task_id is not None else None
    except (TypeError, ValueError):
        task_id_int = None

    import json

    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM deployment_events WHERE idempotency_key = $1",
            key,
        )
        if existing:
            # Retry: update mutable status fields unless already operator-confirmed
            if existing["status"] == "confirmed":
                await _audit(
                    conn,
                    int(existing["id"]),
                    actor_type="webhook",
                    actor_id=None,
                    action="idempotent_hit_confirmed",
                    detail={"ignored_status": status},
                )
                return _row_to_dict(existing)
            row = await conn.fetchrow(
                """
                UPDATE deployment_events SET
                    status = $2,
                    title = COALESCE(NULLIF($3, ''), title),
                    sectors = CASE WHEN cardinality($4::text[]) > 0 THEN $4::text[] ELSE sectors END,
                    technical_summary = COALESCE(NULLIF($5, ''), technical_summary),
                    user_impact = COALESCE(NULLIF($6, ''), user_impact),
                    plain_explanation = COALESCE(NULLIF($7, ''), plain_explanation),
                    commit_sha = COALESCE($8, commit_sha),
                    build_id = COALESCE($9, build_id),
                    actor = COALESCE($10, actor),
                    logs_url = COALESCE($11, logs_url),
                    ops_ai_task_id = COALESCE($12, ops_ai_task_id),
                    extra = extra || $13::jsonb,
                    updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                existing["id"],
                status,
                title,
                sectors,
                technical,
                impact,
                plain,
                commit_sha,
                build_id,
                actor,
                logs_url,
                task_id_int,
                json.dumps(extra, ensure_ascii=False),
            )
            await _audit(
                conn,
                int(row["id"]),
                actor_type="webhook",
                actor_id=None,
                action="updated",
                detail={"status": status},
            )
            out = _row_to_dict(row)
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO deployment_events (
                    idempotency_key, environment, commit_sha, build_id, actor, status,
                    title, sectors, technical_summary, user_impact, plain_explanation,
                    logs_url, source, ops_ai_task_id, extra
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8::text[],$9,$10,$11,$12,$13,$14,$15::jsonb
                )
                RETURNING *
                """,
                key,
                env,
                commit_sha,
                build_id,
                actor,
                status,
                title,
                sectors,
                technical,
                impact,
                plain,
                logs_url,
                source,
                task_id_int,
                json.dumps(extra, ensure_ascii=False),
            )
            await _audit(
                conn,
                int(row["id"]),
                actor_type="webhook",
                actor_id=None,
                action="created",
                detail={"status": status},
            )
            out = _row_to_dict(row)

    if status in ("failed", "unknown") and not (out.get("extra") or {}).get("soft_notified"):
        try:
            if await _notify_status_soft(row):
                pool = await get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE deployment_events
                        SET extra = extra || '{"soft_notified": true}'::jsonb,
                            updated_at = NOW()
                        WHERE id = $1
                        """,
                        int(out["id"]),
                    )
        except Exception:
            logger.exception("soft deploy notify failed")
    return out


async def confirm_deploy_event(
    event_id: int,
    operator: dict,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM deployment_events WHERE id = $1", event_id)
        if not row:
            raise LookupError("not found")
        if row["environment"] != "production":
            raise ValueError("only production rollouts are confirmed here")
        if row["status"] not in ("success", "confirmed"):
            raise ValueError("can only confirm successful rollouts")
        if row["status"] == "confirmed" and row.get("notify_sent_at"):
            return _row_to_dict(row)

        updated = await conn.fetchrow(
            """
            UPDATE deployment_events SET
                status = 'confirmed',
                confirmed_at = COALESCE(confirmed_at, NOW()),
                confirmed_by_operator_id = COALESCE(confirmed_by_operator_id, $2),
                updated_at = NOW()
            WHERE id = $1
            RETURNING *
            """,
            event_id,
            int(operator["id"]),
        )
        await _audit(
            conn,
            event_id,
            actor_type="operator",
            actor_id=int(operator["id"]),
            action="confirmed",
            detail={"note": _scrub_plain(note, limit=500)},
        )

    notified = await notify_operators_deploy_confirmed(updated)
    if notified:
        pool = await get_pool()
        async with pool.acquire() as conn:
            updated = await conn.fetchrow(
                """
                UPDATE deployment_events
                SET notify_sent_at = COALESCE(notify_sent_at, NOW()), updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                event_id,
            )
    return _row_to_dict(updated)


async def notify_operators_deploy_confirmed(row) -> bool:
    """Notify linked operators only after confirmed success — never claim 'done' for failed."""
    if dict(row).get("notify_sent_at"):
        return False
    status = row["status"]
    if status not in ("confirmed", "success"):
        # failed/unknown: separate soft notice without "решено"
        return await _notify_status_soft(row)

    title = html.escape(str(row.get("title") or "Выкат")[:200])
    plain = html.escape(str(row.get("plain_explanation") or "")[:800])
    sectors = ", ".join(html.escape(str(s)) for s in (row.get("sectors") or [])[:12])
    sha = html.escape(str(row.get("commit_sha") or "")[:12])
    text = (
        f"<b>FocusPay · подтверждённый выкат</b>\n"
        f"#{int(row['id'])} {title}\n"
        f"Статус: подтверждено оператором\n"
    )
    if sectors:
        text += f"Сектора: {sectors}\n"
    if plain:
        text += f"\n{plain}\n"
    if sha:
        text += f"\n<code>{sha}</code>"

    return await _broadcast_operators_tg(text)


async def _notify_status_soft(row) -> bool:
    status = html.escape(str(row.get("status") or "unknown"))
    title = html.escape(str(row.get("title") or "Выкат")[:200])
    text = (
        f"<b>FocusPay · статус выката</b>\n"
        f"#{int(row['id'])} {title}\n"
        f"Статус: <code>{status}</code>\n"
        f"Это не подтверждение решения — проверьте вручную."
    )
    return await _broadcast_operators_tg(text)


async def _broadcast_operators_tg(text: str) -> bool:
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT telegram_user_id
            FROM operator_accounts
            WHERE is_active = TRUE AND telegram_user_id IS NOT NULL
            """
        )
    ok_any = False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for r in rows:
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": int(r["telegram_user_id"]),
                    "text": text[:3500],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            if resp.status_code < 400:
                ok_any = True
        except Exception as e:
            logger.warning("deploy notify failed: %s", e)
    return ok_any


async def list_changelog(
    *,
    day: date | None = None,
    environment: str = "production",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))
    pool = await get_pool()
    async with pool.acquire() as conn:
        if day is not None:
            rows = await conn.fetch(
                """
                SELECT * FROM deployment_events
                WHERE environment = $1
                  AND timezone('UTC', created_at)::date = $2::date
                ORDER BY created_at DESC
                LIMIT $3 OFFSET $4
                """,
                environment,
                day,
                limit,
                offset,
            )
            total = await conn.fetchval(
                """
                SELECT count(*) FROM deployment_events
                WHERE environment = $1
                  AND timezone('UTC', created_at)::date = $2::date
                """,
                environment,
                day,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM deployment_events
                WHERE environment = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                environment,
                limit,
                offset,
            )
            total = await conn.fetchval(
                "SELECT count(*) FROM deployment_events WHERE environment = $1",
                environment,
            )

        days = await conn.fetch(
            """
            SELECT timezone('UTC', created_at)::date AS day, count(*) AS n
            FROM deployment_events
            WHERE environment = $1
            GROUP BY 1
            ORDER BY 1 DESC
            LIMIT 60
            """,
            environment,
        )

    by_day: dict[str, list] = {}
    for r in rows:
        d = _row_to_dict(r)
        day_key = (r["created_at"].astimezone(timezone.utc).date().isoformat())
        by_day.setdefault(day_key, []).append(d)

    return {
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "days": [
            {"date": (d["day"].isoformat() if hasattr(d["day"], "isoformat") else str(d["day"])), "count": int(d["n"])}
            for d in days
        ],
        "items_by_day": by_day,
        "items": [_row_to_dict(r) for r in rows],
    }


async def get_event(event_id: int) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM deployment_events WHERE id = $1", event_id)
        if not row:
            return None
        audits = await conn.fetch(
            """
            SELECT id, actor_type, actor_id, action, detail, created_at
            FROM deployment_event_audit
            WHERE event_id = $1
            ORDER BY id DESC
            LIMIT 50
            """,
            event_id,
        )
    d = _row_to_dict(row)
    d["audit"] = []
    for a in audits:
        item = dict(a)
        if isinstance(item.get("created_at"), datetime):
            item["created_at"] = item["created_at"].isoformat()
        d["audit"].append(item)
    return d
