"""Эскалация чата внештатника в TG при отсутствии ответа оператора."""
from __future__ import annotations

import asyncio
import html
import logging

from config import settings
from db import get_pool

logger = logging.getLogger("exchanger_chat_escalation")

EXCHANGER_CHAT_ESCALATION_SEC = 60


async def schedule_exchanger_escalation(thread_id: int, message_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE web_chat_threads
            SET chat_escalation_msg_id = $2, updated_at = now()
            WHERE id = $1 AND source = 'exchanger'
            """,
            thread_id,
            message_id,
        )
    asyncio.create_task(_escalate_after_delay(thread_id, message_id))


async def clear_exchanger_escalation(thread_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT source FROM web_chat_threads WHERE id = $1",
            thread_id,
        )
        if not row or row["source"] != "exchanger":
            return
        await conn.execute(
            """
            UPDATE web_chat_threads
            SET chat_escalation_msg_id = NULL, updated_at = now()
            WHERE id = $1
            """,
            thread_id,
        )


async def _escalate_after_delay(thread_id: int, message_id: int) -> None:
    await asyncio.sleep(EXCHANGER_CHAT_ESCALATION_SEC)
    try:
        await _try_escalate(thread_id, message_id)
    except Exception as exc:
        logger.warning("exchanger escalation failed thread=%s: %s", thread_id, exc)


async def _try_escalate(thread_id: int, message_id: int) -> bool:
    from chat_service import exchanger_snapshot
    from external_deals_telegram import external_deals_chat
    from telegram_notify import send_ops_message

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT t.id, t.source, t.chat_escalation_msg_id, t.external_exchanger_id,
                   (SELECT sender_role FROM web_chat_messages m
                    WHERE m.thread_id = t.id ORDER BY m.id DESC LIMIT 1) AS last_sender,
                   (SELECT body FROM web_chat_messages m
                    WHERE m.thread_id = t.id ORDER BY m.id DESC LIMIT 1) AS last_body,
                   (SELECT COUNT(*)::int FROM web_chat_messages m
                    WHERE m.thread_id = t.id
                      AND m.sender_role = 'admin'
                      AND m.id > $2) AS admin_replies_after
            FROM web_chat_threads t
            WHERE t.id = $1
            """,
            thread_id,
            message_id,
        )
        if not row:
            return False
        if row["source"] != "exchanger":
            return False
        if int(row["chat_escalation_msg_id"] or 0) != message_id:
            return False
        if int(row["admin_replies_after"] or 0) > 0:
            await clear_exchanger_escalation(thread_id)
            return False
        if row["last_sender"] != "exchanger":
            await clear_exchanger_escalation(thread_id)
            return False

        ex_id = row.get("external_exchanger_id")
        ex_snap = await exchanger_snapshot(conn, int(ex_id)) if ex_id else {}
        preview = html.escape((row["last_body"] or "")[:200])
        name = html.escape(
            str(ex_snap.get("display_name") or ex_snap.get("name") or "Внештатник")
        )
        username = str(ex_snap.get("username") or "").strip().lstrip("@")
        site = (settings.public_site_url or "").rstrip("/")
        link = (
            f"{site}/ops/chat?thread={thread_id}"
            if site
            else f"/ops/chat?thread={thread_id}"
        )

        lines = [
            "⏱ <b>Ответьте внештатнику</b>",
            f"👤 {name}",
        ]
        if username:
            lines.append(f"@{html.escape(username)}")
        if preview:
            lines.append(f"💬 {preview}")
        lines.append(f'🌐 <a href="{html.escape(link)}">Открыть чат</a>')

        await conn.execute(
            """
            UPDATE web_chat_threads
            SET chat_escalated_at = now(),
                chat_escalation_msg_id = NULL,
                updated_at = now()
            WHERE id = $1
            """,
            thread_id,
        )

    chat_id, topic_id = external_deals_chat()
    if not chat_id:
        logger.warning("exchanger chat escalation skipped: no external deals group")
        return False

    await send_ops_message("\n".join(lines), chat_id=chat_id, message_thread_id=topic_id)
    logger.info("exchanger chat escalated thread=%s msg=%s", thread_id, message_id)
    return True


async def sweep_overdue_escalations() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.id, t.chat_escalation_msg_id
            FROM web_chat_threads t
            JOIN web_chat_messages m ON m.id = t.chat_escalation_msg_id
            WHERE t.source = 'exchanger'
              AND t.chat_escalation_msg_id IS NOT NULL
              AND m.created_at < now() - make_interval(secs => $1)
            """,
            EXCHANGER_CHAT_ESCALATION_SEC,
        )
    for row in rows:
        await _try_escalate(int(row["id"]), int(row["chat_escalation_msg_id"]))


async def exchanger_escalation_sweeper_loop() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            await sweep_overdue_escalations()
        except Exception as exc:
            logger.warning("exchanger escalation sweep failed: %s", exc)
