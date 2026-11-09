"""Forum topics for published reviews: VPN and exchanges stay in separate threads.

The public reviews place is a channel, and a channel cannot have topics. An admin
turns Topics on in a group and sends /review_topics. Approved reviews are copied
into «VPN» or «Обмены». Until that group is registered, publishing stays on the channel.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("review_topics")

_ROOT = Path(__file__).resolve().parent.parent

TOPIC_VPN = "vpn"
TOPIC_EXCHANGE = "exchange"
TOPIC_NAMES = {
    TOPIC_VPN: "VPN",
    TOPIC_EXCHANGE: "Обмены",
}


class ReviewTopicsError(Exception):
    pass


def topics_file() -> Path:
    explicit = (os.getenv("REVIEW_TOPICS_FILE") or "").strip()
    if explicit:
        return Path(explicit)
    prod = Path("/opt/tg_bot_btc/data/review_topics.json")
    if prod.parent.is_dir() or prod.is_file():
        return prod
    return _ROOT / "data" / "review_topics.json"


def product_topic(product: str | None) -> str:
    return TOPIC_VPN if (product or "") == "vpn" else TOPIC_EXCHANGE


def read_store() -> dict:
    path = topics_file()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_store(data: dict) -> Path:
    path = topics_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def thread_id(store: dict | None, product: str | None) -> int | None:
    raw = (store or {}).get(product_topic(product))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value or None


def thread_kwargs(chat_id, product: str | None) -> dict:
    """Thread id when this chat is the registered reviews forum. Otherwise empty."""
    store = read_store()
    try:
        forum_id = int(store.get("chat_id") or 0)
        target = int(chat_id)
    except (TypeError, ValueError):
        return {}
    if not forum_id or forum_id != target:
        return {}
    thread = thread_id(store, product)
    if not thread:
        return {}
    return {"message_thread_id": thread}


def is_review_topics_chat(chat_id: int | None) -> bool:
    store = read_store()
    try:
        forum_id = int(store.get("chat_id") or 0)
    except (TypeError, ValueError):
        return False
    return bool(forum_id) and int(chat_id or 0) == forum_id


def same_chat(left, right) -> bool:
    try:
        return int(left) == int(right) and int(left) != 0
    except (TypeError, ValueError):
        return False


async def copy_into_topic(
    bot,
    *,
    product: str | None,
    from_chat_id,
    text_message_id: int | None,
    photo_message_id: int | None = None,
) -> None:
    """Copy an already published channel post into the product topic."""
    store = read_store()
    try:
        forum_id = int(store.get("chat_id") or 0)
    except (TypeError, ValueError):
        return
    thread = thread_id(store, product)
    if not forum_id or not thread or not text_message_id or not from_chat_id:
        return
    if same_chat(from_chat_id, forum_id):
        return
    await bot.forward_message(
        chat_id=forum_id,
        from_chat_id=from_chat_id,
        message_id=int(text_message_id),
        message_thread_id=thread,
    )
    if photo_message_id:
        await bot.forward_message(
            chat_id=forum_id,
            from_chat_id=from_chat_id,
            message_id=int(photo_message_id),
            message_thread_id=thread,
        )


async def ensure_topics(bot, chat_id: int) -> dict:
    """Create VPN and Обмены once. A second call in the same chat reuses them."""
    chat = await bot.get_chat(chat_id)
    if not getattr(chat, "is_forum", False):
        raise ReviewTopicsError(
            "В этом чате нет тем. В настройках группы включите «Темы» и отправьте /review_topics ещё раз. "
            "Канал темы не поддерживает."
        )
    store = read_store()
    try:
        stored_chat = int(store.get("chat_id") or 0)
    except (TypeError, ValueError):
        stored_chat = 0
    if stored_chat == int(chat_id) and thread_id(store, TOPIC_VPN) and thread_id(store, TOPIC_EXCHANGE):
        return store
    created = {"chat_id": int(chat_id)}
    for key, name in TOPIC_NAMES.items():
        topic = await bot.create_forum_topic(chat_id=int(chat_id), name=name)
        created[key] = int(topic.message_thread_id)
    write_store(created)
    log.warning("review topics registered chat=%s vpn=%s exchange=%s", chat_id, created[TOPIC_VPN], created[TOPIC_EXCHANGE])
    return created
