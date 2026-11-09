"""Проверка группы отчётов. В чужой группе молчим."""
from __future__ import annotations

from services import config_rates


async def reply_wrong_reports_group(update) -> bool:
    """
    True = вызывающий должен выйти: чат не группа отчётов.

    В чужой группе молчим всем, не только админам. Иначе /help и /dash
    доходят до отказа «нет доступа» в общем чате. Подсказку по chat_id
    даёт /chatid, а не публичный ответ.
    """
    chat_id = update.effective_chat.id if update.effective_chat else None
    return not config_rates.is_reports_group_chat(chat_id)
