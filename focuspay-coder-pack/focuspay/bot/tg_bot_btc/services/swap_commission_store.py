"""Конфиг чата для учёта комиссий со свапов (chat_id + опционально topic)."""
from __future__ import annotations

import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def swap_commission_file() -> Path:
    explicit = (os.getenv("SWAP_COMMISSION_CONFIG_FILE") or "").strip()
    if explicit:
        return Path(explicit)
    prod = Path("/opt/tg_bot_btc/data/swap_commission_chat.json")
    if prod.parent.exists():
        return prod
    return _ROOT / "data" / "swap_commission_chat.json"


def read_swap_commission_target() -> dict | None:
    path = swap_commission_file()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    chat_id = data.get("chat_id")
    if chat_id is None:
        return None
    out: dict = {"chat_id": int(chat_id)}
    topic_id = data.get("topic_id")
    if topic_id is not None:
        out["topic_id"] = int(topic_id)
    return out


def write_swap_commission_target(chat_id: int, topic_id: int | None = None) -> Path:
    path = swap_commission_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {"chat_id": int(chat_id)}
    if topic_id is not None:
        payload["topic_id"] = int(topic_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def is_swap_commission_chat(chat_id: int | None, topic_id: int | None = None) -> bool:
    target = read_swap_commission_target()
    if not target or not chat_id:
        return False
    if int(target["chat_id"]) != int(chat_id):
        return False
    expected_topic = target.get("topic_id")
    if expected_topic is None:
        return True
    return int(expected_topic) == int(topic_id or 0)
