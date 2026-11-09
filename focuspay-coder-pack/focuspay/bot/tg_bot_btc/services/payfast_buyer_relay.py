"""Мост /msg: текст Payfast покупателю и якорь ответа обратно в чат."""
from __future__ import annotations

import html
import logging
import re

from handlers.appeals_stat import client_alias, parse_stat_ref
from services.db import get_pool
from services.text_sanitize import sanitize_telegram_html

logger = logging.getLogger("payfast_buyer_relay")

MAX_BODY_LEN = 3500

_CMD_RE = re.compile(r"^/msg(?:@[A-Za-z0-9_]+)?(?=\s|$)", re.IGNORECASE)

HINT = "Использование: <code>/msg ID_заявки текст</code>"
SHIFT_ON = "Сейчас на смене есть оператор. /msg недоступна."
SHIFT_UNKNOWN = "Не удалось проверить смену. /msg не отправлена."
NO_BUYER = "По этой заявке покупатель не в боте, написать нельзя."
NOT_FOUND = "Заявка не найдена."
TOO_LONG = "Текст слишком длинный."
NOT_DELIVERED = "Не доставлено: клиент не открывал бота или заблокировал его."
COPY_FAILED = "Не удалось доставить ответ клиента."


def relay_shift_block_reason(gate) -> str | None:
    """Отказ новой /msg: есть смена, локальный список смен или смену не прочитали.

    None — смены нет, команду можно слать. Ответ покупателя на уже
    отправленное сообщение этой проверкой не закрывается.
    """
    reason = str(getattr(gate, "reason", "") or "")
    if reason == "check_failed":
        return "check_failed"
    try:
        active = int(getattr(gate, "active_count", 0) or 0)
    except (TypeError, ValueError):
        active = 0
    store = tuple(getattr(gate, "store_user_ids", ()) or ())
    if active > 0 or store:
        return "on_shift"
    return None


def parse_msg_command(text: str | None) -> tuple[str | None, str]:
    """(id заявки, текст). Пустой id — команды нет или id не разобран."""
    raw = (text or "").strip()
    match = _CMD_RE.match(raw)
    if not match:
        return None, ""
    rest = raw[match.end() :].strip()
    if not rest:
        return None, ""
    parts = rest.split(None, 1)
    ref = parse_stat_ref(parts[0])
    body = parts[1].strip() if len(parts) > 1 else ""
    return ref, body


def format_buyer_dm(order_id: str, body: str) -> str:
    safe_id = html.escape(str(order_id or "").strip())
    safe_body = html.escape(body.strip())
    text = (
        f"Сообщение по заявке <code>{safe_id}</code>\n\n"
        f"{safe_body}\n\n"
        "Ответьте на это сообщение: текст, видео, стикер или смайл уйдёт обратно. "
        "Ваш профиль не показывается."
    )
    return sanitize_telegram_html(text)


def format_group_ack(alias: str, order_id: str) -> str:
    text = (
        f"Отправлено клиенту {html.escape(alias)}\n"
        f"Заявка: <code>{html.escape(str(order_id or '').strip())}</code>"
    )
    return sanitize_telegram_html(text)


def format_client_label(buyer_user_id: int) -> str:
    return f"Клиент {client_alias(int(buyer_user_id))}"


def reply_reaches_receipt_handler(message) -> bool:
    """Видео и файл всё равно должны дойти до приёма чека."""
    return bool(
        getattr(message, "video", None)
        or getattr(message, "document", None)
        or getattr(message, "video_note", None)
    )


async def insert_relay_anchor(
    *,
    order_id: str,
    buyer_user_id: int,
    buyer_message_id: int,
    group_chat_id: int,
    group_message_id: int,
    message_thread_id: int | None,
    sender_tg_id: int | None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO payfast_buyer_relay (
                order_id, buyer_user_id, buyer_message_id,
                group_chat_id, group_message_id, message_thread_id, sender_tg_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (buyer_user_id, buyer_message_id) DO NOTHING
            """,
            str(order_id),
            int(buyer_user_id),
            int(buyer_message_id),
            int(group_chat_id),
            int(group_message_id),
            int(message_thread_id) if message_thread_id else None,
            int(sender_tg_id) if sender_tg_id else None,
        )


async def find_relay_anchor(buyer_user_id: int, buyer_message_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT order_id, buyer_user_id, buyer_message_id,
                   group_chat_id, group_message_id, message_thread_id
            FROM payfast_buyer_relay
            WHERE buyer_user_id = $1 AND buyer_message_id = $2
            """,
            int(buyer_user_id),
            int(buyer_message_id),
        )
    if not row:
        return None
    return dict(row)
