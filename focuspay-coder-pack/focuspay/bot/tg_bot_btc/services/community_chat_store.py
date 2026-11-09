"""Runtime chat_id общего чата пользователей (регистрация /community в группе)."""
from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def community_chat_file() -> Path:
    explicit = (os.getenv("COMMUNITY_CHAT_ID_FILE") or "").strip()
    if explicit:
        return Path(explicit)
    prod = Path("/opt/tg_bot_btc/data/community_chat_id")
    if prod.parent.is_dir() or prod.is_file():
        return prod
    return _ROOT / "data" / "community_chat_id"


def read_community_chat_id() -> int:
    path = community_chat_file()
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


def write_community_chat_id(chat_id: int) -> Path:
    path = community_chat_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(chat_id)), encoding="utf-8")
    return path


def community_invite_file() -> Path:
    return community_chat_file().with_name("community_chat_invite_link")


def read_community_invite_link() -> str:
    path = community_invite_file()
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_community_invite_link(url: str) -> Path:
    path = community_invite_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(url.strip(), encoding="utf-8")
    return path
