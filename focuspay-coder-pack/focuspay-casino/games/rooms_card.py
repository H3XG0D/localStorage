"""Live equal-stake room card: countdown after fill, then reel beats."""
from __future__ import annotations

from typing import Any

from games.board_style import seconds_until
from games.chat_reaper import TTL_RESULT
from games.drama import is_done, is_running, run_beats
from games.live_card import LiveCardBoard, edit_html_message

_BOARD: LiveCardBoard | None = None
_ROOM_BY_CHAT: dict[int, str] = {}

REEL_BEATS: tuple[tuple[str, float], ...] = (
    ("reel", 3.0),
    ("finalists", 3.0),
    ("reveal", 0.0),
)


def drama_key(chat_id: int, snapshot: dict[str, Any] | None) -> str | None:
    snap = snapshot if isinstance(snapshot, dict) else {}
    status = str(snap.get("status") or "")
    room_id = str(snap.get("room_id") or "")
    if not room_id or status not in {"locked", "settled"}:
        return None
    return f"room:{room_id}:{chat_id}"


def card_text(
    snapshot: dict[str, Any] | None,
    *,
    viewer_id: int | None = None,
    phase: str | None = None,
) -> str:
    from games.rooms import room_card_text

    return room_card_text(snapshot, viewer_id=viewer_id, phase=phase)


def _keyboard(snapshot: dict[str, Any] | None) -> Any:
    from games.rooms import _card_keyboard

    return _card_keyboard(snapshot)


def _is_terminal(snapshot: dict[str, Any] | None) -> bool:
    status = str((snapshot or {}).get("status") or "")
    if status == "cancelled":
        return True
    if status != "settled":
        return False
    snap = snapshot if isinstance(snapshot, dict) else {}
    room_id = str(snap.get("room_id") or "")
    if not room_id or _BOARD is None:
        return True
    keys = [f"room:{room_id}:{chat_id}" for chat_id in _BOARD.cards()]
    if not keys:
        return True
    if any(is_running(key) for key in keys):
        return False
    return any(is_done(key) for key in keys)


async def _fetch(client: Any, telegram_id: int | None, chat_id: int | None = None) -> dict[str, Any]:
    room_id = _ROOM_BY_CHAT.get(int(chat_id or 0))
    if not room_id:
        return {}
    data = await client.get_fixed_room(room_id, telegram_id=telegram_id)
    return data if isinstance(data, dict) else {}


def _make_beat(bot: Any, chat_id: int, snapshot: dict[str, Any], card: dict[str, Any], markup: Any, phase: str):
    async def _run() -> None:
        mid = card.get("message_id")
        if not isinstance(mid, int):
            return
        text = card_text(snapshot, viewer_id=card.get("telegram_id") if isinstance(card.get("telegram_id"), int) else None, phase=phase)
        await edit_html_message(bot, chat_id, mid, text, markup, log_name="rooms")

    return _run


async def _start_reel(bot: Any, chat_id: int, snapshot: dict[str, Any], card: dict[str, Any]) -> None:
    key = drama_key(chat_id, snapshot)
    if not key or is_running(key) or is_done(key):
        return
    markup = _keyboard(snapshot)
    beats = [(_make_beat(bot, chat_id, snapshot, card, markup, phase), delay, phase) for phase, delay in REEL_BEATS]
    await run_beats(key, beats)


async def _on_snapshot(bot: Any, client: Any, chat_id: int, snap: dict[str, Any], card: dict[str, Any]) -> bool:
    _ = client
    key = drama_key(chat_id, snap)
    if not key:
        return False
    if is_done(key):
        return False
    await _start_reel(bot, chat_id, snap, card)
    return True


def _interval_for(snapshot: dict[str, Any] | None) -> float:
    snap = snapshot if isinstance(snapshot, dict) else {}
    status = str(snap.get("status") or "")
    if status in {"countdown", "locked", "settled"}:
        return 2.0
    left = seconds_until(snap.get("countdown_ends_at") or snap.get("closes_at"))
    if left is not None and left <= 15:
        return 2.0
    return 5.0


def _board() -> LiveCardBoard:
    global _BOARD
    if _BOARD is None:
        _BOARD = LiveCardBoard(
            name="rooms",
            interval=5,
            fetch=_fetch,
            render=lambda snap: card_text(snap),
            keyboard=_keyboard,
            terminal=_is_terminal,
            ttl=TTL_RESULT,
            interval_fn=_interval_for,
            on_snapshot=_on_snapshot,
            drama_key=drama_key,
        )
    return _BOARD


def reset_state() -> None:
    global _BOARD
    _ROOM_BY_CHAT.clear()
    if _BOARD is not None:
        _BOARD.reset()
        _BOARD = None


async def drain_state() -> None:
    global _BOARD
    _ROOM_BY_CHAT.clear()
    if _BOARD is not None:
        await _BOARD.drain()
        _BOARD = None


def peek(chat_id: int) -> dict[str, Any] | None:
    return _board().peek(chat_id)


async def upsert(
    bot: Any,
    client: Any,
    chat_id: int,
    snapshot: dict[str, Any] | None,
    *,
    telegram_id: int | None = None,
    message_id: int | None = None,
) -> None:
    snap = snapshot if isinstance(snapshot, dict) else {}
    room_id = str(snap.get("room_id") or "")
    if room_id:
        _ROOM_BY_CHAT[chat_id] = room_id
    await _board().upsert(
        bot, client, chat_id, snap, telegram_id=telegram_id, message_id=message_id
    )


async def drop(bot: Any, chat_id: int) -> None:
    _ROOM_BY_CHAT.pop(chat_id, None)
    await _board().drop(bot, chat_id)
