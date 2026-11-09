"""Runtime chat_id канала отзывов (регистрация /reviews в канале)."""
from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def reviews_chat_file() -> Path:
    explicit = (os.getenv("REVIEWS_CHAT_ID_FILE") or "").strip()
    if explicit:
        return Path(explicit)
    prod = Path("/opt/tg_bot_btc/data/reviews_chat_id")
    if prod.parent.is_dir() or prod.is_file():
        return prod
    return _ROOT / "data" / "reviews_chat_id"


def read_reviews_chat_id() -> int:
    path = reviews_chat_file()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return 0
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def write_reviews_chat_id(chat_id: int) -> Path:
    path = reviews_chat_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(chat_id)), encoding="utf-8")
    return path
