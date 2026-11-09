"""Shared live roulette card: one message per chat, countdown then spin beats."""
from __future__ import annotations

import html
from typing import Any

from games.board_style import PHASE_LABELS, render_board, seconds_until
from games.chat_reaper import TTL_RESULT
from games.drama import is_done, is_running, run_beats
from games.live_card import LiveCardBoard, edit_html_message

_BOARD: LiveCardBoard | None = None

SPIN_BEATS: tuple[tuple[str, float], ...] = (
    ("bets_closed", 2.0),
    ("spinning", 3.0),
    ("slowing", 2.0),
    ("reveal", 0.0),
)


def _fmt_money(value: object) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "0"
    text = f"{amount:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _mention(player: dict[str, Any]) -> str:
    try:
        uid = int(player.get("user_id") or 0)
    except (TypeError, ValueError):
        uid = 0
    name = html.escape(str(player.get("display_name") or uid or "игрок")[:80])
    if uid > 0:
        return f'<a href="tg://user?id={uid}">{name}</a>'
    return name


def _color_ru(color: object) -> str:
    raw = str(color or "")
    if raw == "red":
        return "красное"
    if raw == "black":
        return "чёрное"
    if raw == "green":
        return "зеро"
    return ""


def _round_short(snapshot: dict[str, Any]) -> str:
    round_id = str(snapshot.get("round_id") or "")
    return round_id.replace("-", "")[:8].upper() or "——"


def drama_key(chat_id: int, snapshot: dict[str, Any] | None) -> str | None:
    snap = snapshot if isinstance(snapshot, dict) else {}
    status = str(snap.get("status") or "")
    round_id = str(snap.get("round_id") or "")
    if not round_id or status not in {"locked", "spinning", "settled"}:
        return None
    return f"roulette:{round_id}:{chat_id}"


def _hide_pocket(snapshot: dict[str, Any], *, phase: str | None) -> bool:
    status = str(snapshot.get("status") or "")
    if status not in {"locked", "spinning", "settled"}:
        return False
    if phase == "reveal":
        return False
    key_done = False
    round_id = str(snapshot.get("round_id") or "")
    if round_id:
        key_done = any(
            is_done(f"roulette:{round_id}:{chat_id}")
            for chat_id in (_BOARD.cards() if _BOARD is not None else {})
        )
    if phase is None and (status == "settled" or key_done):
        return False
    return True


def card_text(
    snapshot: dict[str, Any] | None,
    *,
    just_placed: bool = False,
    phase: str | None = None,
) -> str:
    from games.roulette_table import STAKE_ACCEPTED_TITLE, timer_line

    snap = snapshot if isinstance(snapshot, dict) else {}
    players = snap.get("players") if isinstance(snap.get("players"), list) else []
    roster: list[str] = []
    bank = 0.0
    unique: set[int] = set()
    for row in players:
        if not isinstance(row, dict):
            continue
        try:
            unique.add(int(row.get("user_id") or 0))
        except (TypeError, ValueError):
            pass
        try:
            bank += float(row.get("stake_rub") or 0)
        except (TypeError, ValueError):
            pass
        title = html.escape(str(row.get("title_ru") or row.get("bet") or "ставка"))
        odds = html.escape(str(row.get("odds_ru") or "").strip())
        stake = _fmt_money(row.get("stake_rub"))
        extra = f" ({odds})" if odds else ""
        roster.append(f"• {_mention(row)} — {title} {stake} ₽{extra}")
    if just_placed and not roster:
        roster.append("• ставка принята")
    count = int(snap.get("player_count") or len(unique) or 0)
    hide = _hide_pocket(snap, phase=phase)
    extra: list[str] = []
    if not hide:
        pocket = snap.get("pocket")
        if pocket is not None:
            color = _color_ru(snap.get("color"))
            extra.append(f"Выпало <b>{int(pocket)}</b>" + (f" {html.escape(color)}" if color else ""))
    now = PHASE_LABELS.get(phase or "", "")
    if not now:
        status = str(snap.get("status") or "")
        if status in {"locked", "spinning"}:
            now = PHASE_LABELS["spinning"]
        elif status == "settled" and not hide:
            now = PHASE_LABELS["settled"]
        elif status in {"", "open"}:
            now = PHASE_LABELS["collect"] if seconds_until(snap.get("closes_at")) is not None else PHASE_LABELS["waiting_first"]
    nxt = "Ждём спин" if str(snap.get("status") or "") in {"", "open"} else ""
    if hide:
        nxt = ""
        timer = ""
    else:
        timer = timer_line(snap)
    return render_board(
        header=STAKE_ACCEPTED_TITLE,
        subtitle=f"Рулетка 0–36 · раунд #{_round_short(snap)}",
        money=f"Банк: {_fmt_money(bank)} ₽ · игроков {count}",
        roster=roster,
        now=now,
        nxt=nxt,
        timer=timer,
        extra=extra,
    )


def _keyboard(snapshot: dict[str, Any] | None) -> Any:
    from games.roulette_table import _table_keyboard

    return _table_keyboard()


def _is_terminal(snapshot: dict[str, Any] | None) -> bool:
    status = str((snapshot or {}).get("status") or "")
    if status != "settled":
        return False
    snap = snapshot if isinstance(snapshot, dict) else {}
    round_id = str(snap.get("round_id") or "")
    if not round_id or _BOARD is None:
        return True
    keys = [f"roulette:{round_id}:{chat_id}" for chat_id in _BOARD.cards()]
    if not keys:
        return True
    if any(is_running(key) for key in keys):
        return False
    return any(is_done(key) for key in keys)


async def _fetch(client: Any, telegram_id: int | None, chat_id: int | None = None) -> dict[str, Any]:
    _ = chat_id
    data = await client.get_roulette_table(telegram_id=telegram_id)
    return data if isinstance(data, dict) else {}


async def _start_spin(bot: Any, chat_id: int, snapshot: dict[str, Any], card: dict[str, Any]) -> None:
    key = drama_key(chat_id, snapshot)
    if not key or is_running(key) or is_done(key):
        return
    markup = _keyboard(snapshot)
    beats = [(_make_beat(bot, chat_id, snapshot, card, markup, phase), delay, phase) for phase, delay in SPIN_BEATS]
    await run_beats(key, beats)


def _make_beat(bot: Any, chat_id: int, snapshot: dict[str, Any], card: dict[str, Any], markup: Any, phase: str):
    async def _run() -> None:
        mid = card.get("message_id")
        if not isinstance(mid, int):
            return
        text = card_text(snapshot, phase=phase)
        await edit_html_message(bot, chat_id, mid, text, markup, log_name="roulette")

    return _run


async def _on_snapshot(bot: Any, client: Any, chat_id: int, snap: dict[str, Any], card: dict[str, Any]) -> bool:
    _ = client
    key = drama_key(chat_id, snap)
    if not key:
        return False
    if is_done(key):
        return False
    await _start_spin(bot, chat_id, snap, card)
    return True


def _board() -> LiveCardBoard:
    global _BOARD
    if _BOARD is None:
        _BOARD = LiveCardBoard(
            name="roulette",
            interval=5,
            fetch=_fetch,
            render=card_text,
            keyboard=_keyboard,
            terminal=_is_terminal,
            ttl=TTL_RESULT,
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
