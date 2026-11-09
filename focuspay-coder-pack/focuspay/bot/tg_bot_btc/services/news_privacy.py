"""Псевдонимизация chat_id / user_id для общих логов новостей."""
from __future__ import annotations

import hashlib
import logging

_SALT = "focuspay-news-privacy-v1"
security_log = logging.getLogger("security.news")


def pseudo_chat(chat_id: int | None) -> str:
    h = hashlib.sha256(f"{_SALT}:chat:{chat_id}".encode()).hexdigest()[:12]
    return f"chat_{h}"


def pseudo_user(user_id: int | None) -> str:
    h = hashlib.sha256(f"{_SALT}:user:{user_id}".encode()).hexdigest()[:12]
    return f"user_{h}"
