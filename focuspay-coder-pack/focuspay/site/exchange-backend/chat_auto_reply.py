"""Автоответы в чате поддержки (@focus_operator / виджет на сайте)."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("chat_auto_reply")

CHE_KOGO_REPLY = (
    "Че как! На связи — оператор скоро ответит.\n"
    "Если срочно, напишите вопрос одним сообщением."
)


def matches_che_kogo(text: str | None) -> bool:
    """True, если в тексте есть «че кого» / «чё кого» (с пунктуацией и без)."""
    raw = (text or "").strip().lower().replace("ё", "е")
    if not raw:
        return False
    compact = re.sub(r"[^\w\s]+", " ", raw)
    compact = re.sub(r"\s+", " ", compact).strip()
    if compact in ("че кого", "чекого"):
        return True
    return bool(re.search(r"\bче\s*кого\b", compact))


async def maybe_reply_che_kogo(thread_id: int, buyer_text: str | None) -> None:
    """DB-driven trigger templates; legacy name kept for callers."""
    from chat_templates import maybe_apply_auto_replies

    await maybe_apply_auto_replies(thread_id, buyer_text)
