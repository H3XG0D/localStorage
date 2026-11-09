"""Входящие реки: «PDF не пройден» → просим у клиента видео.

Диалог реки читает только Telethon. Группу Appeals этот опрос не заменяет.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque

from services.appeals_messages import parse_reki_pdf_failed
from services.reki_poll import poll_ready

logger = logging.getLogger("reki_inbox")

POLL_SECONDS = 20
INBOX_LIMIT = 20
_SEEN_MAX = 400

_seen: set[int] = set()
_seen_order: deque[int] = deque()
_missing_logged: set[str] = set()


def _remember(message_id: int) -> None:
    if message_id in _seen:
        return
    _seen.add(message_id)
    _seen_order.append(message_id)
    while len(_seen_order) > _SEEN_MAX:
        _seen.discard(_seen_order.popleft())


async def find_reki_order_id(payfast_id: str | None, client_ref: str | None) -> str | None:
    """Заявка по UUID реки или по нашему order_id, если «ваш id» с ним совпал."""
    from services.db import get_order, get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        if payfast_id:
            row = await conn.fetchrow(
                """
                SELECT order_id FROM manual_requisite_tickets
                WHERE merchant_order_id = $1
                  AND order_id IS NOT NULL
                  AND status = 'LINKED'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                payfast_id,
            )
            if row and row["order_id"]:
                return str(row["order_id"])
            row = await conn.fetchrow(
                """
                SELECT order_id FROM orders
                WHERE payment_snapshot->>'reki_payfast_id' = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                payfast_id,
            )
            if row and row["order_id"]:
                return str(row["order_id"])
    if client_ref:
        order = await get_order(client_ref)
        if order and order.get("order_id"):
            return str(order["order_id"])
    return None


async def handle_reki_notice(text: str, *, bot=None) -> str:
    """ok | dedup | ignored | missing | failed."""
    parsed = parse_reki_pdf_failed(text)
    if parsed is None:
        return "ignored"
    payfast_id, client_ref = parsed
    order_id = await find_reki_order_id(payfast_id, client_ref)
    if not order_id:
        key = payfast_id or client_ref or ""
        if key and key not in _missing_logged:
            logger.warning(
                "reki pdf-failed: order not found payfast=%s client=%s",
                payfast_id,
                client_ref,
            )
            _missing_logged.add(key)
        return "missing"
    from services.video_receipt_request import request_client_receipt_check

    try:
        ok, reason = await request_client_receipt_check(
            order_id,
            3,
            bot=bot,
            source="reki_inbox",
            allow_late=False,
        )
    except Exception:
        logger.warning("reki video request failed order=%s", order_id, exc_info=True)
        return "failed"
    if ok and reason in ("dedup", "video_already_submitted"):
        return "dedup"
    if ok:
        return "ok"
    logger.warning(
        "reki video request rejected order=%s reason=%s",
        order_id,
        reason,
    )
    if reason == "awaiting_check_rejected":
        return "failed"
    return "rejected"


async def poll_reki_inbox_once(*, bot=None) -> int:
    """Сколько новых просьб видео ушло клиентам."""
    from services.reki_request import fetch_recent_incoming_texts

    messages = await fetch_recent_incoming_texts(limit=INBOX_LIMIT)
    asked = 0
    for message_id, text in messages:
        if message_id in _seen:
            continue
        outcome = await handle_reki_notice(text, bot=bot)
        if outcome in ("missing", "failed"):
            continue
        _remember(message_id)
        if outcome == "ok":
            asked += 1
    return asked


async def reki_inbox_task(*, shutdown_event: asyncio.Event | None = None) -> None:
    if not poll_ready():
        logger.info("reki inbox disabled: no session")
        return
    while shutdown_event is None or not shutdown_event.is_set():
        delay = POLL_SECONDS
        try:
            asked = await poll_reki_inbox_once()
            if asked:
                logger.info("reki inbox: asked video for %s orders", asked)
        except Exception as exc:
            if type(exc).__name__ == "FloodWaitError":
                delay = max(delay, int(getattr(exc, "seconds", 0) or 0) + 5, 300)
                logger.warning("reki inbox flood wait: sleeping %ss", delay)
            else:
                logger.warning("reki inbox failed", exc_info=True)
                delay = max(delay, 60)
        if shutdown_event is None:
            await asyncio.sleep(delay)
            continue
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            continue
