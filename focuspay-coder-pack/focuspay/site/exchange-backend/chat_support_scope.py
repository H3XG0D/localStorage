"""Исключение служебного аккаунта @focus_operator из клиентского чата."""
from __future__ import annotations

from config import settings


async def support_operator_user_ids(conn) -> set[int]:
    """Telegram user_id аккаунта поддержки — не показывать как клиента."""
    ids: set[int] = set()
    owner = int(settings.security_telegram_user_id or 0)
    if owner:
        ids.add(owner)
    rows = await conn.fetch(
        "SELECT user_id FROM telegram_business_connections WHERE is_enabled = TRUE"
    )
    for row in rows:
        ids.add(int(row["user_id"]))
    uname = (settings.chat_support_username or "focus_operator").strip().lstrip("@").lower()
    if uname:
        uid = await conn.fetchval(
            "SELECT user_id FROM bot_users WHERE LOWER(username) = $1 LIMIT 1",
            uname,
        )
        if uid:
            ids.add(int(uid))
    return ids


def is_support_operator_user(user_id: int | None, excluded: set[int]) -> bool:
    if not user_id or not excluded:
        return False
    return int(user_id) in excluded
