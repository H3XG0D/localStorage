"""Память проекта Ops AI: факты по людям/времени + привязка Telegram + дайджест."""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from db import get_pool

logger = logging.getLogger("ops_ai_memory")

MSK = ZoneInfo("Europe/Moscow")
REMEMBER_RE = re.compile(
    r"^\s*(запомни|remember)\s*[:\-]?\s*(.+)$",
    re.I | re.S,
)


def person_key_for_operator(operator_id: int) -> str:
    return f"op:{int(operator_id)}"


def _row(r) -> dict:
    d = dict(r)
    for k, v in list(d.items()):
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


async def add_memory(
    *,
    kind: str,
    title: str,
    body: str,
    person_key: str | None = None,
    person_label: str | None = None,
    source: str = "manual",
    source_ref: str | None = None,
    created_by_operator_id: int | None = None,
    importance: int = 1,
    occurred_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> dict:
    kind = (kind or "project").strip().lower()
    if kind not in ("person", "project", "shift", "incident", "decision"):
        kind = "project"
    title = (title or "").strip()[:200] or "Память"
    body = (body or "").strip()[:4000]
    if not body:
        raise ValueError("Пустая память")
    importance = max(1, min(5, int(importance or 1)))
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ops_ai_memories (
                kind, person_key, person_label, title, body,
                occurred_at, source, source_ref, created_by_operator_id,
                importance, expires_at
            ) VALUES (
                $1, $2, $3, $4, $5,
                COALESCE($6, NOW()), $7, $8, $9,
                $10, $11
            )
            RETURNING *
            """,
            kind,
            (person_key or None),
            (person_label or None),
            title,
            body,
            occurred_at,
            source,
            source_ref,
            created_by_operator_id,
            importance,
            expires_at,
        )
    return _row(row)


async def list_memories(
    *,
    person_key: str | None = None,
    kind: str | None = None,
    limit: int = 40,
    since_days: int | None = 90,
) -> list[dict]:
    clauses = ["(expires_at IS NULL OR expires_at > NOW())"]
    args: list[Any] = []
    if person_key:
        args.append(person_key)
        clauses.append(f"person_key = ${len(args)}")
    if kind:
        args.append(kind)
        clauses.append(f"kind = ${len(args)}")
    if since_days and since_days > 0:
        args.append(int(since_days))
        clauses.append(f"occurred_at >= NOW() - (${len(args)}::text || ' days')::interval")
    args.append(max(1, min(200, int(limit))))
    where = " AND ".join(clauses)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT * FROM ops_ai_memories WHERE {where} ORDER BY importance DESC, occurred_at DESC LIMIT ${len(args)}""",  # nosec B608
        )
    return [_row(r) for r in rows]


async def format_memory_block(
    *,
    query: str,
    operator_id: int | None = None,
    limit: int = 12,
) -> str:
    """Срез памяти для LLM: свои person + project/decision + упоминания."""
    items: list[dict] = []
    seen: set[int] = set()

    async def _take(rows: list[dict]) -> None:
        for r in rows:
            rid = int(r["id"])
            if rid in seen:
                continue
            seen.add(rid)
            items.append(r)

    if operator_id:
        await _take(
            await list_memories(
                person_key=person_key_for_operator(operator_id),
                limit=limit,
                since_days=120,
            )
        )
    await _take(await list_memories(kind="project", limit=6, since_days=60))
    await _take(await list_memories(kind="decision", limit=6, since_days=90))
    await _take(await list_memories(kind="incident", limit=4, since_days=30))

    q = (query or "").lower()
    # лёгкий keyword boost: если в запросе есть кусок body — подтянем ещё
    if len(q) >= 4:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM ops_ai_memories
                WHERE (expires_at IS NULL OR expires_at > NOW())
                  AND (
                    lower(title) LIKE $1 OR lower(body) LIKE $1
                    OR lower(COALESCE(person_label,'')) LIKE $1
                  )
                ORDER BY importance DESC, occurred_at DESC
                LIMIT 8
                """,
                f"%{q[:80]}%",
            )
        await _take([_row(r) for r in rows])

    if not items:
        return ""
    lines = ["# PROJECT MEMORY (по людям / времени)"]
    for m in items[:limit]:
        when = (m.get("occurred_at") or "")[:16].replace("T", " ")
        who = m.get("person_label") or m.get("person_key") or "project"
        lines.append(
            f"- [{when}] ({m.get('kind')}) {who}: {m.get('title')} — {(m.get('body') or '')[:280]}"
        )
    return "\n".join(lines)


async def maybe_remember_from_chat(
    *,
    operator_id: int,
    text: str,
    operator_label: str | None = None,
) -> dict | None:
    """Если оператор пишет «запомни: …» — кладём в память."""
    m = REMEMBER_RE.match(text or "")
    if not m:
        return None
    body = (m.group(2) or "").strip()
    if len(body) < 3:
        return None
    label = operator_label or f"op#{operator_id}"
    return await add_memory(
        kind="person",
        title=body[:80],
        body=body,
        person_key=person_key_for_operator(operator_id),
        person_label=label,
        source="chat",
        created_by_operator_id=operator_id,
        importance=2,
    )


async def remember_task_done(task: dict, *, note: str | None = None) -> dict | None:
    try:
        tid = int(task.get("id") or 0)
        op_id = int(task.get("operator_id") or 0) or None
        title = f"Done #{tid}: {task.get('title') or 'task'}"
        body = (note or task.get("summary") or task.get("request_text") or "")[:3500]
        return await add_memory(
            kind="decision",
            title=title[:200],
            body=body or title,
            person_key=person_key_for_operator(op_id) if op_id else None,
            person_label=f"op#{op_id}" if op_id else None,
            source="task",
            source_ref=f"task:{tid}",
            created_by_operator_id=op_id,
            importance=3,
        )
    except Exception as e:
        logger.warning("remember_task_done: %s", e)
        return None


# --- Telegram bind ---

async def create_bind_link(operator_id: int) -> dict:
    token = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:24].upper()
    expires = datetime.now(timezone.utc) + timedelta(hours=2)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE operator_accounts SET
                telegram_bind_token = $2,
                telegram_bind_expires_at = $3
            WHERE id = $1
            RETURNING id, username, display_name, telegram_user_id,
                      ops_ai_digest_enabled, ops_ai_digest_hour,
                      telegram_bind_expires_at
            """,
            operator_id,
            token,
            expires,
        )
        if not row:
            raise LookupError("Оператор не найден")
    from config import settings

    bot = (settings.telegram_bot_username or "").lstrip("@")
    deep = f"https://t.me/{bot}?start=opsbind_{token}" if bot else f"/start opsbind_{token}"
    return {
        "token": token,
        "deep_link": deep,
        "expires_at": expires.isoformat(),
        "telegram_user_id": row["telegram_user_id"],
        "digest_enabled": bool(row["ops_ai_digest_enabled"]),
        "digest_hour": int(row["ops_ai_digest_hour"] or 10),
        "command": f"/ops_bind {token}",
    }


async def bind_operator_telegram(token: str, telegram_user_id: int) -> dict | None:
    code = (token or "").strip().upper()
    if code.lower().startswith("opsbind_"):
        code = code.split("_", 1)[1].upper()
    if not code or len(code) < 8:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, username, display_name, telegram_user_id, telegram_bind_expires_at
            FROM operator_accounts
            WHERE telegram_bind_token = $1
              AND is_active = TRUE
              AND (telegram_bind_expires_at IS NULL OR telegram_bind_expires_at > NOW())
            """,
            code,
        )
        if not row:
            return None
        if row["telegram_user_id"] and int(row["telegram_user_id"]) != int(telegram_user_id):
            return None
        # один TG — один оператор
        await conn.execute(
            """
            UPDATE operator_accounts
            SET telegram_user_id = NULL
            WHERE telegram_user_id = $1 AND id <> $2
            """,
            telegram_user_id,
            row["id"],
        )
        updated = await conn.fetchrow(
            """
            UPDATE operator_accounts SET
                telegram_user_id = $1,
                telegram_bind_token = NULL,
                telegram_bind_expires_at = NULL
            WHERE id = $2
            RETURNING id, username, display_name, telegram_user_id,
                      ops_ai_digest_enabled, ops_ai_digest_hour
            """,
            telegram_user_id,
            row["id"],
        )
    return _row(updated) if updated else None


async def unbind_operator_telegram(operator_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE operator_accounts SET
                telegram_user_id = NULL,
                telegram_bind_token = NULL,
                telegram_bind_expires_at = NULL
            WHERE id = $1
            """,
            operator_id,
        )


async def get_bind_status(operator_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, username, display_name, telegram_user_id,
                   ops_ai_digest_enabled, ops_ai_digest_hour
            FROM operator_accounts WHERE id = $1
            """,
            operator_id,
        )
    if not row:
        raise LookupError("Оператор не найден")
    return {
        "operator_id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "telegram_user_id": row["telegram_user_id"],
        "telegram_linked": row["telegram_user_id"] is not None,
        "digest_enabled": bool(row["ops_ai_digest_enabled"]),
        "digest_hour": int(row["ops_ai_digest_hour"] or 10),
        "digest_tz": "Europe/Moscow",
    }


async def update_digest_settings(
    operator_id: int,
    *,
    enabled: bool | None = None,
    hour: int | None = None,
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        cur = await conn.fetchrow(
            "SELECT ops_ai_digest_enabled, ops_ai_digest_hour FROM operator_accounts WHERE id = $1",
            operator_id,
        )
        if not cur:
            raise LookupError("Оператор не найден")
        new_en = cur["ops_ai_digest_enabled"] if enabled is None else bool(enabled)
        new_h = int(cur["ops_ai_digest_hour"] or 10) if hour is None else int(hour)
        if not (0 <= new_h <= 23):
            raise ValueError("Час дайджеста 0–23 (МСК)")
        await conn.execute(
            """
            UPDATE operator_accounts SET
                ops_ai_digest_enabled = $2,
                ops_ai_digest_hour = $3
            WHERE id = $1
            """,
            operator_id,
            new_en,
            new_h,
        )
    return await get_bind_status(operator_id)


async def _already_sent_today(conn, operator_id: int, day_key: str) -> bool:
    row = await conn.fetchrow(
        """
        SELECT 1 FROM ops_ai_digest_log
        WHERE operator_id = $1
          AND kind = 'daily'
          AND payload_preview = $2
        LIMIT 1
        """,
        operator_id,
        day_key,
    )
    return bool(row)


async def build_digest_text(operator_id: int) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        op = await conn.fetchrow(
            "SELECT username, display_name FROM operator_accounts WHERE id = $1",
            operator_id,
        )
        review = await conn.fetchval(
            "SELECT COUNT(*) FROM ops_ai_dev_tasks WHERE status = 'review'"
        )
        my_open = await conn.fetchval(
            """
            SELECT COUNT(*) FROM ops_ai_dev_tasks
            WHERE operator_id = $1 AND status IN ('new','drafting','review','approved')
            """,
            operator_id,
        )
    mems = await list_memories(
        person_key=person_key_for_operator(operator_id),
        limit=5,
        since_days=2,
    )
    project = await list_memories(kind="project", limit=3, since_days=2)
    name = (op and (op["display_name"] or op["username"])) or f"#{operator_id}"
    lines = [
        f"🧠 Ops AI дайджест — {name}",
        f"В review (общие): {int(review or 0)} · ваши открытые: {int(my_open or 0)}",
        "Админка: https://focuspay.org/x8/ai-tasks",
    ]
    if mems or project:
        lines.append("\nПамять за ~2 дня:")
        for m in (mems + project)[:8]:
            when = (m.get("occurred_at") or "")[:10]
            lines.append(f"• [{when}] {m.get('title')}")
    else:
        lines.append("\nНовых записей памяти почти нет.")
    lines.append("\n«запомни: …» в FAB — попадёт в память. Отключить: профиль /ops/profile")
    return "\n".join(lines)


async def run_due_digests(now: datetime | None = None) -> int:
    """Claim and deliver due operator digests across any number of workers."""
    current = now.astimezone(MSK) if now is not None else datetime.now(MSK)
    hour = current.hour
    delivery_date = current.date()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, telegram_user_id, username
            FROM operator_accounts
            WHERE is_active = TRUE
              AND ops_ai_digest_enabled = TRUE
              AND telegram_user_id IS NOT NULL
              AND ops_ai_digest_hour = $1
            """,
            hour,
        )
    if not rows:
        return 0

    from digest_delivery import (
        claim_digest_delivery,
        complete_digest_delivery,
        release_digest_delivery,
    )
    from telegram_notify import send_admin_message

    sent = 0
    for r in rows:
        op_id = int(r["id"])
        tg = int(r["telegram_user_id"])
        claim_token = await claim_digest_delivery(
            digest_kind="operator",
            recipient_key=str(op_id),
            delivery_date=delivery_date,
        )
        if claim_token is None:
            continue
        try:
            text = await build_digest_text(op_id)
            message_id = await send_admin_message(text, chat_id=tg)
            if message_id is None:
                logger.warning("digest send op=%s: Telegram returned no message id", op_id)
                await release_digest_delivery(claim_token)
                continue
            if not await complete_digest_delivery(claim_token):
                logger.error("digest completion lost claim op=%s", op_id)
                continue
            sent += 1
        except Exception as e:
            logger.warning("digest send op=%s: %s", op_id, e)
            await release_digest_delivery(claim_token)
    return sent
