"""TTL registry for ephemeral Telegram messages (help, service, round results)."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

TTL_HELP = 240
TTL_RESULT = 20
TTL_ROUND = 240
TTL_SERVICE = 120
TTL_CARD = 90
REAPER_INTERVAL = 2

GROUP_TYPES = frozenset({"group", "supergroup"})
SKIP_RIGHTS_SECONDS = 45.0
_NOT_FOUND = ("message to delete not found", "message_id_invalid", "message identifier is not specified")
_NO_RIGHTS = (
    "not enough rights",
    "have no rights",
    "chat_admin_required",
    "message can't be deleted",
    "can't delete",
    "need administrator",
    "forbidden",
)

_ITEMS: list[tuple[float, int, int]] = []
_SKIP_USER_UNTIL: dict[int, float] = {}
_WARNED_CHATS: set[int] = set()


def reset_state() -> None:
    _ITEMS.clear()
    _SKIP_USER_UNTIL.clear()
    _WARNED_CHATS.clear()


def pending() -> list[tuple[float, int, int]]:
    return list(_ITEMS)


def _int_id(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def message_id_of(sent: object) -> int | None:
    if sent is None:
        return None
    direct = _int_id(sent)
    if direct is not None:
        return direct
    if isinstance(sent, dict):
        return _int_id(sent.get("message_id"))
    return _int_id(getattr(sent, "message_id", None))


def chat_id_of(chat: object) -> int | None:
    if chat is None:
        return None
    if isinstance(chat, dict):
        return _int_id(chat.get("id"))
    return _int_id(getattr(chat, "id", None))


def _type_name(raw: object) -> str:
    if raw is None:
        return ""
    value = getattr(raw, "value", raw)
    text = str(value or "").strip()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.lower()


def chat_type_of(chat: object) -> str:
    if chat is None:
        return ""
    if isinstance(chat, dict):
        return _type_name(chat.get("type"))
    return _type_name(getattr(chat, "type", None))


def is_group_chat(chat: object) -> bool:
    return chat_type_of(chat) in GROUP_TYPES


def _exc_text(exc: BaseException) -> str:
    return str(exc).lower()


def _is_not_found(exc: BaseException) -> bool:
    text = _exc_text(exc)
    return any(token in text for token in _NOT_FOUND)


def _is_no_rights(exc: BaseException) -> bool:
    text = _exc_text(exc)
    return any(token in text for token in _NO_RIGHTS)


def track(chat_id: object, message_id: object, ttl: float) -> None:
    cid = _int_id(chat_id)
    mid = _int_id(message_id)
    if cid is None or mid is None:
        return
    due = time.monotonic() + max(0.0, float(ttl))
    _ITEMS[:] = [item for item in _ITEMS if not (item[1] == cid and item[2] == mid)]
    _ITEMS.append((due, cid, mid))


def track_sent(chat_id: object, sent: object, ttl: float) -> None:
    track(chat_id, message_id_of(sent), ttl)


def track_group_result(chat_id: object, sent: object) -> None:
    """Drop a group round summary (winner, pot, commission) after TTL_RESULT."""
    cid = _int_id(chat_id)
    if cid is None or cid >= 0:
        return
    track_sent(cid, sent, TTL_RESULT)


def untrack(chat_id: object, message_id: object) -> None:
    cid = _int_id(chat_id)
    mid = _int_id(message_id)
    if cid is None or mid is None:
        return
    _ITEMS[:] = [item for item in _ITEMS if not (item[1] == cid and item[2] == mid)]


async def send_ephemeral(bot: Any, chat_id: object, text: str, ttl: float, **kwargs: Any) -> Any:
    sent = await bot.send_message(chat_id, text, **kwargs)
    track_sent(chat_id, sent, ttl)
    return sent


async def reply_ephemeral(bot: Any, message: Any, text: str, ttl: float, **kwargs: Any) -> Any:
    sent = await bot.reply_to(message, text, **kwargs)
    chat = getattr(message, "chat", None)
    if chat is None and isinstance(message, dict):
        chat = message.get("chat")
    track_sent(chat_id_of(chat), sent, ttl)
    return sent


async def try_delete_user_message(bot: Any, message: Any) -> bool:
    """Delete a player's command. Groups only; pause a chat briefly after a rights failure."""
    chat = getattr(message, "chat", None)
    if chat is None and isinstance(message, dict):
        chat = message.get("chat")
    if not is_group_chat(chat):
        return False
    chat_id = chat_id_of(chat)
    message_id = message_id_of(message)
    if chat_id is None or message_id is None:
        return False
    pause_until = _SKIP_USER_UNTIL.get(chat_id)
    if pause_until is not None and time.monotonic() < pause_until:
        return False
    try:
        await bot.delete_message(chat_id, message_id)
        _SKIP_USER_UNTIL.pop(chat_id, None)
        return True
    except Exception as exc:
        if _is_not_found(exc):
            return False
        _SKIP_USER_UNTIL[chat_id] = time.monotonic() + float(SKIP_RIGHTS_SECONDS or 0)
        if chat_id not in _WARNED_CHATS:
            _WARNED_CHATS.add(chat_id)
            logger.warning(
                "chat reaper cannot delete user messages in chat %s: %s",
                chat_id,
                exc,
            )
        return False


async def sweep(bot: Any, *, now: float | None = None) -> int:
    ts = time.monotonic() if now is None else now
    due = [item for item in _ITEMS if item[0] <= ts]
    _ITEMS[:] = [item for item in _ITEMS if item[0] > ts]
    deleted = 0
    for _, chat_id, message_id in due:
        try:
            await bot.delete_message(chat_id, message_id)
            deleted += 1
        except Exception as exc:
            if _is_not_found(exc):
                continue
            if chat_id not in _WARNED_CHATS:
                _WARNED_CHATS.add(chat_id)
                logger.warning(
                    "chat reaper cannot delete bot message chat=%s msg=%s: %s",
                    chat_id,
                    message_id,
                    exc,
                )
    return deleted


async def reaper_loop(bot: Any, interval: float = REAPER_INTERVAL) -> None:
    try:
        while True:
            try:
                await sweep(bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("chat reaper sweep failed")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("chat reaper cancelled")
        raise
