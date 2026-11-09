"""Рассылка по whitelist бота внештатников."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import HTTPException

from db import get_pool
from exchanger_bot_api import TelegramApiError, send_message
from exchanger_bot_config import fetch_config_row

logger = logging.getLogger("exchanger_bot_broadcast")

BROADCAST_DELAY = 0.05
_running: set[int] = set()
_cancel: set[int] = set()


def parse_audience(audience: str) -> tuple[str, int | None]:
    raw = (audience or "all").strip().lower()
    if raw in ("all", "owners", "clerks"):
        return raw, None
    if raw.startswith("exchanger:"):
        try:
            return "exchanger", int(raw.split(":", 1)[1])
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректный магазин в audience") from None
    raise HTTPException(status_code=400, detail="audience: all | owners | clerks | exchanger:{id}")


async def list_recipient_ids(audience: str) -> list[int]:
    kind, exchanger_id = parse_audience(audience)
    clauses = ["is_active = TRUE"]
    args: list[Any] = []
    if kind == "owners":
        clauses.append("role = 'owner'")
    elif kind == "clerks":
        clauses.append("role = 'clerk'")
    elif kind == "exchanger":
        args.append(exchanger_id)
        clauses.append(f"exchanger_id = ${len(args)}")
    sql = (
        "SELECT telegram_user_id FROM exchanger_bot_members WHERE "
        + " AND ".join(clauses)
        + " ORDER BY id"
    )
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [int(r["telegram_user_id"]) for r in rows]


def _job_out(row) -> dict[str, Any]:
    data = dict(row)
    for key in ("created_at", "started_at", "finished_at"):
        if data.get(key) is not None:
            data[key] = data[key].isoformat()
    return data


async def create_broadcast(*, audience: str, text: str, created_by: int | None) -> dict[str, Any]:
    message = (text or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Текст пустой")
    cfg = await fetch_config_row()
    if not cfg or not cfg.get("token"):
        raise HTTPException(status_code=400, detail="Бот не подключён")
    if _running:
        raise HTTPException(status_code=409, detail="Уже идёт рассылка")
    ids = await list_recipient_ids(audience)
    if not ids:
        raise HTTPException(status_code=400, detail="В аудитории никого нет")
    parse_audience(audience)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO exchanger_bot_broadcasts (
                audience, message_text, status, total_count, created_by
            ) VALUES ($1, $2, 'pending', $3, $4)
            RETURNING *
            """,
            audience,
            message,
            len(ids),
            created_by,
        )
    job_id = int(row["id"])
    asyncio.create_task(_run_job(job_id, ids, cfg["token"], message))
    return _job_out(row)


async def list_broadcasts(limit: int = 30) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM exchanger_bot_broadcasts ORDER BY id DESC LIMIT $1",
            limit,
        )
    return [_job_out(r) for r in rows]


async def cancel_broadcast(job_id: int) -> dict[str, Any]:
    _cancel.add(job_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM exchanger_bot_broadcasts WHERE id = $1",
            job_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Рассылка не найдена")
    return _job_out(row)


async def _run_job(job_id: int, ids: list[int], token: str, text: str) -> None:
    _running.add(job_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE exchanger_bot_broadcasts
            SET status = 'running', started_at = now()
            WHERE id = $1
            """,
            job_id,
        )
    sent = 0
    failed = 0
    sample = None
    try:
        for i, chat_id in enumerate(ids):
            if job_id in _cancel:
                break
            try:
                await send_message(token, chat_id, text)
                sent += 1
            except TelegramApiError as exc:
                failed += 1
                sample = sample or str(exc)[:400]
            if (i + 1) % 25 == 0:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE exchanger_bot_broadcasts
                        SET sent_count = $1, failed_count = $2
                        WHERE id = $3
                        """,
                        sent,
                        failed,
                        job_id,
                    )
            await asyncio.sleep(BROADCAST_DELAY)
        status = "cancelled" if job_id in _cancel else "done"
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE exchanger_bot_broadcasts
                SET sent_count = $1, failed_count = $2, status = $3,
                    error_summary = $4, finished_at = now()
                WHERE id = $5
                """,
                sent,
                failed,
                status,
                sample,
                job_id,
            )
    except Exception:
        logger.exception("exchanger bot broadcast %s failed", job_id)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE exchanger_bot_broadcasts
                SET status = 'failed', sent_count = $1, failed_count = $2,
                    finished_at = now()
                WHERE id = $3
                """,
                sent,
                failed,
                job_id,
            )
    finally:
        _running.discard(job_id)
        _cancel.discard(job_id)
