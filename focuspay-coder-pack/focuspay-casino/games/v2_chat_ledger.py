"""Ephemeral Telegram message ids for a V2 table play surface."""
from __future__ import annotations

from typing import Any

_LEDGERS: dict[str, dict[str, Any]] = {}
_FINALIZED: set[str] = set()


def _int_id(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def normalize_msg_ids(raw: object) -> list[int]:
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    seen: set[int] = set()
    for item in raw:
        mid = _int_id(item)
        if mid is None or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out


def add_trash(chats: list[dict[str, Any]], *, chat_id: int, message_id: int) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    found = False
    for row in chats:
        nxt = dict(row)
        if nxt.get("chat_id") == chat_id:
            ids = normalize_msg_ids(nxt.get("trash_msg_ids"))
            if message_id not in ids:
                ids.append(message_id)
            nxt["trash_msg_ids"] = ids
            found = True
        updated.append(nxt)
    if not found:
        updated.append({
            "chat_id": chat_id,
            "card_msg_id": None,
            "roll_msg_id": None,
            "trash_msg_ids": [message_id],
        })
    return updated


def collect_trash(table: dict[str, Any]) -> list[tuple[int, int]]:
    """Return (chat_id, message_id) pairs the bot should delete after the result is posted."""
    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()

    def add(chat_id: object, message_id: object) -> None:
        cid = _int_id(chat_id)
        mid = _int_id(message_id)
        if cid is None or mid is None:
            return
        key = (cid, mid)
        if key in seen:
            return
        seen.add(key)
        pairs.append(key)

    state = table.get("game_state")
    state = dict(state) if isinstance(state, dict) else {}
    add(state.get("listing_chat_id"), state.get("listing_msg_id"))
    add(table.get("game_chat_id") or state.get("chat_id"), state.get("card_msg_id"))
    add(table.get("game_chat_id") or state.get("chat_id"), state.get("roll_msg_id"))
    raw = state.get("play_chats")
    if isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict):
                continue
            chat_id = row.get("chat_id")
            add(chat_id, row.get("card_msg_id"))
            add(chat_id, row.get("roll_msg_id"))
            for mid in normalize_msg_ids(row.get("trash_msg_ids")):
                add(chat_id, mid)
    return pairs


def result_chat_ids(table: dict[str, Any]) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()

    def add(chat_id: object) -> None:
        cid = _int_id(chat_id)
        if cid is None or cid in seen:
            return
        seen.add(cid)
        ids.append(cid)

    state = table.get("game_state")
    state = dict(state) if isinstance(state, dict) else {}
    raw = state.get("play_chats")
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict):
                add(row.get("chat_id"))
    add(table.get("game_chat_id"))
    add(state.get("chat_id"))
    add(state.get("listing_chat_id"))
    return ids


def remember_table(table: dict[str, Any]) -> None:
    table_id = str(table.get("table_id") or "")
    if table_id:
        _LEDGERS[table_id] = table


def recall_table(table_id: str) -> dict[str, Any] | None:
    stored = _LEDGERS.get(str(table_id or ""))
    return stored if isinstance(stored, dict) else None


def forget_table(table_id: str) -> None:
    _LEDGERS.pop(str(table_id or ""), None)


def try_mark_finalized(table_id: str) -> bool:
    token = str(table_id or "")
    if not token or token in _FINALIZED:
        return False
    _FINALIZED.add(token)
    return True


def already_finalized(table_id: str) -> bool:
    return str(table_id or "") in _FINALIZED


def reset_ledger_state() -> None:
    _LEDGERS.clear()
    _FINALIZED.clear()
