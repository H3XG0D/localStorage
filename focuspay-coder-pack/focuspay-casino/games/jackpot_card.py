"""Shared live jackpot card: adaptive countdown, then reel beats."""
from __future__ import annotations

from typing import Any

from games.board_style import seconds_until
from games.chat_reaper import TTL_RESULT
from games.drama import is_done, is_running, run_beats
from games.live_card import LiveCardBoard, edit_html_message

_BOARD: LiveCardBoard | None = None

REEL_BEATS: tuple[tuple[str, float], ...] = (
    ("reel", 3.0),
    ("finalists", 3.0),
    ("reveal", 0.0),
)


def drama_key(chat_id: int, snapshot: dict[str, Any] | None) -> str | None:
    snap = snapshot if isinstance(snapshot, dict) else {}
    status = str(snap.get("status") or "")
    if status not in {"locked", "settled"}:
        return None
    round_id = str(snap.get("round_id") or "live")
    return f"jackpot:{round_id}:{chat_id}"


def interval_for(snapshot: dict[str, Any] | None) -> float:
    snap = snapshot if isinstance(snapshot, dict) else {}
    status = str(snap.get("status") or "")
    if status in {"locked", "settled"}:
        return 2.0
    left = seconds_until(snap.get("closes_at"))
    if left is None:
        return 30.0
    if left <= 10:
        return 2.0
    if left <= 60:
        return 5.0
    return 30.0


def card_text(snapshot: dict[str, Any] | None, *, phase: str | None = None) -> str:
    from games.jackpot import STAKE_ACCEPTED_TITLE, status_text

    snap = snapshot if isinstance(snapshot, dict) else {}
    hide = False
    status = str(snap.get("status") or "")
    if status in {"locked", "settled"} and phase != "reveal":
        hide = True
        key_round = str(snap.get("round_id") or "live")
        if phase is None and _BOARD is not None:
            hide = not any(
                is_done(f"jackpot:{key_round}:{chat_id}")
                for chat_id in _BOARD.cards()
            )
    body = status_text(snap, phase=phase, hide_winner=hide)
    if status in {"", "open"}:
        return f"{STAKE_ACCEPTED_TITLE}\n{body}"
    return body


def _keyboard(snapshot: dict[str, Any] | None) -> Any:
    from games.jackpot import _status_keyboard

    return _status_keyboard(snapshot, include_watch=True)


def _is_terminal(snapshot: dict[str, Any] | None) -> bool:
    status = str((snapshot or {}).get("status") or "")
    if status == "refunded":
        return True
    if status != "settled":
        return False
    snap = snapshot if isinstance(snapshot, dict) else {}
    round_id = str(snap.get("round_id") or "live")
    if _BOARD is None:
        return True
    keys = [f"jackpot:{round_id}:{chat_id}" for chat_id in _BOARD.cards()]
    if not keys:
        return True
    if any(is_running(key) for key in keys):
        return False
    return any(is_done(key) for key in keys)


async def _fetch(client: Any, telegram_id: int | None, chat_id: int | None = None) -> dict[str, Any]:
    _ = chat_id
    data = await client.get_jackpot(telegram_id=telegram_id)
    return data if isinstance(data, dict) else {}


def _make_beat(bot: Any, chat_id: int, snapshot: dict[str, Any], card: dict[str, Any], markup: Any, phase: str):
    async def _run() -> None:
        mid = card.get("message_id")
        if not isinstance(mid, int):
            return
        text = card_text(snapshot, phase=phase)
        await edit_html_message(bot, chat_id, mid, text, markup, log_name="jackpot")

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


def _board() -> LiveCardBoard:
    global _BOARD
    if _BOARD is None:
        _BOARD = LiveCardBoard(
            name="jackpot",
            interval=30,
            fetch=_fetch,
            render=card_text,
            keyboard=_keyboard,
            terminal=_is_terminal,
            ttl=TTL_RESULT,
            interval_fn=interval_for,
            on_snapshot=_on_snapshot,
            drama_key=drama_key,
        )
    return _BOARD


def reset_state() -> None:
    global _BOARD
    if _BOARD is not None:
        _BOARD.reset()
        _BOARD = None


async def drain_state() -> None:
    global _BOARD
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
) -> None:
    await _board().upsert(bot, client, chat_id, snapshot, telegram_id=telegram_id)


async def drop(bot: Any, chat_id: int) -> None:
    await _board().drop(bot, chat_id)
