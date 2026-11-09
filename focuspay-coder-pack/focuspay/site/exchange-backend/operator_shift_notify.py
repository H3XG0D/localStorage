"""Уведомления в Telegram об открытии/закрытии смен операторов."""
from __future__ import annotations

import html
import logging
from typing import Literal

from config import settings
from operator_shift_store import read_operator_shift_target
from telegram_notify import send_ops_message

logger = logging.getLogger("operator_shift_notify")


async def _active_shift_names(conn) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT COALESCE(a.display_name, a.username) AS name
        FROM operator_shifts s
        JOIN operator_accounts a ON a.id = s.operator_id
        WHERE s.ended_at IS NULL AND a.is_active = TRUE
        ORDER BY s.started_at
        """
    )
    return [str(r["name"]) for r in rows if r.get("name")]


async def notify_operator_shift(
    conn,
    *,
    operator_name: str,
    action: Literal["open", "close"],
    admin_closed: bool = False,
) -> None:
    target = read_operator_shift_target()
    chat_id = int((target or {}).get("chat_id") or settings.ops_telegram_group_id() or 0)
    if not chat_id or not settings.telegram_bot_token:
        return

    topic_id = (target or {}).get("topic_id")
    name = html.escape((operator_name or "Оператор").strip())
    verb = "открыл" if action == "open" else "закрыл"
    emoji = "🟢" if action == "open" else "🔴"
    suffix = " (админ)" if admin_closed else ""

    on_shift = await _active_shift_names(conn)
    lines = [f"{emoji} <b>{name}</b> {verb} смену{suffix}"]
    if on_shift:
        lines.append(f"👷 На смене: {html.escape(', '.join(on_shift))}")
    else:
        lines.append("👷 На смене: никого")

    try:
        await send_ops_message(
            "\n".join(lines),
            chat_id=chat_id,
            message_thread_id=int(topic_id) if topic_id is not None else None,
        )
    except Exception as e:
        logger.warning("operator shift notify failed: %s", e)
