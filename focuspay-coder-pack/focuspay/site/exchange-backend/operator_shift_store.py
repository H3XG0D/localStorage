"""Чат/топик уведомлений о сменах + множество активных canonical Telegram user_id.

Источник истины «кто на смене» — PostgreSQL ``operator_shifts``.
Файл зеркалит набор Telegram id и хранит chat/topic для нотификаций.

Инварианты:
- идентификатор оператора — только положительный numeric Telegram user_id
  (не username, не web operator_id, не chat_id < 0);
- два последовательных открытия дополняют множество, а не перезаписывают;
- ``topic_id is None`` отличается от конкретного топика;
- запись chat/topic не затирает ``active_user_ids``.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("operator_shift_store")


def _config_path() -> Path:
    explicit = (os.getenv("OPERATOR_SHIFT_CONFIG_FILE") or "").strip()
    if explicit:
        return Path(explicit)
    bot_root = Path(os.getenv("TG_BOT_PATH", "/opt/tg_bot_btc"))
    return bot_root / "data" / "operator_shifts_chat.json"


def canonical_telegram_user_id(value) -> int | None:
    """Стабильный Telegram user_id. Отклоняет username / chat_id / мусор."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.startswith("@") or text.startswith("-"):
            return None
        if not text.isdigit():
            return None
        value = int(text)
    else:
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
    if value <= 0:
        return None
    return value


def normalize_topic_id(value) -> int | None:
    if value is None or value is False or value == "":
        return None
    try:
        topic = int(value)
    except (TypeError, ValueError):
        return None
    if topic <= 0:
        return None
    return topic


def _canonical_id_list(values: Iterable | None) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for raw in values or ():
        cid = canonical_telegram_user_id(raw)
        if cid is None or cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


def _normalize_state(data: dict) -> dict:
    chat_raw = data.get("chat_id")
    chat_id = None
    if chat_raw is not None and chat_raw is not False and chat_raw != "":
        try:
            chat_id = int(chat_raw)
        except (TypeError, ValueError):
            chat_id = None
    out: dict = {
        "active_user_ids": _canonical_id_list(data.get("active_user_ids")),
    }
    if chat_id is not None:
        out["chat_id"] = chat_id
    topic_id = normalize_topic_id(data.get("topic_id"))
    if topic_id is not None:
        out["topic_id"] = topic_id
    updated = data.get("updated_at")
    if updated:
        out["updated_at"] = str(updated)
    return out


def _locked_update(mutator) -> dict:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text("{}\n", encoding="utf-8")
    with path.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            raw = fh.read()
            try:
                data = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                logger.warning("operator shift store corrupt, resetting json")
                data = {}
            if not isinstance(data, dict):
                data = {}
            mutator(data)
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            normalized = _normalize_state(data)
            text = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
            fh.seek(0)
            fh.truncate()
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
            return normalized
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def read_operator_shift_state() -> dict:
    path = _config_path()
    if not path.is_file():
        return {"active_user_ids": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"active_user_ids": []}
    if not isinstance(data, dict):
        return {"active_user_ids": []}
    return _normalize_state(data)


def read_operator_shift_target() -> dict | None:
    state = read_operator_shift_state()
    chat_id = state.get("chat_id")
    if chat_id is None:
        return None
    out: dict = {"chat_id": int(chat_id)}
    if "topic_id" in state:
        out["topic_id"] = int(state["topic_id"])
    return out


def write_operator_shift_target(chat_id: int, topic_id: int | None = None) -> Path:
    def mutator(data: dict) -> None:
        data["chat_id"] = int(chat_id)
        normalized_topic = normalize_topic_id(topic_id)
        if normalized_topic is None:
            data.pop("topic_id", None)
        else:
            data["topic_id"] = normalized_topic

    _locked_update(mutator)
    return _config_path()


def list_active_shift_user_ids() -> list[int]:
    return list(read_operator_shift_state().get("active_user_ids") or [])


def replace_active_shift_user_ids(user_ids: Iterable) -> list[int]:
    canonical = _canonical_id_list(user_ids)

    def mutator(data: dict) -> None:
        data["active_user_ids"] = canonical

    state = _locked_update(mutator)
    return list(state.get("active_user_ids") or [])


def add_active_shift_user(user_id) -> list[int]:
    cid = canonical_telegram_user_id(user_id)
    if cid is None:
        logger.info("shift_store skip add: not a canonical telegram user_id")
        return list_active_shift_user_ids()

    def mutator(data: dict) -> None:
        current = _canonical_id_list(data.get("active_user_ids"))
        if cid not in current:
            current.append(cid)
        data["active_user_ids"] = current

    state = _locked_update(mutator)
    return list(state.get("active_user_ids") or [])


def remove_active_shift_user(user_id) -> list[int]:
    cid = canonical_telegram_user_id(user_id)

    def mutator(data: dict) -> None:
        current = _canonical_id_list(data.get("active_user_ids"))
        if cid is not None:
            data["active_user_ids"] = [x for x in current if x != cid]
        else:
            data["active_user_ids"] = current

    state = _locked_update(mutator)
    return list(state.get("active_user_ids") or [])


def same_shift_chat_context(
    chat_id: int | None,
    topic_id: int | None,
    *,
    stored: dict | None = None,
) -> bool:
    target = stored if stored is not None else read_operator_shift_target()
    if not target or target.get("chat_id") is None or chat_id is None:
        return False
    try:
        stored_chat = int(target["chat_id"])
        incoming_chat = int(chat_id)
    except (TypeError, ValueError):
        return False
    if stored_chat != incoming_chat:
        return False
    return normalize_topic_id(target.get("topic_id")) == normalize_topic_id(topic_id)


async def sync_active_shift_user_ids_from_db(conn) -> list[int]:
    """Пересобирает множество из всех открытых смен. Не затирает предыдущего оператора."""
    rows = await conn.fetch(
        """
        SELECT a.telegram_user_id
        FROM operator_shifts s
        JOIN operator_accounts a ON a.id = s.operator_id
        WHERE s.ended_at IS NULL
          AND a.is_active = TRUE
        ORDER BY s.started_at
        """
    )
    raw_ids = [r["telegram_user_id"] for r in rows]
    synced = replace_active_shift_user_ids(raw_ids)
    unbound = sum(1 for value in raw_ids if canonical_telegram_user_id(value) is None)
    logger.info(
        "shift_store synced active_tg=%s unbound=%s db_open=%s",
        synced,
        unbound,
        len(rows),
    )
    return synced
