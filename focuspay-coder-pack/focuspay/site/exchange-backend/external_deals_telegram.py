"""Telegram-чат для уведомлений по внештатным сделкам."""
from __future__ import annotations

from config import settings


def external_deals_chat() -> tuple[int, int | None]:
    """(chat_id, topic_id) — отдельная группа «внештат», без топика смен."""
    chat_id = int(settings.external_deals_telegram_group_id() or 0)
    return chat_id, None
