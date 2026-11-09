"""Хранение ожидания tx hash после «Выплачено» (bot_data + reply lookup)."""
from __future__ import annotations

import logging
import time
from typing import Any, Literal

logger = logging.getLogger("payout_pending_store")

PendingKind = Literal["buy_payout", "buy_manual", "refwd", "extwd_receipt"]
_TTL_SEC = 30 * 60
_STORE_KEY = "payout_pending_store"


def _store(bot_data: dict) -> dict:
    raw = bot_data.setdefault(_STORE_KEY, {})
    if "by_prompt" not in raw:
        raw["by_prompt"] = {}
    if "by_user" not in raw:
        raw["by_user"] = {}
    return raw


def _prune(store: dict) -> None:
    now = time.time()
    for bucket in (store.get("by_prompt"), store.get("by_user")):
        if not isinstance(bucket, dict):
            continue
        stale = [k for k, v in bucket.items() if now - float(v.get("ts", 0)) > _TTL_SEC]
        for k in stale:
            bucket.pop(k, None)


def save_pending(
    bot_data: dict,
    *,
    kind: PendingKind,
    chat_id: int,
    user_id: int,
    prompt_message_id: int,
    card_message_id: int,
    payload: dict[str, Any],
) -> None:
    store = _store(bot_data)
    _prune(store)
    entry = {
        "kind": kind,
        "chat_id": int(chat_id),
        "user_id": int(user_id),
        "prompt_message_id": int(prompt_message_id),
        "card_message_id": int(card_message_id),
        "ts": time.time(),
        **payload,
    }
    prompt_key = f"{int(chat_id)}:{int(prompt_message_id)}"
    user_key = f"{int(chat_id)}:{int(user_id)}"
    store["by_prompt"][prompt_key] = entry
    store["by_user"][user_key] = entry
    logger.info(
        "payout pending saved kind=%s chat=%s prompt=%s order=%s withdrawal=%s payout=%s",
        kind,
        chat_id,
        prompt_message_id,
        payload.get("order_id"),
        payload.get("withdrawal_id"),
        payload.get("payout_id"),
    )


def lookup_pending(
    bot_data: dict,
    *,
    chat_id: int,
    user_id: int,
    reply_to_message_id: int | None = None,
) -> dict[str, Any] | None:
    store = _store(bot_data)
    _prune(store)
    if reply_to_message_id:
        prompt_key = f"{int(chat_id)}:{int(reply_to_message_id)}"
        hit = store["by_prompt"].get(prompt_key)
        if hit:
            return dict(hit)
    user_key = f"{int(chat_id)}:{int(user_id)}"
    hit = store["by_user"].get(user_key)
    return dict(hit) if hit else None


def clear_pending(bot_data: dict, entry: dict[str, Any]) -> None:
    store = _store(bot_data)
    chat_id = int(entry.get("chat_id") or 0)
    prompt_id = entry.get("prompt_message_id")
    user_id = entry.get("user_id")
    if chat_id and prompt_id:
        store["by_prompt"].pop(f"{chat_id}:{int(prompt_id)}", None)
    if chat_id and user_id:
        store["by_user"].pop(f"{chat_id}:{int(user_id)}", None)


def sync_user_data_pending(
    context,
    *,
    kind: PendingKind,
    chat_id: int,
    user_id: int,
    card_message_id: int,
    payload: dict[str, Any],
) -> None:
    """Дублирует pending в user_data для обратной совместимости."""
    base = {
        "kind": kind,
        "chat_id": chat_id,
        "message_id": card_message_id,
        **payload,
    }
    if kind == "refwd":
        context.user_data["pending_refwd_tx"] = base
    elif kind == "extwd_receipt":
        context.user_data["pending_extwd_receipt"] = base
    else:
        context.user_data["pending_payout_tx"] = base


def clear_user_data_pending(context, kind: PendingKind) -> None:
    if kind == "refwd":
        context.user_data.pop("pending_refwd_tx", None)
    elif kind == "extwd_receipt":
        context.user_data.pop("pending_extwd_receipt", None)
    else:
        context.user_data.pop("pending_payout_tx", None)
