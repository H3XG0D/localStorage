"""Deliver FocusLucky Telegram DMs from raffle_notification_outbox."""
from __future__ import annotations

import asyncio
import json
import logging

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, RetryAfter, TelegramError

from services.db import get_pool

logger = logging.getLogger("raffle_notify")


def reply_markup_from_payload(payload: dict) -> InlineKeyboardMarkup | None:
    raw = payload.get("reply_markup")
    if not isinstance(raw, dict):
        return None
    rows = raw.get("inline_keyboard")
    if not isinstance(rows, list) or not rows:
        return None
    keyboard: list[list[InlineKeyboardButton]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        buttons: list[InlineKeyboardButton] = []
        for btn in row:
            if not isinstance(btn, dict):
                continue
            text = str(btn.get("text") or "").strip()
            url = str(btn.get("url") or "").strip()
            if not text or not url:
                continue
            buttons.append(InlineKeyboardButton(text=text, url=url))
        if buttons:
            keyboard.append(buttons)
    if not keyboard:
        return None
    return InlineKeyboardMarkup(keyboard)


async def raffle_notify_task(bot: Bot, shutdown_event: asyncio.Event) -> None:
    while not shutdown_event.is_set():
        try:
            await _flush_once(bot)
        except Exception:
            logger.exception("raffle notify flush")
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=2.0)
            return
        except asyncio.TimeoutError:
            continue


async def _flush_once(bot: Bot) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT to_regclass('public.raffle_notification_outbox')")
        if not exists:
            return
        rows = await conn.fetch(
            """
            UPDATE raffle_notification_outbox
            SET status = 'processing', claimed_at = now(), attempts = attempts + 1
            WHERE id IN (
                SELECT id FROM raffle_notification_outbox
                WHERE status = 'pending' AND available_at <= now()
                ORDER BY id
                LIMIT 40
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, recipient_id, payload
            """
        )
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        chat_id = int(payload.get("chat_id") or row["recipient_id"])
        text = str(payload.get("text") or "")
        parse_mode = payload.get("parse_mode") or "HTML"
        markup = reply_markup_from_payload(payload) if isinstance(payload, dict) else None
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=bool(payload.get("disable_web_page_preview", False)),
                reply_markup=markup,
            )
            status = "sent"
            err = None
        except RetryAfter as exc:
            status = "pending"
            err = str(exc)
            await asyncio.sleep(float(getattr(exc, "retry_after", 1) or 1))
        except Forbidden:
            status = "failed"
            err = "forbidden"
        except TelegramError as exc:
            status = "failed"
            err = str(exc)
        except Exception as exc:
            status = "failed"
            err = str(exc)
        async with pool.acquire() as conn:
            if status == "pending":
                await conn.execute(
                    """
                    UPDATE raffle_notification_outbox
                    SET status = 'pending', available_at = now() + interval '15 seconds', last_error = $2::text
                    WHERE id = $1
                    """,
                    row["id"],
                    err,
                )
            else:
                await conn.execute(
                    """
                    UPDATE raffle_notification_outbox
                    SET status = $2::varchar,
                        completed_at = CASE WHEN $2::varchar = 'sent' THEN now() ELSE completed_at END,
                        last_error = $3::text
                    WHERE id = $1
                    """,
                    row["id"],
                    status,
                    err,
                )
