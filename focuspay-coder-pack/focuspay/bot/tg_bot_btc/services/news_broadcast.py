"""Адресная рассылка новостей: idempotency, rate limit, frequency cap, lock."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from services.db import get_pool
from services.news_privacy import pseudo_chat, pseudo_user, security_log
from services.news_subscriptions import ALLOWED_CATEGORIES, list_recipients

logger = logging.getLogger("news_broadcast")

# In-process guards (дополняют DB lock)
_rate_bucket: list[float] = []
_local_locks: set[str] = set()


def _env_int(name: str, default: int) -> int:
    import os

    try:
        return int((os.getenv(name) or str(default)).strip() or default)
    except ValueError:
        return default


def rate_per_min() -> int:
    return max(1, _env_int("NEWS_BROADCAST_RATE_PER_MIN", 30))


def frequency_hours() -> int:
    return max(1, _env_int("NEWS_BROADCAST_FREQUENCY_HOURS", 24))


def max_recipients() -> int:
    return max(1, _env_int("NEWS_BROADCAST_MAX_RECIPIENTS", 50000))


def _rate_ok() -> bool:
    now = time.time()
    window = 60.0
    limit = rate_per_min()
    global _rate_bucket
    _rate_bucket = [t for t in _rate_bucket if now - t < window]
    if len(_rate_bucket) >= limit:
        return False
    _rate_bucket.append(now)
    return True


async def _frequency_cap_ok(category: str) -> bool:
    hours = frequency_hours()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id FROM news_broadcast_jobs
            WHERE category = $1
              AND status IN ('queued', 'running', 'done')
              AND created_at > now() - make_interval(hours => $2)
            ORDER BY id DESC
            LIMIT 1
            """,
            category,
            int(hours),
        )
    return row is None


async def create_job(
    *,
    actor_id: int,
    body_html: str,
    category: str = "general",
    title: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    cat = (category or "general").strip().lower()
    if cat not in ALLOWED_CATEGORIES:
        raise ValueError(f"Неизвестная категория: {category}")
    text = (body_html or "").strip()
    if not text:
        raise ValueError("Пустой текст")
    if len(text) > 4000:
        raise ValueError("Текст слишком длинный")
    if not _rate_ok():
        raise PermissionError("Rate limit рассылки новостей")
    if not await _frequency_cap_ok(cat):
        raise PermissionError(
            f"Frequency cap: категория «{cat}» уже рассылалась за {frequency_hours()}ч"
        )

    key = (idempotency_key or "").strip() or f"news-{cat}-{uuid.uuid4().hex}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM news_broadcast_jobs WHERE idempotency_key = $1",
            key,
        )
        if existing:
            security_log.info(
                "news_job_idempotent key=%s job=%s actor=%s",
                key[:48],
                existing["id"],
                pseudo_user(actor_id),
            )
            return dict(existing)

        row = await conn.fetchrow(
            """
            INSERT INTO news_broadcast_jobs (
                idempotency_key, category, title, body_html, status, created_by
            ) VALUES ($1, $2, $3, $4, 'queued', $5)
            RETURNING *
            """,
            key,
            cat,
            (title or "")[:200] or None,
            text,
            int(actor_id),
        )
        await conn.execute(
            """
            INSERT INTO news_broadcast_audit (job_id, actor_id, action, detail)
            VALUES ($1, $2, 'create', $3::jsonb)
            """,
            row["id"],
            int(actor_id),
            json.dumps({"category": cat, "idempotency_key": key}),
        )
    security_log.info(
        "news_job_created job=%s cat=%s actor=%s",
        row["id"],
        cat,
        pseudo_user(actor_id),
    )
    return dict(row)


async def _try_lock(job_id: int) -> str | None:
    token = uuid.uuid4().hex
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE news_broadcast_jobs
            SET status = 'running',
                locked_at = now(),
                lock_token = $2,
                started_at = COALESCE(started_at, now())
            WHERE id = $1
              AND status = 'queued'
              AND (locked_at IS NULL OR locked_at < now() - interval '30 minutes')
            RETURNING id
            """,
            int(job_id),
            token,
        )
    return token if row else None


async def run_job(bot, job_id: int) -> dict[str, Any]:
    """Отправка только opted-in пользователям; защита от параллельного запуска."""
    lock_key = f"job:{job_id}"
    if lock_key in _local_locks:
        raise PermissionError("Job уже выполняется (local lock)")
    token = await _try_lock(job_id)
    if not token:
        raise PermissionError("Job уже запущен или не в очереди")
    _local_locks.add(lock_key)

    pool = await get_pool()
    async with pool.acquire() as conn:
        job = await conn.fetchrow(
            "SELECT * FROM news_broadcast_jobs WHERE id = $1", int(job_id)
        )
    if not job:
        _local_locks.discard(lock_key)
        raise LookupError("Job не найден")

    recipients = await list_recipients(job["category"], limit=max_recipients())
    sent = failed = skipped = 0
    delay = max(0.03, 1.0 / max(rate_per_min(), 1))

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE news_broadcast_jobs SET total = $2 WHERE id = $1",
                int(job_id),
                len(recipients),
            )

        for uid in recipients:
            # dedup per job
            async with pool.acquire() as conn:
                exists = await conn.fetchval(
                    """
                    SELECT 1 FROM news_broadcast_deliveries
                    WHERE job_id = $1 AND user_id = $2
                    """,
                    int(job_id),
                    int(uid),
                )
            if exists:
                skipped += 1
                continue
            try:
                await bot.send_message(
                    chat_id=int(uid),
                    text=job["body_html"],
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                status = "sent"
                err = None
                sent += 1
            except Exception as e:
                status = "failed"
                err = str(e)[:300]
                failed += 1
                security_log.warning(
                    "news_delivery_fail job=%s user=%s err=%s",
                    job_id,
                    pseudo_user(uid),
                    type(e).__name__,
                )
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO news_broadcast_deliveries (job_id, user_id, status, error)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (job_id, user_id) DO NOTHING
                    """,
                    int(job_id),
                    int(uid),
                    status,
                    err,
                )
                await conn.execute(
                    """
                    UPDATE news_broadcast_jobs
                    SET sent = $2, failed = $3, skipped = $4
                    WHERE id = $1 AND lock_token = $5
                    """,
                    int(job_id),
                    sent,
                    failed,
                    skipped,
                    token,
                )
            await asyncio.sleep(delay)

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE news_broadcast_jobs
                SET status = 'done',
                    finished_at = now(),
                    locked_at = NULL,
                    lock_token = NULL,
                    sent = $2, failed = $3, skipped = $4
                WHERE id = $1 AND lock_token = $5
                RETURNING *
                """,
                int(job_id),
                sent,
                failed,
                skipped,
                token,
            )
        security_log.info(
            "news_job_done job=%s sent=%s failed=%s skipped=%s",
            job_id,
            sent,
            failed,
            skipped,
        )
        return dict(row) if row else {"id": job_id, "sent": sent, "failed": failed}
    except Exception as e:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE news_broadcast_jobs
                SET status = 'failed',
                    error_summary = $2,
                    finished_at = now(),
                    locked_at = NULL,
                    lock_token = NULL
                WHERE id = $1
                """,
                int(job_id),
                str(e)[:500],
            )
        security_log.warning("news_job_failed job=%s err=%s", job_id, type(e).__name__)
        raise
    finally:
        _local_locks.discard(lock_key)


# re-export for handlers that log chat binding
__all__ = [
    "create_job",
    "run_job",
    "pseudo_chat",
    "rate_per_min",
    "frequency_hours",
]
