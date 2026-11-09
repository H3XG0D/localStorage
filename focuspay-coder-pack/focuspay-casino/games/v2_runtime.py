"""Telegram runtime for durable V2 tables: dice, cards, outbox, recovery."""
from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from telebot import types
from telebot.async_telebot import AsyncTeleBot

from games.baccara import bak_hand_score
from games.board_style import PHASE_LABELS, render_board, seconds_until
from games.catalog import CARD_GAMES, emoji_for_canonical, fmt_id
from games.card_streets import RESULT_BEAT_SECONDS, STREET_PAUSE_SECONDS, dealing_label, street_count, visible_hands
from games.drama import REVEAL_HOLD_SECONDS, is_running, run_beats, wait_drama
from games.v2_table_gameplay import (
    all_rolls_complete,
    apply_roll,
    leader_seat_nos,
    occupied_seat_nos,
    required_roll_count,
    seat_totals,
    tie_break_state,
)
from games.v2_tables import _game_config, _idempotency, _seat_counts, _table_seats
from games.card_fairness import fairness_href, verify_url
from games.dice_timing import wait_dice_landed
from games.result_notify import format_personal_result_dm
from games.site_links import add_watch_button, table_url
from games.v2_chat_ledger import (
    add_trash,
    already_finalized,
    collect_trash,
    forget_table,
    normalize_msg_ids,
    recall_table,
    remember_table,
    result_chat_ids,
    try_mark_finalized,
)
from games.chat_reaper import track_group_result
import config
from telegram_reliability import classify_telegram_delivery_error

logger = logging.getLogger(__name__)

_roll_index: dict[tuple[int, int], str] = {}
_table_roll_locks: dict[str, asyncio.Lock] = {}
_READY_WATCH: dict[str, dict[str, Any]] = {}
_ROLL_WATCH: dict[str, dict[str, Any]] = {}
_CARD_WATCH: dict[str, dict[str, Any]] = {}
_HIT_UNTIL = 17
READY_TICK_INTERVAL = 3.0
START_DELAY_GRACE_SECONDS = 20
DELAY_NOTICE = "Старт задерживается, ждём сервер"
SCORE_BEAT_SECONDS = 2.0
BLACKJACK_REMINDER_SECONDS = 15
GONE_STATUS = "gone"
BJ_START_PREFIX = "bj_"
CARD_BACK = "🂠"
PLAY_STATUSES = {"running", "tie_break_running"}
SHOWDOWN_STATUSES = {
    "finished", "cancelled", "expired", "manual_review",
    "outcome_committed", "settled", "settling",
}


def _table_id(table: dict[str, Any]) -> str:
    return str(table.get("table_id") or "")


def _state(table: dict[str, Any]) -> dict[str, Any]:
    state = table.get("game_state")
    return dict(state) if isinstance(state, dict) else {}


def _version(table: dict[str, Any]) -> int:
    return int(table.get("state_version") or 0)


def _draw_policy(state: dict[str, Any]) -> str:
    policy = state.get("draw_policy")
    return policy if policy in {"tie_break", "tie_split"} else "tie_break"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_starts_at(state: dict[str, Any]) -> datetime | None:
    raw = state.get("starts_at")
    if raw in (None, ""):
        return None
    try:
        ends = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if ends.tzinfo is None:
        ends = ends.replace(tzinfo=timezone.utc)
    return ends


def _lobby_start_line(table: dict[str, Any]) -> str | None:
    if str(table.get("status") or "") != "ready":
        return None
    starts = _parse_starts_at(_state(table))
    if starts is None:
        return "Старт вот-вот"
    remaining = int((starts - _utc_now()).total_seconds())
    if remaining > 0:
        return f"Старт через {remaining} с"
    if remaining > -START_DELAY_GRACE_SECONDS:
        return "Старт вот-вот"
    return DELAY_NOTICE


def _required_rolls(table: dict[str, Any]) -> int:
    state = _state(table)
    configured = state.get("rounds")
    return required_roll_count(str(table.get("game_type")), configured_rolls=int(configured) if configured else None)


def _active_seat_nos(state: dict[str, Any], roster: list[dict[str, Any]]) -> list[int]:
    leaders = state.get("tie_break_seat_nos")
    if isinstance(leaders, list) and leaders:
        return [int(seat_no) for seat_no in leaders]
    if isinstance(state.get("seat_nos"), list) and state["seat_nos"]:
        return [int(seat_no) for seat_no in state["seat_nos"]]
    return [int(seat["seat_no"]) for seat in roster if isinstance(seat, dict)]


def _chat_id(table: dict[str, Any]) -> int | None:
    raw = table.get("game_chat_id")
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    state = _state(table)
    chat_id = state.get("chat_id")
    return chat_id if isinstance(chat_id, int) and not isinstance(chat_id, bool) else None


def _is_private_chat_id(chat_id: int) -> bool:
    return chat_id > 0


async def _bound_group_chat_id(client) -> int | None:
    try:
        binding = await client.get_active_game_chat_binding()
    except Exception:
        return None
    if not isinstance(binding, dict):
        return None
    chat_id = binding.get("chat_id")
    return chat_id if isinstance(chat_id, int) and not isinstance(chat_id, bool) else None


def _play_chats(table: dict[str, Any]) -> list[dict[str, Any]]:
    raw = _state(table).get("play_chats")
    chats: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict):
                continue
            chat_id = row.get("chat_id")
            if isinstance(chat_id, int) and not isinstance(chat_id, bool):
                chats.append({
                    "chat_id": chat_id,
                    "card_msg_id": row.get("card_msg_id") if isinstance(row.get("card_msg_id"), int) else None,
                    "roll_msg_id": row.get("roll_msg_id") if isinstance(row.get("roll_msg_id"), int) else None,
                    "trash_msg_ids": normalize_msg_ids(row.get("trash_msg_ids")),
                })
    if chats:
        return chats
    chat_id = _chat_id(table)
    if not isinstance(chat_id, int):
        return []
    state = _state(table)
    return [{
        "chat_id": chat_id,
        "card_msg_id": state.get("card_msg_id") if isinstance(state.get("card_msg_id"), int) else None,
        "roll_msg_id": state.get("roll_msg_id") if isinstance(state.get("roll_msg_id"), int) else None,
        "trash_msg_ids": normalize_msg_ids(state.get("trash_msg_ids")),
    }]


def _upsert_play_chat(
    chats: list[dict[str, Any]],
    *,
    chat_id: int,
    card_msg_id: int | None = None,
    roll_msg_id: int | None = None,
) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    found = False
    for row in chats:
        if row.get("chat_id") == chat_id:
            nxt = dict(row)
            if isinstance(card_msg_id, int):
                nxt["card_msg_id"] = card_msg_id
            if isinstance(roll_msg_id, int):
                nxt["roll_msg_id"] = roll_msg_id
            updated.append(nxt)
            found = True
        else:
            updated.append(dict(row))
    if not found:
        updated.append({
            "chat_id": chat_id,
            "card_msg_id": card_msg_id,
            "roll_msg_id": roll_msg_id,
            "trash_msg_ids": [],
        })
    return updated


def _play_state_patch(table: dict[str, Any], chats: list[dict[str, Any]]) -> dict[str, Any]:
    patch: dict[str, Any] = {"play_chats": chats}
    primary = _chat_id(table)
    for row in chats:
        if row.get("chat_id") != primary:
            continue
        if isinstance(row.get("card_msg_id"), int):
            patch["card_msg_id"] = row["card_msg_id"]
        if isinstance(row.get("roll_msg_id"), int):
            patch["roll_msg_id"] = row["roll_msg_id"]
        if isinstance(primary, int):
            patch["chat_id"] = primary
        break
    return patch


def _roster_names(table: dict[str, Any]) -> dict[str, Any]:
    raw = _state(table).get("roster_names")
    return dict(raw) if isinstance(raw, dict) else {}


def _apply_actor_roster(table: dict[str, Any], actor: Any | None) -> dict[str, Any]:
    """Stamp the creator's Telegram name onto seat 1 before the first board paint."""
    if actor is None:
        return table
    identity = _identity_from_user(actor)
    if not identity:
        return table
    actor_id = getattr(actor, "id", None)
    seat = _seat_for_player(table, actor_id) if isinstance(actor_id, int) and not isinstance(actor_id, bool) else None
    if seat is None:
        for row in _table_seats(table):
            if isinstance(row, dict) and int(row.get("seat_no") or 0) == 1:
                seat = row
                break
    if not isinstance(seat, dict):
        return table
    nxt = dict(table)
    state = dict(_state(table))
    state["roster_names"] = _merge_roster_name(table, seat_no=int(seat["seat_no"]), identity=identity)
    nxt["game_state"] = state
    return nxt


def _identity_from_user(user: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    telegram_id = getattr(user, "id", None)
    first = getattr(user, "first_name", None)
    username = getattr(user, "username", None)
    if isinstance(telegram_id, int) and not isinstance(telegram_id, bool):
        payload["telegram_id"] = telegram_id
    if isinstance(first, str) and first.strip():
        payload["first_name"] = first.strip()
    if isinstance(username, str) and username.strip():
        payload["username"] = username.strip()
    return payload


def _merge_roster_name(table: dict[str, Any], *, seat_no: int, identity: dict[str, Any]) -> dict[str, Any]:
    names = _roster_names(table)
    names[str(int(seat_no))] = identity
    return names


def _is_card_table(table: dict[str, Any]) -> bool:
    return str(table.get("game_type")) in CARD_GAMES


def _index_roll_prompt(table_id: str, chat_id: int, message_id: int) -> None:
    _roll_index[(chat_id, message_id)] = table_id


def _as_telegram_id(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def extract_blackjack_start_table_id(payload: str | None) -> str | None:
    raw = (payload or "").strip()
    if raw.startswith("/start"):
        raw = raw[6:].strip()
    if not raw.lower().startswith(BJ_START_PREFIX):
        return None
    token = raw[len(BJ_START_PREFIX):].strip()
    return token or None


def blackjack_dm_start_url(table_id: str) -> str:
    username = str(getattr(config, "BOT_USERNAME", "") or "").strip().lstrip("@")
    if not username:
        return ""
    return f"https://t.me/{username}?start={BJ_START_PREFIX}{table_id}"


def _telegram_cannot_dm(exc: BaseException) -> bool:
    error_kind, _ = classify_telegram_delivery_error(exc)
    return error_kind == "dm_unavailable"


def _seat_for_player(table: dict[str, Any], telegram_id: int) -> dict[str, Any] | None:
    want = _as_telegram_id(telegram_id)
    if want is None:
        return None
    for seat in _table_seats(table):
        if not isinstance(seat, dict) or seat.get("participant_kind") != "player":
            continue
        if _as_telegram_id(seat.get("telegram_id")) == want:
            return seat
    return None


def _is_blackjack(table: dict[str, Any]) -> bool:
    return str(table.get("game_type") or "") == "blackjack"


def _dm_blocked_ids(table: dict[str, Any]) -> list[int]:
    raw = _state(table).get("dm_blocked")
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for item in raw:
        tid = _as_telegram_id(item)
        if tid is not None and tid not in out:
            out.append(tid)
    return out


def _decisions_map(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("decisions")
    return dict(raw) if isinstance(raw, dict) else {}


def _stood_seat_nos(state: dict[str, Any]) -> set[int]:
    out: set[int] = set()
    raw = state.get("stood_seats")
    if isinstance(raw, list):
        for item in raw:
            try:
                out.add(int(item))
            except (TypeError, ValueError):
                continue
    for key, value in _decisions_map(state).items():
        if not value:
            continue
        try:
            out.add(int(key))
        except (TypeError, ValueError):
            continue
    return out


def _blackjack_showdown(table: dict[str, Any]) -> bool:
    if not _is_blackjack(table):
        return True
    status = str(table.get("status") or "")
    if status in SHOWDOWN_STATUSES or status == GONE_STATUS:
        return True
    state = _state(table)
    phase = str(state.get("phase") or "")
    if phase in {"scoring", "draw_choice", "settled"}:
        return True
    roster = _table_seats(table)
    active = _active_seat_nos(state, roster)
    if not active:
        return False
    stood = _stood_seat_nos(state)
    return all(seat_no in stood for seat_no in active)


def _blackjack_state_patch(
    table: dict[str, Any],
    *,
    hands: dict[str, Any] | None = None,
    decisions: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = _state(table)
    next_hands = hands if hands is not None else (state.get("hands") if isinstance(state.get("hands"), dict) else {})
    next_decisions = decisions if decisions is not None else _decisions_map(state)
    stood = sorted(
        int(key)
        for key, value in next_decisions.items()
        if value
        and str(key).lstrip("-").isdigit()
    )
    patch: dict[str, Any] = {
        "hands": next_hands,
        "decisions": next_decisions,
        "stood_seats": stood,
        "phase": "hitting",
    }
    if extra:
        patch.update(extra)
    return patch


def _bot_seats(table: dict[str, Any]) -> list[dict[str, Any]]:
    return [seat for seat in _table_seats(table) if isinstance(seat, dict) and seat.get("participant_kind") == "bot"]


def format_v2_settlement(payload: dict[str, Any], table: dict[str, Any] | None = None) -> str:
    kind = str(payload.get("outcome_kind") or "")
    payouts = [row for row in (payload.get("payouts") if isinstance(payload.get("payouts"), list) else []) if isinstance(row, dict)]
    roster_table = table if isinstance(table, dict) else (payload.get("table") if isinstance(payload.get("table"), dict) else None)
    payout_by_seat: dict[int, dict[str, Any]] = {}
    for row in payouts:
        try:
            payout_by_seat[int(row["seat_no"])] = row
        except (TypeError, ValueError, KeyError):
            continue
    winner_nos: list[int] = []
    raw_winners = payload.get("winner_seat_nos")
    if isinstance(raw_winners, list) and raw_winners:
        for item in raw_winners:
            try:
                winner_nos.append(int(item))
            except (TypeError, ValueError):
                continue
    elif kind in {"winner", "tie_split"}:
        winner_nos = list(payout_by_seat)
    def _winner_label(seat_no: int) -> str:
        if roster_table:
            for seat in _table_seats(roster_table):
                if isinstance(seat, dict) and int(seat.get("seat_no") or 0) == seat_no:
                    return _seat_name(seat, roster_table)
        return _party_label(seat_no, roster_table)

    labels = [_winner_label(seat_no) for seat_no in winner_nos]
    if kind == "winner" and len(labels) == 1:
        headline = f"🏆 Победил: {labels[0]}"
    elif kind == "winner" and labels:
        headline = f"🏆 Победили: {', '.join(labels)}"
    elif kind == "winner":
        headline = "🏆 Победитель"
    elif kind == "tie_split":
        headline = f"Ничья: {', '.join(labels)}" if labels else "Ничья, ставки возвращены"
    else:
        headline = kind or "—"
    config = _game_config(roster_table) if roster_table else {"name": "", "emoji": "🏁"}
    game_name = str(config.get("name") or "")
    table_token = str(payload.get("table_id") or (roster_table or {}).get("table_id") or "")
    title = f"🏁 <b>Стол #{fmt_id(table_token)}</b>"
    if game_name:
        title = f"{title} — {game_name}"
    pot = payload.get("pot_rub", "—")
    commission = payload.get("commission_rub", "—")
    win_amount = None
    if kind == "winner" and len(winner_nos) == 1:
        win_amount = payout_by_seat.get(winner_nos[0], {}).get("amount_rub")
    if win_amount is not None:
        money = f"💰 Выигрыш: {win_amount} ₽ · банк {pot} ₽ · комиссия {commission} ₽"
    else:
        money = f"💰 Банк: {pot} ₽ · комиссия {commission} ₽"
    return "\n".join([title, headline, money])


def _max_seats(table: dict[str, Any]) -> int:
    try:
        return max(0, int(table.get("max_seats") or table.get("max_players") or 0))
    except (TypeError, ValueError):
        return 0


def _lobby_card_text(table: dict[str, Any]) -> str:
    config = _game_config(table)
    _people, _bots, free = _seat_counts(table)
    state = _state(table)
    draw = {"tie_break": "переброс лидеров", "tie_split": "возврат ставок"}.get(_draw_policy(state), "—")
    seats = _max_seats(table)
    roster_rows: list[str] = []
    by_no: dict[int, dict[str, Any]] = {}
    for seat in _table_seats(table):
        if not isinstance(seat, dict):
            continue
        try:
            by_no[int(seat["seat_no"])] = seat
        except (TypeError, ValueError, KeyError):
            continue
    for seat_no in range(1, seats + 1):
        seat = by_no.get(seat_no)
        if seat:
            roster_rows.append(f"{seat_no}. {_seat_name(seat, table)}")
        else:
            roster_rows.append(f"{seat_no}. — свободно")
    if seats <= 0:
        roster_rows.append("— мест нет")
    start_line = _lobby_start_line(table)
    status = str(table.get("status") or "")
    now = ""
    if status == "ready":
        now = PHASE_LABELS["delayed"] if start_line == DELAY_NOTICE else PHASE_LABELS["countdown"]
    elif status == "open":
        now = PHASE_LABELS["collect"]
    nxt = "Займите место или добавьте бота" if status == "open" else ""
    return render_board(
        header=f"{config['emoji']} <b>Стол #{fmt_id(_table_id(table))}</b> — {config['name']} · {table.get('stake_rub', '—')} ₽",
        subtitle=f"Мест {seats or '—'} · свободно {free}",
        roster=roster_rows,
        now=now,
        nxt=nxt,
        timer=start_line,
        extra=[f"Ничья: {draw}"],
    )


def _cancel_button(table: dict[str, Any]) -> Any:
    return types.InlineKeyboardButton("❌ Отменить стол", callback_data=f"v2cancel:{_table_id(table)}")


def _join_keyboard(table: dict[str, Any]) -> types.InlineKeyboardMarkup | None:
    if table.get("status") != "open":
        return None
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("✅ Занять место", callback_data=f"v2join:{_table_id(table)}"))
    _people, _bots, free = _seat_counts(table)
    if free > 0:
        keyboard.add(types.InlineKeyboardButton("➕ Бот", callback_data=f"v2bot:{_table_id(table)}"))
    keyboard.add(_cancel_button(table))
    add_watch_button(keyboard, table_url(_table_id(table)))
    return keyboard


def _result_keyboard(table: dict[str, Any], *, seed: str | None = None) -> types.InlineKeyboardMarkup | None:
    keyboard = types.InlineKeyboardMarkup()
    table_id = _table_id(table)
    watch = table_url(table_id)
    verify = None
    if _is_card_table(table):
        state = _state(table)
        href = verify_url(
            game_type=str(table.get("game_type")),
            game_id=table_id,
            commit=state.get("rng_commit") if isinstance(state.get("rng_commit"), str) else None,
            client_seed=state.get("client_seed") if isinstance(state.get("client_seed"), str) else None,
            nonce=state.get("nonce"),
            server_seed=seed if isinstance(seed, str) else None,
        )
        verify = href or None
    if not verify:
        verify = watch
    if verify:
        keyboard.add(types.InlineKeyboardButton("Проверить игру", url=verify))
    if watch and watch != verify:
        keyboard.add(types.InlineKeyboardButton("Смотреть на сайте", url=watch))
    rows = getattr(keyboard, "keyboard", None)
    return keyboard if rows else None


def _seated_names_line(table: dict[str, Any]) -> str:
    names: list[str] = []
    for seat in _table_seats(table):
        if not isinstance(seat, dict) or seat.get("participant_kind") != "player":
            continue
        names.append(_seat_name(seat, table))
    if not names:
        return ""
    return "За столом: " + ", ".join(names)


def _listing_text(table: dict[str, Any]) -> str:
    config = _game_config(table)
    _people, _bots, free = _seat_counts(table)
    max_seats = table.get("max_seats", table.get("max_players", "—"))
    lines = [
        f"{config['emoji']} <b>Стол #{fmt_id(_table_id(table))}</b> — {config['name']}",
        f"💰 Ставка: {table.get('stake_rub', '—')} ₽ · мест {max_seats}, свободно {free}",
    ]
    seated = _seated_names_line(table)
    if seated:
        lines.append(seated)
    if _is_blackjack(table):
        lines.append("Нажмите «Войти». Ваши карты и добор — в личке игрового бота. В группе — статус и итог.")
    else:
        lines.append("Нажмите «Войти», чтобы играть в этом чате.")
    if str(table.get("game_type")) in {"pvp_dice", "pvp_emoji"} and max_seats == 2:
        lines.append("Если за 60 секунд соперник не войдёт, подключится бот при доступном игровом банке. Новая ставка не списывается.")
    return "\n".join(lines)


def _listing_keyboard(table: dict[str, Any]) -> types.InlineKeyboardMarkup | None:
    if table.get("status") != "open":
        return None
    keyboard = types.InlineKeyboardMarkup()
    _people, _bots, free = _seat_counts(table)
    if free > 0:
        keyboard.add(types.InlineKeyboardButton("Войти", callback_data=f"v2join:{_table_id(table)}"))
    keyboard.add(_cancel_button(table))
    return keyboard


def _play_surface_text(table: dict[str, Any]) -> str:
    state = _state(table)
    if _is_card_table(table) and (state.get("hands") or str(table.get("status")) in {"running", "tie_break_running"}):
        return _card_text(table)
    if str(table.get("status")) in {"running", "tie_break_running"} and not _is_card_table(table):
        return _roll_text(table)
    return _lobby_card_text(table)


def _play_surface_markup(table: dict[str, Any], *, viewer_id: int | None = None) -> types.InlineKeyboardMarkup | None:
    if _is_card_table(table) and str(table.get("status")) in PLAY_STATUSES:
        return _card_keyboard(table, viewer_id=viewer_id)
    if str(table.get("status")) == "open":
        return _join_keyboard(table)
    return types.InlineKeyboardMarkup()


def _listing_converted_to_play(table: dict[str, Any]) -> bool:
    state = _state(table)
    listing_chat = state.get("listing_chat_id")
    listing_msg = state.get("listing_msg_id")
    if not isinstance(listing_chat, int) or not isinstance(listing_msg, int):
        return False
    for row in _play_chats(table):
        if row.get("chat_id") == listing_chat and row.get("card_msg_id") == listing_msg:
            return True
    return False


def _next_roller(table: dict[str, Any]) -> dict[str, Any] | None:
    state = _state(table)
    required = _required_rolls(table)
    roster = _table_seats(table)
    by_no = {int(seat["seat_no"]): seat for seat in roster if isinstance(seat, dict)}
    for seat_no in _active_seat_nos(state, roster):
        if _missing_roll_index(state, seat_no, required) is not None:
            return by_no.get(seat_no)
    return None


def _leader_line(table: dict[str, Any]) -> str:
    state = _state(table)
    required = _required_rolls(table)
    rolls = state.get("rolls") if isinstance(state.get("rolls"), dict) else {}
    roster = _table_seats(table)
    by_no = {int(seat["seat_no"]): seat for seat in roster if isinstance(seat, dict)}
    totals: dict[int, int] = {}
    for seat_no in _active_seat_nos(state, roster):
        total = 0
        seen = 0
        for index in range(required):
            key = f"s{seat_no}r{index}"
            if key in rolls:
                try:
                    total += int(rolls[key])
                    seen += 1
                except (TypeError, ValueError):
                    continue
        if seen:
            totals[seat_no] = total
    if not totals:
        return ""
    best = max(totals.values())
    leaders = [seat_no for seat_no, total in totals.items() if total == best]
    if len(leaders) != 1:
        return ""
    seat = by_no.get(leaders[0]) or {}
    return f"Ведёт {_seat_name(seat, table)}, {best}"


def _roll_text(table: dict[str, Any], *, scoring: bool = False) -> str:
    config = _game_config(table)
    state = _state(table)
    required = _required_rolls(table)
    rolls = state.get("rolls") if isinstance(state.get("rolls"), dict) else {}
    roster = _table_seats(table)
    seat_nos = _active_seat_nos(state, roster)
    by_no = {int(seat["seat_no"]): seat for seat in roster if isinstance(seat, dict)}
    rows: list[str] = []
    for seat_no in seat_nos:
        seat = by_no.get(seat_no) or {}
        name = _seat_name(seat, table)
        values = [str(rolls[f"s{seat_no}r{index}"]) for index in range(required) if f"s{seat_no}r{index}" in rolls]
        status = f"{len(values)}/{required}" if len(values) < required else "✅"
        rows.append(f"  • Место {seat_no} {name} [{status}]: {' '.join(values) or '—'}")
    roller = _next_roller(table)
    now = PHASE_LABELS["scoring"] if scoring else PHASE_LABELS["rolling"]
    if roller and not scoring:
        now = f"бросает место {int(roller.get('seat_no') or 0)} · {_seat_name(roller, table)}"
    nxt = ""
    if not scoring:
        nxt = f"киньте {config['emoji']} в этот чат. Казино кинет после вас."
    extra = [_leader_line(table)]
    if state.get("phase") == "tie_break":
        extra.insert(0, "Переброс лидеров.")
    else:
        extra.insert(0, "Киньте эмодзи в этот чат — реплай не нужен.")
    left = seconds_until(state.get("roll_deadline_at"))
    timer = f"⏳ До броска {left} с" if left is not None and not scoring else ""
    return render_board(
        header=f"{config['emoji']} <b>Стол #{fmt_id(_table_id(table))}</b> — {config['name']}",
        roster=rows,
        now=now,
        nxt=nxt,
        timer=timer,
        extra=[row for row in extra if row],
    )


def _telegram_username(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    value = raw.strip().lstrip("@")
    return value


def _player_seat_label(info: dict[str, Any], seat: dict[str, Any]) -> str:
    username = _telegram_username(info.get("username")) or _telegram_username(seat.get("username"))
    if username:
        return f"@{username}"
    first = info.get("first_name")
    if isinstance(first, str) and first.strip():
        return first.strip()
    raw = seat.get("display_name")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return "игрок"


def _seat_name(seat: dict[str, Any], table: dict[str, Any] | None = None) -> str:
    if seat.get("participant_kind") == "bot":
        label = (seat.get("bot") or {}).get("display_name") or "Бот"
        return html.escape(str(label))
    info: dict[str, Any] = {}
    if table is not None:
        stored = _roster_names(table).get(str(seat.get("seat_no")))
        if isinstance(stored, dict):
            info = stored
    label = _player_seat_label(info, seat)
    telegram_id = seat.get("telegram_id")
    if telegram_id is None:
        telegram_id = info.get("telegram_id")
    escaped = html.escape(label)
    if isinstance(telegram_id, int) and not isinstance(telegram_id, bool):
        return f'<a href="tg://user?id={telegram_id}">{escaped}</a>'
    return escaped


def _party_label(seat_no: object, table: dict[str, Any] | None) -> str:
    try:
        number = int(seat_no)
    except (TypeError, ValueError):
        return "место —"
    if table:
        for seat in _table_seats(table):
            if isinstance(seat, dict) and int(seat.get("seat_no") or 0) == number:
                return f"место {number} · {_seat_name(seat, table)}"
    return f"место {number}"


async def _annotate_roster_names(bot: AsyncTeleBot, table: dict[str, Any]) -> dict[str, Any]:
    names = _roster_names(table)
    roster = []
    for seat in _table_seats(table):
        if not isinstance(seat, dict):
            continue
        row = dict(seat)
        stored = names.get(str(row.get("seat_no")))
        if isinstance(stored, dict):
            row["display_name"] = _player_seat_label(stored, row)
            telegram_id = stored.get("telegram_id")
            if row.get("telegram_id") is None and isinstance(telegram_id, int) and not isinstance(telegram_id, bool):
                row["telegram_id"] = telegram_id
        telegram_id = row.get("telegram_id")
        if row.get("participant_kind") == "player" and isinstance(telegram_id, int) and not isinstance(telegram_id, bool):
            if not (isinstance(row.get("display_name"), str) and str(row.get("display_name")).strip()) or str(row.get("display_name")).strip() == "игрок":
                with contextlib.suppress(Exception):
                    chat = await bot.get_chat(telegram_id)
                    first = getattr(chat, "first_name", None)
                    username = getattr(chat, "username", None)
                    label = _player_seat_label({"first_name": first, "username": username}, row)
                    if label and label != "игрок":
                        row["display_name"] = label
        roster.append(row)
    annotated = dict(table)
    annotated["roster"] = roster
    return annotated


def _card_rules(game_type: str, *, private: bool = False) -> str:
    if game_type == "blackjack":
        if private:
            return "Ваши карты видите только вы. Ближе к 21, не перебрать."
        return "Карты закрыты. Ближе к 21, не перебрать. Ваши карты и добор — в личке бота."
    return "Ближе к 9. При 0–5 очках третья карта берётся сама. Ждите итог."


def _card_status(cards: list[str], *, decided: bool, active: bool, game_type: str) -> str:
    if not cards:
        return "раздача"
    if not active:
        return "ждут"
    if game_type == "blackjack":
        score = bj_best_score(cards) if cards and not _is_back_only(cards) else 0
        if decided:
            return "перебор" if score > 21 else "оставил"
        return "думает"
    if decided:
        return "готово"
    return "раздача"


def _is_back_only(cards: list[str]) -> bool:
    return bool(cards) and all(str(card) in {CARD_BACK, "back"} for card in cards)


def _hidden_card_line(cards: list[str]) -> str:
    return " ".join(CARD_BACK for _ in cards) if cards else "—"


def _card_text(
    table: dict[str, Any],
    *,
    result_text: str | None = None,
    fairness: str | None = None,
    reveal_streets: int | None = None,
    viewer_id: int | None = None,
) -> str:
    config = _game_config(table)
    state = _state(table)
    game_type = str(table.get("game_type"))
    hands = state.get("hands") if isinstance(state.get("hands"), dict) else {}
    if reveal_streets is not None:
        hands = visible_hands(hands, reveal_streets, game_type=game_type)
    decisions = _decisions_map(state)
    stood = _stood_seat_nos(state)
    roster = _table_seats(table)
    active = set(_active_seat_nos(state, roster))
    note = state.get("board_note") if isinstance(state.get("board_note"), str) else ""
    dealing = dealing_label(reveal_streets) if reveal_streets is not None else ""
    showdown = (
        _blackjack_showdown(table) if game_type == "blackjack" else
        str(table.get("status")) in SHOWDOWN_STATUSES
        or str(state.get("phase")) in {"scoring", "settled"}
        or result_text is not None
    )
    viewer = _as_telegram_id(viewer_id)
    private = viewer is not None
    rows: list[str] = []
    for seat in roster:
        if not isinstance(seat, dict):
            continue
        seat_no = int(seat["seat_no"])
        cards = _hand_list(hands, seat_no)
        decided = str(seat_no) in decisions or seat_no in stood
        hiding = reveal_streets is not None
        owner = _as_telegram_id(seat.get("telegram_id"))
        hide_holes = (
            game_type == "blackjack"
            and not showdown
            and (viewer is None or owner != viewer)
        )
        if hide_holes:
            card_line = _hidden_card_line(cards)
            score = "—"
        else:
            card_line = " ".join(cards) if cards else "—"
            score = "—" if hiding or not cards else f"{_seat_score(game_type, cards)}"
        status = "раздача" if hiding else _card_status(
            cards, decided=decided, active=seat_no in active, game_type=game_type,
        )
        rows.append(
            f"Место {seat_no} · {_seat_name(seat, table)}: <code>{card_line}</code> — <b>{score}</b> · {status}"
        )
    now = dealing or (PHASE_LABELS["hitting"] if game_type == "blackjack" and reveal_streets is None else PHASE_LABELS["dealing"])
    if note and reveal_streets is None:
        now = note
    if game_type == "blackjack" and reveal_streets is None:
        nxt = "Ждите итог." if showdown else "Нажмите «Взять карту» или «Оставить»."
        left = seconds_until(state.get("roll_deadline_at"))
        if not showdown and left is not None:
            nxt += f" До авто-«Оставить»: {left} сек."
    else:
        nxt = "Ждите итог." if game_type != "blackjack" or reveal_streets is not None else "Нажмите «Взять карту» или «Оставить»."
    footer = fairness
    if footer is None:
        url = verify_url(
            game_type=game_type,
            game_id=_table_id(table),
            commit=state.get("rng_commit") if isinstance(state.get("rng_commit"), str) else None,
            client_seed=state.get("client_seed") if isinstance(state.get("client_seed"), str) else None,
            nonce=state.get("nonce"),
        )
        if url:
            footer = f'<a href="{fairness_href(url)}">Проверить колоду после игры</a>'
        else:
            footer = "Колода зафиксирована. Проверка после игры: /casino/fairness"
    extra = [result_text] if result_text else []
    return render_board(
        header=f"{config['emoji']} <b>Стол #{fmt_id(_table_id(table))}</b> — {config['name']}",
        money=f"💰 Ставка: {table.get('stake_rub', '—')} ₽",
        subtitle=_card_rules(game_type, private=private and game_type == "blackjack"),
        roster=rows,
        now=now,
        nxt=nxt,
        extra=extra,
        footer=footer,
    )


def _hit_keyboard(table_id: str) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("🃏 Взять карту", callback_data=f"v2hit:{table_id}"),
        types.InlineKeyboardButton("🛑 Оставить", callback_data=f"v2stand:{table_id}"),
    )
    return keyboard


def _blackjack_open_dm_keyboard(table: dict[str, Any]) -> types.InlineKeyboardMarkup | None:
    url = blackjack_dm_start_url(_table_id(table))
    if not url:
        return None
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("Открыть личку и карты", url=url))
    return keyboard


def _humans_still_hitting(table: dict[str, Any]) -> bool:
    state = _state(table)
    decisions = _decisions_map(state)
    stood = _stood_seat_nos(state)
    active = set(_active_seat_nos(state, _table_seats(table)))
    return any(
        isinstance(seat, dict)
        and seat.get("participant_kind") == "player"
        and int(seat["seat_no"]) in active
        and str(seat["seat_no"]) not in decisions
        and int(seat["seat_no"]) not in stood
        for seat in _table_seats(table)
    )


def _card_keyboard(table: dict[str, Any], *, viewer_id: int | None = None) -> types.InlineKeyboardMarkup | None:
    if str(table.get("game_type")) != "blackjack":
        return None
    if _blackjack_showdown(table):
        return None
    state = _state(table)
    decisions = _decisions_map(state)
    stood = _stood_seat_nos(state)
    active = set(_active_seat_nos(state, _table_seats(table)))
    viewer = _as_telegram_id(viewer_id)
    if viewer is None:
        if not _humans_still_hitting(table):
            return None
        return _blackjack_open_dm_keyboard(table)
    seat = _seat_for_player(table, viewer)
    if seat is None:
        return _blackjack_open_dm_keyboard(table)
    seat_no = int(seat["seat_no"])
    if seat_no not in active or str(seat_no) in decisions or seat_no in stood:
        return None
    return _hit_keyboard(_table_id(table))


def _deal_actor(table: dict[str, Any], seat: dict[str, Any]) -> int:
    if seat.get("participant_kind") == "bot":
        return int(table.get("creator_id") or 0)
    return int(seat.get("telegram_id") or 0)


def _tie_round(state: dict[str, Any]) -> int:
    raw = state.get("tie_break_round")
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


async def _edit_board(
    bot: AsyncTeleBot,
    client,
    table: dict[str, Any],
    *,
    text: str | None = None,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    allow_resend: bool = True,
) -> dict[str, Any]:
    body = text if text is not None else _card_text(table)
    markup = reply_markup if reply_markup is not None else types.InlineKeyboardMarkup()
    chats = _play_chats(table)
    if not chats:
        return table
    updated: list[dict[str, Any]] = []
    changed = False
    for row in chats:
        chat_id = row.get("chat_id")
        if not isinstance(chat_id, int):
            continue
        nxt = dict(row)
        msg_id = row.get("card_msg_id")
        edited = False
        if isinstance(msg_id, int):
            try:
                await bot.edit_message_text(body, chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
                edited = True
            except Exception as exc:
                if "not modified" in str(exc).lower():
                    edited = True
                else:
                    logger.info("V2 board edit failed table=%s chat=%s", _table_id(table), chat_id, exc_info=True)
        if not edited:
            if not allow_resend:
                updated.append(nxt)
                continue
            old_id = nxt.get("card_msg_id") if isinstance(nxt.get("card_msg_id"), int) else None
            try:
                msg = await bot.send_message(chat_id, body, parse_mode="HTML", reply_markup=markup)
                nxt["card_msg_id"] = int(msg.message_id)
                if isinstance(old_id, int) and old_id != nxt["card_msg_id"]:
                    nxt["trash_msg_ids"] = normalize_msg_ids(list(nxt.get("trash_msg_ids") or []) + [old_id])
                changed = True
            except Exception:
                logger.exception("V2 board send failed table=%s chat=%s", _table_id(table), chat_id)
        updated.append(nxt)
    if not allow_resend:
        return table
    stored = _state(table).get("play_chats")
    need_persist = changed or not isinstance(stored, list) or updated != chats
    if need_persist:
        try:
            return await _persist(client, table, _play_state_patch(table, updated))
        except Exception:
            logger.exception("V2 board persist failed table=%s", _table_id(table))
            return table
    return table


async def _tick_edit_board(
    bot: AsyncTeleBot,
    table: dict[str, Any],
    *,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
) -> bool:
    """Edit live cards only. Never send a replacement message."""
    markup = reply_markup if reply_markup is not None else types.InlineKeyboardMarkup()
    chats = _play_chats(table)
    if not chats:
        return True
    failed = False
    for row in chats:
        chat_id = row.get("chat_id")
        msg_id = row.get("card_msg_id")
        if not isinstance(chat_id, int) or not isinstance(msg_id, int):
            failed = True
            continue
        try:
            await bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        except Exception as exc:
            if "not modified" in str(exc).lower():
                continue
            logger.info("V2 board tick edit failed table=%s chat=%s", _table_id(table), chat_id, exc_info=True)
            failed = True
    return not failed


async def _ensure_play_chat(bot: AsyncTeleBot, client, table: dict[str, Any], *, chat_id: int) -> dict[str, Any]:
    chats = _play_chats(table)
    existing = next((row for row in chats if row.get("chat_id") == chat_id), None)
    if existing and isinstance(existing.get("card_msg_id"), int):
        return table
    text = _play_surface_text(table)
    markup = _play_surface_markup(table)
    if markup is None:
        markup = types.InlineKeyboardMarkup()
    state = _state(table)
    listing_chat = state.get("listing_chat_id")
    listing_msg = state.get("listing_msg_id")
    msg_id: int | None = None
    if listing_chat == chat_id and isinstance(listing_msg, int):
        try:
            await bot.edit_message_text(text, chat_id, listing_msg, parse_mode="HTML", reply_markup=markup)
            msg_id = listing_msg
        except Exception as exc:
            if "not modified" in str(exc).lower():
                msg_id = listing_msg
            else:
                logger.info("V2 listing-to-board failed table=%s chat=%s", _table_id(table), chat_id, exc_info=True)
    if msg_id is None:
        try:
            msg = await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
            msg_id = int(msg.message_id)
        except Exception:
            logger.exception("V2 play-chat send failed table=%s chat=%s", _table_id(table), chat_id)
            return table
    chats = _upsert_play_chat(chats, chat_id=chat_id, card_msg_id=msg_id)
    try:
        return await _persist(client, table, _play_state_patch(table, chats))
    except Exception:
        logger.exception("V2 play-chat persist failed table=%s", _table_id(table))
        return table


async def _refresh_listing(bot: AsyncTeleBot, client, table: dict[str, Any]) -> dict[str, Any]:
    if _listing_converted_to_play(table):
        return table
    state = _state(table)
    listing_chat = state.get("listing_chat_id")
    listing_msg = state.get("listing_msg_id")
    if not isinstance(listing_chat, int) or not isinstance(listing_msg, int):
        return table
    _people, _bots, free = _seat_counts(table)
    if str(table.get("status")) != "open" or free <= 0:
        with contextlib.suppress(Exception):
            await bot.edit_message_text(
                "Стол заполнен. Игра идёт у участников.",
                listing_chat, listing_msg, parse_mode="HTML",
            )
        return table
    with contextlib.suppress(Exception):
        await bot.edit_message_text(
            _listing_text(table), listing_chat, listing_msg, parse_mode="HTML", reply_markup=_listing_keyboard(table),
        )
    return table


async def _maybe_announce_listing(bot: AsyncTeleBot, client, table: dict[str, Any]) -> dict[str, Any]:
    play_id = _chat_id(table)
    if not isinstance(play_id, int) or not _is_private_chat_id(play_id):
        return table
    if str(table.get("status")) != "open":
        return table
    _people, _bots, free = _seat_counts(table)
    if free <= 0:
        return table
    bound = await _bound_group_chat_id(client)
    if not isinstance(bound, int) or bound == play_id:
        return table
    try:
        msg = await bot.send_message(bound, _listing_text(table), parse_mode="HTML", reply_markup=_listing_keyboard(table))
    except Exception:
        logger.exception("Failed to announce V2 table in bound group table_id=%s", _table_id(table))
        return table
    try:
        return await _persist(client, table, {"listing_chat_id": bound, "listing_msg_id": int(msg.message_id)})
    except Exception:
        logger.exception("Failed to persist V2 listing table_id=%s", _table_id(table))
        return table


async def _persist_and_refresh(client, table: dict[str, Any], game_state: dict[str, Any]) -> dict[str, Any]:
    table = await _persist(client, table, game_state)
    return await _refresh(client, table)


async def _persist(client, table: dict[str, Any], game_state: dict[str, Any]) -> dict[str, Any]:
    result = await client.v2_table_operation(
        _table_id(table),
        "persist-state",
        expected_state_version=_version(table),
        game_state=game_state,
        idempotency_key=_idempotency("persist", _table_id(table), int(table.get("state_version") or 0)),
    )
    next_table = result.get("table") if isinstance(result, dict) else None
    if not isinstance(next_table, dict):
        raise ValueError("V2 persist-state did not return a table")
    remember_table(next_table)
    return next_table


async def _refresh(client, table: dict[str, Any]) -> dict[str, Any]:
    tables = await client.v2_tables_get("/v2/tables/active")
    items = tables.get("tables") if isinstance(tables, dict) else None
    if not isinstance(items, list):
        return table
    table_id = _table_id(table)
    for item in items:
        if isinstance(item, dict) and str(item.get("table_id")) == table_id:
            return item
    gone = dict(table)
    gone["status"] = GONE_STATUS
    return gone


def _stop_table_watchers(table_id: str) -> None:
    token = str(table_id or "")
    if not token:
        return
    for bucket in (_READY_WATCH, _ROLL_WATCH, _CARD_WATCH):
        entry = bucket.pop(token, None)
        if not isinstance(entry, dict):
            continue
        task = entry.get("task")
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()


async def publish_created_table(
    bot: AsyncTeleBot,
    client,
    table: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
    actor: Any | None = None,
    existing_message: tuple[int, int] | None = None,
) -> None:
    table = _apply_actor_roster(table, actor)
    chat_id = _chat_id(table)
    if chat_id is None:
        logger.warning("V2 table has no game chat table_id=%s", _table_id(table))
        return
    keyboard = _join_keyboard(table)
    text = _lobby_card_text(table)
    msg_id: int | None = None
    existing_chat = existing_message[0] if existing_message else None
    existing_mid = existing_message[1] if existing_message else None
    if existing_chat == chat_id and isinstance(existing_mid, int):
        try:
            await bot.edit_message_text(text, chat_id, existing_mid, parse_mode="HTML", reply_markup=keyboard)
            msg_id = existing_mid
        except Exception as exc:
            if "not modified" in str(exc).lower():
                msg_id = existing_mid
            else:
                logger.info("V2 reuse wizard card failed table=%s chat=%s", _table_id(table), chat_id, exc_info=True)
    if msg_id is None:
        try:
            msg = await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=keyboard)
            msg_id = int(msg.message_id)
        except Exception:
            logger.exception("Failed to publish V2 table card table_id=%s", _table_id(table))
            return
    patch: dict[str, Any] = {"chat_id": chat_id, "card_msg_id": int(msg_id)}
    chats = _upsert_play_chat(_play_chats(table), chat_id=chat_id, card_msg_id=int(msg_id))
    patch.update(_play_state_patch(table, chats))
    names = _roster_names(table)
    if names:
        patch["roster_names"] = names
    try:
        table = await _persist(client, table, patch)
    except Exception:
        logger.exception("Failed to persist V2 table card table_id=%s", _table_id(table))
    table = await _maybe_announce_listing(bot, client, table)
    status = str(table.get("status") or "")
    auto_started = bool(result and result.get("auto_started")) or status == "running"
    if status in {"running", "tie_break_running"}:
        await start_table_round(bot, client, table)
        return
    if status == "ready" or auto_started:
        _ensure_ready_watch(bot, client, table)


async def after_table_join(bot: AsyncTeleBot, client, result: dict[str, Any], *, join_chat_id: int | None = None, user: Any | None = None) -> None:
    table = result.get("table") if isinstance(result, dict) else None
    if not isinstance(table, dict):
        return
    table = await _refresh(client, table)
    if user is not None:
        identity = _identity_from_user(user)
        actor_id = getattr(user, "id", None)
        seat = _seat_for_player(table, actor_id) if isinstance(actor_id, int) and not isinstance(actor_id, bool) else None
        if seat and identity:
            try:
                table = await _persist(client, table, {
                    "roster_names": _merge_roster_name(table, seat_no=int(seat["seat_no"]), identity=identity),
                })
            except Exception:
                logger.exception("Failed to persist V2 roster name table_id=%s", _table_id(table))
    if isinstance(join_chat_id, int) and not isinstance(join_chat_id, bool):
        table = await _ensure_play_chat(bot, client, table, chat_id=join_chat_id)
    table = await _refresh_listing(bot, client, table)
    status = str(table.get("status") or "")
    if status in {"running", "tie_break_running"}:
        await start_table_round(bot, client, table)
        return
    await _edit_board(bot, client, table, text=_lobby_card_text(table), reply_markup=_join_keyboard(table))
    if status == "ready" or result.get("auto_started"):
        _ensure_ready_watch(bot, client, table)


def _ensure_ready_watch(bot: AsyncTeleBot, client, table: dict[str, Any]) -> None:
    table_id = _table_id(table)
    if not table_id:
        return
    remember_table(table)
    existing = _READY_WATCH.get(table_id)
    if isinstance(existing, dict):
        existing["table"] = table
        task = existing.get("task")
        if isinstance(task, asyncio.Task) and not task.done():
            return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    entry: dict[str, Any] = {"table": table, "task": None, "delayed_logged": False}
    entry["task"] = asyncio.create_task(
        _watch_ready_table(bot, client, table_id),
        name=f"v2-ready-{table_id}",
    )
    _READY_WATCH[table_id] = entry


async def _watch_ready_table(bot: AsyncTeleBot, client, table_id: str) -> None:
    try:
        while True:
            await asyncio.sleep(READY_TICK_INTERVAL)
            entry = _READY_WATCH.get(table_id)
            if not isinstance(entry, dict):
                return
            seed = entry.get("table")
            table = seed if isinstance(seed, dict) else {"table_id": table_id}
            table = await _refresh(client, table)
            remember_table(table)
            entry["table"] = table
            status = str(table.get("status") or "")
            if status != "ready":
                if status in {"running", "tie_break_running"}:
                    await start_table_round(bot, client, table)
                return
            starts = _parse_starts_at(_state(table))
            if starts is not None:
                lag = (_utc_now() - starts).total_seconds()
                if lag >= START_DELAY_GRACE_SECONDS and not entry.get("delayed_logged"):
                    logger.warning("V2 table start delayed table=%s lag=%.0fs", table_id, lag)
                    entry["delayed_logged"] = True
            if not await _tick_edit_board(
                bot,
                table,
                text=_lobby_card_text(table),
                reply_markup=_join_keyboard(table),
            ):
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("V2 ready watch failed table=%s", table_id)
    finally:
        current = asyncio.current_task()
        stored = _READY_WATCH.get(table_id)
        if isinstance(stored, dict) and stored.get("task") is current:
            _READY_WATCH.pop(table_id, None)


async def drain_ready_watchers() -> None:
    tasks: list[asyncio.Task] = []
    for bucket in (_READY_WATCH, _ROLL_WATCH, _CARD_WATCH):
        for entry in list(bucket.values()):
            if not isinstance(entry, dict):
                continue
            task = entry.get("task")
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()
                tasks.append(task)
        bucket.clear()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


def _reveal_key(table_id: str) -> str:
    return f"v2-reveal:{table_id}"


def _score_key(table_id: str) -> str:
    return f"v2-score:{table_id}"


async def start_card_reveal(
    bot: AsyncTeleBot,
    client,
    table: dict[str, Any],
    *,
    from_street: int = 1,
    restart: bool = False,
    allow_resend: bool = True,
) -> None:
    table_id = _table_id(table)
    if not table_id:
        return
    remember_table(table)
    hands = _state(table).get("hands") if isinstance(_state(table).get("hands"), dict) else {}
    game_type = str(table.get("game_type"))
    streets = street_count(hands, game_type=game_type)
    if streets <= 0:
        return
    key = _reveal_key(table_id)
    if is_running(key) and not restart:
        return

    snapshot = dict(table)
    snapshot_state = dict(_state(table))
    hands = snapshot_state.get("hands")
    if isinstance(hands, dict):
        snapshot_state["hands"] = {
            str(seat): list(cards) if isinstance(cards, list) else cards for seat, cards in hands.items()
        }
    snapshot["game_state"] = snapshot_state

    if game_type == "baccara":
        await _edit_board(
            bot,
            client,
            snapshot,
            text=_card_text(snapshot),
            reply_markup=types.InlineKeyboardMarkup(),
            allow_resend=allow_resend,
        )
        return

    def _street_fn(street: int):
        async def _edit() -> None:
            await _edit_board(
                bot,
                client,
                snapshot,
                text=_card_text(snapshot, reveal_streets=street),
                reply_markup=types.InlineKeyboardMarkup(),
                allow_resend=allow_resend,
            )

        return _edit

    async def _full() -> None:
        await _edit_board(
            bot, client, snapshot, reply_markup=_card_keyboard(snapshot), allow_resend=allow_resend,
        )

    beats = [(_street_fn(street), STREET_PAUSE_SECONDS, f"dealing_{street}") for street in range(from_street, streets + 1)]
    beats.append((_full, RESULT_BEAT_SECONDS, "scoring"))
    await run_beats(key, beats, restart=restart)


def _ensure_roll_watch(bot: AsyncTeleBot, client, table: dict[str, Any]) -> None:
    table_id = _table_id(table)
    if not table_id or _is_card_table(table):
        return
    if str(table.get("status") or "") not in {"running", "tie_break_running"}:
        return
    remember_table(table)
    existing = _ROLL_WATCH.get(table_id)
    if isinstance(existing, dict):
        existing["table"] = table
        task = existing.get("task")
        if isinstance(task, asyncio.Task) and not task.done():
            return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    entry: dict[str, Any] = {"table": table, "task": None}
    entry["task"] = asyncio.create_task(_watch_roll_table(bot, client, table_id), name=f"v2-roll-{table_id}")
    _ROLL_WATCH[table_id] = entry


async def _watch_roll_table(bot: AsyncTeleBot, client, table_id: str) -> None:
    try:
        while True:
            await asyncio.sleep(READY_TICK_INTERVAL)
            entry = _ROLL_WATCH.get(table_id)
            if not isinstance(entry, dict):
                return
            seed = entry.get("table")
            table = seed if isinstance(seed, dict) else {"table_id": table_id}
            table = await _refresh(client, table)
            remember_table(table)
            entry["table"] = table
            status = str(table.get("status") or "")
            if status not in {"running", "tie_break_running"}:
                return
            state = _state(table)
            required = _required_rolls(table)
            roster = _table_seats(table)
            if all_rolls_complete(
                state.get("rolls") if isinstance(state.get("rolls"), dict) else {},
                _active_seat_nos(state, roster),
                required,
            ):
                return
            if not await _tick_edit_board(
                bot, table, text=_roll_text(table), reply_markup=types.InlineKeyboardMarkup(),
            ):
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("V2 roll watch failed table=%s", table_id)
    finally:
        current = asyncio.current_task()
        stored = _ROLL_WATCH.get(table_id)
        if isinstance(stored, dict) and stored.get("task") is current:
            _ROLL_WATCH.pop(table_id, None)


def _card_fingerprint(table: dict[str, Any]) -> tuple[Any, ...]:
    state = _state(table)
    hands = state.get("hands") if isinstance(state.get("hands"), dict) else {}
    packed = tuple(
        (str(seat), tuple(str(card) for card in (cards or []) if card))
        for seat, cards in sorted(hands.items(), key=lambda item: str(item[0]))
        if isinstance(cards, list)
    )
    try:
        round_no = int(state.get("tie_break_round") or 0)
    except (TypeError, ValueError):
        round_no = 0
    return (
        str(table.get("status") or ""),
        str(state.get("cards_dealt_at") or ""),
        str(state.get("roll_deadline_at") or ""),
        str(state.get("blackjack_reminder_deadline_at") or ""),
        round_no,
        packed,
    )


async def _maybe_send_blackjack_reminder(bot: AsyncTeleBot, client, table: dict[str, Any]) -> dict[str, Any]:
    if not _is_blackjack(table) or str(table.get("status") or "") not in PLAY_STATUSES:
        return table
    state = _state(table)
    deadline = str(state.get("roll_deadline_at") or "")
    left = seconds_until(deadline)
    if not deadline or left is None or left <= 0 or left > BLACKJACK_REMINDER_SECONDS:
        return table
    if str(state.get("blackjack_reminder_deadline_at") or "") == deadline:
        return table
    if table.get("dm_unavailable_fallback_sent_at") == deadline:
        return table
    stood = _stood_seat_nos(state)
    decisions = _decisions_map(state)
    active = set(_active_seat_nos(state, _table_seats(table)))
    recipients = [
        tid
        for seat in _table_seats(table)
        if isinstance(seat, dict)
        and seat.get("participant_kind") == "player"
        and int(seat.get("seat_no") or 0) in active
        and int(seat.get("seat_no") or 0) not in stood
        and str(seat.get("seat_no")) not in decisions
        and (tid := _as_telegram_id(seat.get("telegram_id"))) is not None
    ]
    if not recipients:
        return table
    try:
        # Durable claim first: a restart or a second worker cannot duplicate the reminder.
        table = await _persist(client, table, {"blackjack_reminder_deadline_at": deadline})
    except Exception:
        logger.info("V2 BJ reminder already claimed or table changed table=%s", _table_id(table))
        return table
    chat_id = _chat_id(table)
    delivered: list[int] = []
    blocked: list[int] = []
    for telegram_id in recipients:
        try:
            await bot.send_message(
                telegram_id,
                f"⏳ Blackjack: осталось около {left} сек. Если не выбрать действие, будет автоматически «Оставить».",
            )
        except Exception as exc:
            if _telegram_cannot_dm(exc):
                blocked.append(telegram_id)
            else:
                logger.info("V2 BJ reminder delivery failed table=%s user=%s", _table_id(table), telegram_id)
        else:
            delivered.append(telegram_id)
    if blocked and chat_id is not None:
        try:
            names = ", ".join(
                str(_seat_name(seat, table)).lstrip("@")
                for telegram_id in blocked
                for seat in (_seat_for_player(table, telegram_id),)
                if isinstance(seat, dict)
            ) or "игрок"
            await bot.send_message(
                chat_id,
                f"⏳ {names}: ход ждёт в личке игрового бота — откройте её и нажмите /start, иначе через ~{left} сек будет «Оставить».",
            )
            table = dict(table)
            table["dm_unavailable_fallback_sent_at"] = deadline
        except Exception:
            logger.info("V2 BJ reminder group fallback failed table=%s", _table_id(table))
    return table


def _ensure_card_watch(bot: AsyncTeleBot, client, table: dict[str, Any]) -> None:
    table_id = _table_id(table)
    if not table_id or not _is_card_table(table):
        return
    remember_table(table)
    existing = _CARD_WATCH.get(table_id)
    if isinstance(existing, dict):
        existing["table"] = table
        existing["fingerprint"] = _card_fingerprint(table)
        task = existing.get("task")
        if isinstance(task, asyncio.Task) and not task.done():
            return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    entry: dict[str, Any] = {"table": table, "fingerprint": _card_fingerprint(table), "task": None}
    entry["task"] = asyncio.create_task(_watch_card_table(bot, client, table_id), name=f"v2-card-{table_id}")
    _CARD_WATCH[table_id] = entry


async def _watch_card_table(bot: AsyncTeleBot, client, table_id: str) -> None:
    try:
        while True:
            await asyncio.sleep(READY_TICK_INTERVAL)
            entry = _CARD_WATCH.get(table_id)
            if not isinstance(entry, dict):
                return
            seed = entry.get("table")
            table = seed if isinstance(seed, dict) else {"table_id": table_id}
            table = await _refresh(client, table)
            remember_table(table)
            table = await _maybe_send_blackjack_reminder(bot, client, table)
            entry["table"] = table
            status = str(table.get("status") or "")
            if status not in {"running", "tie_break_running"}:
                return
            fingerprint = _card_fingerprint(table)
            if fingerprint == entry.get("fingerprint"):
                continue
            entry["fingerprint"] = fingerprint
            await start_card_reveal(bot, client, table, restart=True, allow_resend=False)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("V2 card watch failed table=%s", table_id)
    finally:
        current = asyncio.current_task()
        stored = _CARD_WATCH.get(table_id)
        if isinstance(stored, dict) and stored.get("task") is current:
            _CARD_WATCH.pop(table_id, None)


async def start_table_round(bot: AsyncTeleBot, client, table: dict[str, Any]) -> None:
    table = await _refresh(client, table)
    if str(table.get("status")) not in {"running", "tie_break_running"}:
        return
    state = _state(table)
    if state.get("phase") in {"rolling", "tie_break", "cards"} and (state.get("roll_msg_id") or state.get("hands")):
        if _is_card_table(table):
            await _continue_cards(bot, client, table)
        else:
            await _roll_bots(bot, client, table)
        return
    roster = _table_seats(table)
    seat_nos = [int(seat["seat_no"]) for seat in roster]
    chat_id = _chat_id(table)
    init = {
        "seat_nos": seat_nos,
        "phase": "cards" if _is_card_table(table) else "rolling",
        "rolls": state.get("rolls") or {},
        "rounds": _required_rolls(table),
        "draw_policy": _draw_policy(state),
        "chat_id": chat_id,
    }
    table = await _persist(client, table, init)
    if _is_card_table(table):
        await _deal_initial_cards(bot, client, table)
        return
    await _prompt_rolls(bot, client, table)


async def _prompt_rolls(bot: AsyncTeleBot, client, table: dict[str, Any]) -> None:
    chats = _play_chats(table)
    if not chats:
        chat_id = _chat_id(table)
        if not isinstance(chat_id, int):
            logger.warning("V2 roll prompt skipped, no chat table=%s", _table_id(table))
            return
        chats = [{"chat_id": chat_id, "card_msg_id": None, "roll_msg_id": None, "trash_msg_ids": []}]
    updated = [dict(row) for row in chats]
    body = _roll_text(table)
    changed = False
    for row in list(updated):
        chat_id = row.get("chat_id")
        if not isinstance(chat_id, int):
            continue
        card_id = row.get("card_msg_id") if isinstance(row.get("card_msg_id"), int) else None
        roll_id = row.get("roll_msg_id") if isinstance(row.get("roll_msg_id"), int) else None
        target = card_id if card_id is not None else roll_id
        edited = False
        if isinstance(target, int):
            try:
                await bot.edit_message_text(body, chat_id, target, parse_mode="HTML")
                edited = True
            except Exception as exc:
                if "not modified" in str(exc).lower():
                    edited = True
                else:
                    logger.info("V2 roll prompt edit failed table=%s chat=%s", _table_id(table), chat_id, exc_info=True)
        if edited and isinstance(target, int):
            _index_roll_prompt(_table_id(table), chat_id, target)
            continue
        try:
            msg = await bot.send_message(chat_id, body, parse_mode="HTML")
        except Exception:
            logger.exception("V2 roll prompt failed table=%s chat=%s", _table_id(table), chat_id)
            continue
        new_id = int(msg.message_id)
        updated = _upsert_play_chat(updated, chat_id=chat_id, card_msg_id=new_id)
        if isinstance(card_id, int) and card_id != new_id:
            updated = add_trash(updated, chat_id=chat_id, message_id=card_id)
        if isinstance(roll_id, int) and roll_id not in {new_id, card_id}:
            updated = add_trash(updated, chat_id=chat_id, message_id=roll_id)
        _index_roll_prompt(_table_id(table), chat_id, new_id)
        changed = True
    if changed:
        try:
            table = await _persist(client, table, _play_state_patch(table, updated))
        except Exception:
            logger.exception("V2 roll prompt persist failed table=%s", _table_id(table))
            return
    _ensure_roll_watch(bot, client, table)


def _dice_reply_target(table: dict[str, Any]) -> tuple[int, int | None] | None:
    primary = _chat_id(table)
    chats = _play_chats(table)

    def _prefer(row: dict[str, Any]) -> tuple[int, int | None] | None:
        chat_id = row.get("chat_id")
        if not isinstance(chat_id, int):
            return None
        card_id = row.get("card_msg_id") if isinstance(row.get("card_msg_id"), int) else None
        roll_id = row.get("roll_msg_id") if isinstance(row.get("roll_msg_id"), int) else None
        target = card_id if card_id is not None else roll_id
        return chat_id, target

    for row in chats:
        if row.get("chat_id") == primary:
            found = _prefer(row)
            if found is not None:
                return found
    for row in chats:
        found = _prefer(row)
        if found is not None:
            return found
    if isinstance(primary, int):
        return primary, None
    return None


def _missing_roll_index(state: dict[str, Any], seat_no: int, required: int) -> int | None:
    rolls = state.get("rolls") if isinstance(state.get("rolls"), dict) else {}
    for index in range(required):
        if f"s{seat_no}r{index}" not in rolls:
            return index
    return None


def _table_roll_lock(table_id: str) -> asyncio.Lock:
    return _table_roll_locks.setdefault(table_id, asyncio.Lock())


def _humans_complete_index(table: dict[str, Any], state: dict[str, Any], index: int, active: set[int]) -> bool:
    rolls = state.get("rolls") if isinstance(state.get("rolls"), dict) else {}
    for seat in _table_seats(table):
        if not isinstance(seat, dict) or seat.get("participant_kind") != "player":
            continue
        try:
            seat_no = int(seat["seat_no"])
        except (TypeError, ValueError, KeyError):
            continue
        if seat_no not in active:
            continue
        if f"s{seat_no}r{index}" not in rolls:
            return False
    return True


async def _roll_bots(bot: AsyncTeleBot, client, table: dict[str, Any], *, locked: bool = False) -> None:
    if not locked:
        async with _table_roll_lock(_table_id(table)):
            await _roll_bots(bot, client, table, locked=True)
        return
    table = await _refresh(client, table)
    state = _state(table)
    required = _required_rolls(table)
    emoji = emoji_for_canonical(str(table.get("game_type")))
    target = _dice_reply_target(table)
    if target is None:
        return
    chat_id, roll_msg_id = target
    active = set(_active_seat_nos(state, _table_seats(table)))
    for seat in _bot_seats(table):
        seat_no = int(seat["seat_no"])
        if seat_no not in active:
            continue
        while True:
            table = await _refresh(client, table)
            state = _state(table)
            if str(table.get("status")) not in {"running", "tie_break_running"}:
                return
            index = _missing_roll_index(state, seat_no, required)
            if index is None:
                break
            if not _humans_complete_index(table, state, index, active):
                break
            try:
                await wait_dice_landed()
                table = await _refresh(client, table)
                state = _state(table)
                if str(table.get("status")) not in {"running", "tie_break_running"}:
                    return
                if _missing_roll_index(state, seat_no, required) != index:
                    continue
                if not _humans_complete_index(table, state, index, active):
                    break
                send_kwargs: dict[str, Any] = {"chat_id": chat_id, "emoji": emoji}
                if isinstance(roll_msg_id, int):
                    send_kwargs["reply_to_message_id"] = roll_msg_id
                dice = await bot.send_dice(**send_kwargs)
                value = int(getattr(getattr(dice, "dice", None), "value", 0) or 0)
                dice_mid = getattr(dice, "message_id", None)
                await wait_dice_landed()
            except Exception:
                logger.exception("V2 bot dice failed table=%s seat=%s", _table_id(table), seat_no)
                break
            table = await _record_roll(
                bot, client, table, seat_no=seat_no, value=value,
                trash_chat_id=chat_id,
                trash_msg_id=int(dice_mid) if isinstance(dice_mid, int) and not isinstance(dice_mid, bool) else None,
            )
            if str(table.get("status")) not in {"running", "tie_break_running"}:
                return
            if _missing_roll_index(_state(table), seat_no, required) == index:
                logger.warning("V2 bot roll did not persist table=%s seat=%s", _table_id(table), seat_no)
                break


async def _record_roll(
    bot: AsyncTeleBot,
    client,
    table: dict[str, Any],
    *,
    seat_no: int,
    value: int,
    trash_chat_id: int | None = None,
    trash_msg_id: int | None = None,
) -> dict[str, Any]:
    state = _state(table)
    required = _required_rolls(table)
    index = _missing_roll_index(state, seat_no, required)
    if index is None:
        return table
    try:
        next_state = apply_roll(state, seat_no=seat_no, roll_index=index, value=value, required_rolls=required)
    except ValueError:
        return table
    patch: dict[str, Any] = {"rolls": next_state["rolls"], "phase": next_state["phase"]}
    if isinstance(trash_chat_id, int) and not isinstance(trash_chat_id, bool) and isinstance(trash_msg_id, int) and not isinstance(trash_msg_id, bool):
        patch.update(_play_state_patch(table, add_trash(_play_chats(table), chat_id=trash_chat_id, message_id=trash_msg_id)))
    table = await _persist(client, table, patch)
    seen: set[tuple[int, int]] = set()
    for row in _play_chats(table):
        chat_id = row.get("chat_id")
        if not isinstance(chat_id, int):
            continue
        for mid in (row.get("card_msg_id"), row.get("roll_msg_id")):
            if not isinstance(mid, int) or (chat_id, mid) in seen:
                continue
            seen.add((chat_id, mid))
            with contextlib.suppress(Exception):
                await bot.edit_message_text(_roll_text(table), chat_id, mid, parse_mode="HTML")
    return await _maybe_score_dice(bot, client, table)


async def _maybe_score_dice(bot: AsyncTeleBot, client, table: dict[str, Any]) -> dict[str, Any]:
    state = _state(table)
    required = _required_rolls(table)
    roster = _table_seats(table)
    seat_nos = _active_seat_nos(state, roster)
    rolls = state.get("rolls") if isinstance(state.get("rolls"), dict) else {}
    if not all_rolls_complete(rolls, seat_nos, required):
        return table
    table_id = _table_id(table)
    _stop_table_watchers(table_id)
    key = _score_key(table_id)

    async def _scoring() -> None:
        fresh = await _refresh(client, table)
        if str(fresh.get("status") or "") not in {"running", "tie_break_running"}:
            return
        await _edit_board(
            bot, client, fresh, text=_roll_text(fresh, scoring=True),
            reply_markup=types.InlineKeyboardMarkup(), allow_resend=False,
        )

    await run_beats(key, [(_scoring, SCORE_BEAT_SECONDS, "scoring")], restart=True)
    await wait_drama(key, timeout=max(5.0, SCORE_BEAT_SECONDS + 3))
    table = await _refresh(client, table)
    if str(table.get("status") or "") not in {"running", "tie_break_running"}:
        return table
    state = _state(table)
    rolls = state.get("rolls") if isinstance(state.get("rolls"), dict) else {}
    totals = seat_totals(rolls, seat_nos, required)
    leaders = leader_seat_nos(totals)
    if len(leaders) == 1:
        return await _commit_settle(bot, client, table, kind="winner", winner_seat_nos=leaders)
    if _draw_policy(state) == "tie_split":
        return await _commit_settle(bot, client, table, kind="tie_split", winner_seat_nos=leaders)
    committed = await client.v2_table_operation(
        _table_id(table), "commit-outcome",
        expected_state_version=_version(table),
        outcome_kind="tie_break",
        winner_seat_nos=leaders,
        idempotency_key=_idempotency("tiebreak", _table_id(table), _version(table)),
    )
    table = committed.get("table") if isinstance(committed, dict) else table
    if not isinstance(table, dict):
        return table
    cleared = tie_break_state(_state(table), leaders)
    table = await _persist(client, table, {
        "phase": "tie_break",
        "rolls": cleared.get("rolls") or {},
        "tie_break_seat_nos": leaders,
        "tie_break_round": cleared.get("tie_break_round"),
    })
    await _prompt_rolls(bot, client, table)
    return table


async def publish_settled_table(
    bot: AsyncTeleBot,
    client,
    table: dict[str, Any],
    payload: dict[str, Any],
    *,
    seed: str | None = None,
) -> dict[str, Any]:
    table_id = _table_id(table)
    _stop_table_watchers(table_id)
    await wait_drama(_reveal_key(table_id), REVEAL_HOLD_SECONDS)
    await wait_drama(_score_key(table_id), max(5.0, SCORE_BEAT_SECONDS + 3))
    if not try_mark_finalized(table_id):
        return table
    table = await _annotate_roster_names(bot, table)
    text = format_v2_settlement(payload, table=table)
    if _is_card_table(table):
        text = _card_text(table, result_text=text)
    markup = _result_keyboard(table, seed=seed)
    destinations = result_chat_ids(table)
    if not destinations:
        chat_id = _chat_id(table)
        if isinstance(chat_id, int):
            destinations = [chat_id]
    for chat_id in destinations:
        try:
            sent = await bot.send_message(
                chat_id,
                text,
                parse_mode="HTML",
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            track_group_result(chat_id, sent)
        except Exception:
            logger.exception("V2 result send failed table=%s chat=%s", _table_id(table), chat_id)
    card_ids: set[tuple[int, int]] = set()
    for row in _play_chats(table):
        chat_id = row.get("chat_id")
        mid = row.get("card_msg_id")
        if isinstance(chat_id, int) and isinstance(mid, int):
            card_ids.add((chat_id, mid))
    listing_chat = _state(table).get("listing_chat_id")
    listing_msg = _state(table).get("listing_msg_id")
    if isinstance(listing_chat, int) and isinstance(listing_msg, int):
        card_ids.add((listing_chat, listing_msg))
    for chat_id, msg_id in collect_trash(table):
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            logger.warning(
                "V2 delete failed table=%s chat=%s msg=%s",
                _table_id(table), chat_id, msg_id, exc_info=True,
            )
            if (chat_id, msg_id) in card_ids:
                with contextlib.suppress(Exception):
                    await bot.edit_message_text(
                        text, chat_id, msg_id, parse_mode="HTML", reply_markup=markup,
                    )
    forget_table(_table_id(table))
    return table


async def after_table_cancelled(
    bot: AsyncTeleBot,
    client,
    table: dict[str, Any] | None,
    *,
    origin: tuple[int, int] | None = None,
    table_id: str | None = None,
) -> None:
    await discard_table_cards(bot, table, origin=origin, table_id=table_id)


def _cleanup_table(table: dict[str, Any] | None, table_id: str | None) -> dict[str, Any]:
    source = table if isinstance(table, dict) else {}
    token = str(table_id or _table_id(source) or "")
    remembered = recall_table(token) if token else None
    if not isinstance(remembered, dict):
        return source
    merged = dict(remembered)
    merged.update({key: value for key, value in source.items() if value is not None})
    state = dict(_state(remembered))
    state.update(_state(source))
    merged["game_state"] = state
    if token:
        merged["table_id"] = token
    return merged


def _origin_pair(origin: tuple[int, int] | None) -> tuple[int, int] | None:
    if not origin:
        return None
    chat_id, msg_id = origin
    if isinstance(chat_id, int) and not isinstance(chat_id, bool) and isinstance(msg_id, int) and not isinstance(msg_id, bool):
        return (chat_id, msg_id)
    return None


async def discard_table_cards(
    bot: AsyncTeleBot,
    table: dict[str, Any] | None = None,
    *,
    origin: tuple[int, int] | None = None,
    table_id: str | None = None,
) -> None:
    token = str(table_id or (_table_id(table) if isinstance(table, dict) else "") or "")
    extra = _origin_pair(origin)
    if token and already_finalized(token) and extra is None:
        return
    source = _cleanup_table(table, token or None)
    if token:
        _stop_table_watchers(token)
        try_mark_finalized(token)
    pairs = set(collect_trash(source))
    if extra is not None:
        pairs.add(extra)
    for chat_id, msg_id in pairs:
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            logger.warning(
                "V2 cancel delete failed table=%s chat=%s msg=%s",
                token, chat_id, msg_id, exc_info=True,
            )
            with contextlib.suppress(Exception):
                await bot.edit_message_text("Стол отменён.", chat_id, msg_id, parse_mode="HTML")
    if token:
        forget_table(token)


async def _commit_settle(bot: AsyncTeleBot, client, table: dict[str, Any], *, kind: str, winner_seat_nos: list[int]) -> dict[str, Any]:
    committed = await client.v2_table_operation(
        _table_id(table), "commit-outcome",
        expected_state_version=_version(table),
        outcome_kind=kind,
        winner_seat_nos=winner_seat_nos,
        idempotency_key=_idempotency("commit", _table_id(table), _version(table)),
    )
    table = committed.get("table") if isinstance(committed, dict) else table
    if not isinstance(table, dict):
        return table
    settled = await client.v2_table_operation(
        _table_id(table), "settle-committed-outcome",
        expected_state_version=_version(table),
        idempotency_key=_idempotency("settle", _table_id(table), _version(table)),
    )
    payload = settled if isinstance(settled, dict) else {}
    seed = None
    if _is_card_table(table):
        creator_id = int(table.get("creator_id") or 0)
        if creator_id:
            with contextlib.suppress(Exception):
                revealed = await client.v2_table_cards(_table_id(table), "reveal", telegram_id=creator_id)
                seed = revealed.get("rng_seed") if isinstance(revealed, dict) else None
    return await publish_settled_table(
        bot, client, table, payload,
        seed=seed if isinstance(seed, str) else None,
    )


def _table_in_chat(table: dict[str, Any], chat_id: int) -> bool:
    if _chat_id(table) == chat_id:
        return True
    return any(row.get("chat_id") == chat_id for row in _play_chats(table))


def _dice_table_for_player(
    items: list[Any], *, actor_id: int, chat_id: int, emoji: str | None = None,
) -> dict[str, Any] | None:
    seated: list[dict[str, Any]] = []
    needing: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("status")) not in {"running", "tie_break_running"}:
            continue
        if _is_card_table(item):
            continue
        if not _table_in_chat(item, chat_id):
            continue
        if emoji and emoji_for_canonical(str(item.get("game_type"))) != emoji:
            continue
        seat = _seat_for_player(item, actor_id)
        if seat is None:
            continue
        seated.append(item)
        missing = _missing_roll_index(_state(item), int(seat["seat_no"]), _required_rolls(item))
        if missing is not None:
            needing.append(item)
    pool = needing or seated
    return pool[0] if pool else None


async def try_handle_v2_dice(bot: AsyncTeleBot, client, message: Any) -> bool:
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    reply = getattr(message, "reply_to_message", None)
    reply_id = getattr(reply, "message_id", None)
    actor = getattr(message, "from_user", None)
    actor_id = getattr(actor, "id", None)
    dice = getattr(message, "dice", None)
    if getattr(actor, "is_bot", False):
        return True
    if not isinstance(chat_id, int) or not isinstance(actor_id, int) or dice is None:
        return False
    try:
        tables = await client.v2_tables_get("/v2/tables/active")
    except Exception:
        return False
    items = tables.get("tables") if isinstance(tables, dict) else []
    if not isinstance(items, list):
        items = []
    table_id = _roll_index.get((chat_id, reply_id)) if isinstance(reply_id, int) else None
    table = None
    if table_id:
        table = next((item for item in items if isinstance(item, dict) and str(item.get("table_id")) == table_id), None)
    if table is None and isinstance(reply_id, int):
        for item in items:
            if not isinstance(item, dict):
                continue
            matched = False
            for row in _play_chats(item):
                if row.get("chat_id") == chat_id and reply_id in {
                    row.get("roll_msg_id"), row.get("card_msg_id"),
                }:
                    matched = True
                    break
            if matched:
                table = item
                table_id = _table_id(item)
                _index_roll_prompt(table_id, chat_id, reply_id)
                break
    if table is not None and _seat_for_player(table, actor_id) is None:
        table = None
        table_id = None
    if table is None:
        table = _dice_table_for_player(
            items, actor_id=actor_id, chat_id=chat_id, emoji=getattr(dice, "emoji", None),
        )
        if table is not None:
            table_id = _table_id(table)
    if not table_id or table is None:
        return False
    if str(table.get("status")) not in {"running", "tie_break_running"}:
        return True
    if _is_card_table(table):
        return True
    expected = emoji_for_canonical(str(table.get("game_type")))
    if getattr(dice, "emoji", None) != expected:
        await bot.reply_to(message, f"❌ Для этой игры нужен бросок {expected}.")
        return True
    seat = _seat_for_player(table, actor_id)
    if seat is None:
        await bot.reply_to(message, "❌ Бросок могут сделать только участники этого стола.")
        return True
    state = _state(table)
    active = set(_active_seat_nos(state, _table_seats(table)))
    if int(seat["seat_no"]) not in active:
        await bot.reply_to(message, "❌ Сейчас бросают только лидеры.")
        return True
    async with _table_roll_lock(table_id):
        table = await _refresh(client, table)
        if str(table.get("status")) not in {"running", "tie_break_running"}:
            return True
        seat = _seat_for_player(table, actor_id)
        if seat is None or int(seat["seat_no"]) not in set(_active_seat_nos(_state(table), _table_seats(table))):
            return True
        if _missing_roll_index(_state(table), int(seat["seat_no"]), _required_rolls(table)) is None:
            return True
        dice_mid = getattr(message, "message_id", None)
        table = await _record_roll(
            bot, client, table, seat_no=int(seat["seat_no"]), value=int(getattr(dice, "value", 0) or 0),
            trash_chat_id=chat_id if isinstance(dice_mid, int) and not isinstance(dice_mid, bool) else None,
            trash_msg_id=dice_mid if isinstance(dice_mid, int) and not isinstance(dice_mid, bool) else None,
        )
        if str(table.get("status")) in {"running", "tie_break_running"}:
            await _roll_bots(bot, client, table, locked=True)
    return True


def _shoe_side(seat_no: int, *, tie_round: int = 0) -> str:
    if tie_round:
        return f"seat{seat_no}_tb{tie_round}"
    return f"seat{seat_no}"


def _hand_list(hands: dict[str, Any], seat_no: int) -> list[str]:
    raw = hands.get(str(seat_no), hands.get(seat_no))
    return list(raw) if isinstance(raw, list) else []


def bj_best_score(cards: list[str]) -> int:
    total = 0
    aces = 0
    for card in cards:
        rank = str(card)[:-1]
        if rank == "A":
            aces += 1
            total += 11
        elif rank in {"10", "J", "Q", "K"}:
            total += 10
        else:
            try:
                total += int(rank)
            except ValueError:
                continue
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def _seat_score(game_type: str, cards: list[str]) -> int:
    if game_type == "blackjack":
        score = bj_best_score(cards)
        return 0 if score > 21 else score
    return bak_hand_score(cards)


async def _deal_initial_cards(bot: AsyncTeleBot, client, table: dict[str, Any]) -> None:
    table = await _refresh(client, table)
    state = _state(table)
    existing_hands = state.get("hands") if isinstance(state.get("hands"), dict) else {}
    if existing_hands and state.get("cards_dealt_at"):
        await start_card_reveal(bot, client, table)
        await _prompt_card_actions(bot, client, table)
        return
    creator_id = int(table.get("creator_id") or 0)
    table_id = _table_id(table)
    prepared = await client.v2_table_cards(table_id, "prepare", telegram_id=creator_id, game_type=str(table.get("game_type")))
    table = await _persist_and_refresh(client, table, {
        "rng_commit": prepared.get("rng_commit"),
        "client_seed": prepared.get("client_seed"),
        "nonce": prepared.get("nonce"),
        "hands": {},
        "decisions": {},
        "phase": "cards",
        "board_note": "",
    })
    hands: dict[str, list[str]] = {}
    round_no = _tie_round(_state(table))
    for seat in _table_seats(table):
        seat_no = int(seat["seat_no"])
        dealt = await client.v2_table_cards(
            table_id, "deal", telegram_id=_deal_actor(table, seat), hand_size=2, seat_no=seat_no,
            shoe_side=_shoe_side(seat_no, tie_round=round_no),
        )
        cards = dealt.get("cards") if isinstance(dealt, dict) else []
        hands[str(seat_no)] = list(cards) if isinstance(cards, list) else []
    table = await _persist_and_refresh(client, table, {"hands": hands, "decisions": {}})
    await start_card_reveal(bot, client, table)
    await wait_drama(_reveal_key(table_id), REVEAL_HOLD_SECONDS)
    await _prompt_card_actions(bot, client, table)


async def _prompt_card_actions(bot: AsyncTeleBot, client, table: dict[str, Any]) -> None:
    table = await _refresh(client, table)
    game_type = str(table.get("game_type"))
    state = _state(table)
    hands = dict(state.get("hands") or {}) if isinstance(state.get("hands"), dict) else {}
    decisions = dict(state.get("decisions") or {})
    roster = _table_seats(table)
    active = set(_active_seat_nos(state, roster))
    round_no = _tie_round(state)
    if game_type == "baccara":
        if state.get("cards_dealt_at"):
            await start_card_reveal(bot, client, table)
            _ensure_card_watch(bot, client, table)
            return
        grew = False
        for seat in roster:
            seat_no = int(seat["seat_no"])
            if seat_no not in active:
                continue
            cards = _hand_list(hands, seat_no)
            if bak_hand_score(cards) <= 5 and len(cards) < 3:
                dealt = await client.v2_table_cards(
                    _table_id(table), "deal", telegram_id=_deal_actor(table, seat), hand_size=3, seat_no=seat_no,
                    shoe_side=_shoe_side(seat_no, tie_round=round_no),
                )
                cards = dealt.get("cards") if isinstance(dealt, dict) else cards
                nxt = list(cards) if isinstance(cards, list) else cards
                if nxt != _hand_list(hands, seat_no):
                    grew = True
                hands[str(seat_no)] = nxt
            decisions[str(seat_no)] = "stand"
        table = await _persist_and_refresh(client, table, {"hands": hands, "decisions": decisions})
        if grew:
            await start_card_reveal(bot, client, table, from_street=3, restart=True)
            await wait_drama(_reveal_key(_table_id(table)), REVEAL_HOLD_SECONDS)
        await _score_cards(bot, client, table)
        return
    await wait_drama(_reveal_key(_table_id(table)), REVEAL_HOLD_SECONDS)
    for seat in roster:
        seat_no = int(seat["seat_no"])
        if seat_no not in active or str(seat_no) in decisions:
            continue
        cards = _hand_list(hands, seat_no)
        if seat.get("participant_kind") == "bot":
            table = await _bot_blackjack(bot, client, table, seat_no=seat_no, cards=cards)
    table = await _refresh(client, table)
    await _edit_board(bot, client, table, reply_markup=_card_keyboard(table))
    table = await _sync_blackjack_dms(bot, client, table)
    await _maybe_finish_blackjack(bot, client, table)


async def _sync_blackjack_dms(bot: AsyncTeleBot, client, table: dict[str, Any]) -> dict[str, Any]:
    """Send/update personal hit boards in each human's DM. Group card stays public."""
    if not _is_blackjack(table):
        return table
    table = await _refresh(client, table)
    if str(table.get("status")) not in {"running", "tie_break_running"} and not _blackjack_showdown(table):
        return table
    chats = list(_play_chats(table))
    blocked = list(_dm_blocked_ids(table))
    changed = False
    for seat in _table_seats(table):
        if not isinstance(seat, dict) or seat.get("participant_kind") != "player":
            continue
        tid = _as_telegram_id(seat.get("telegram_id"))
        if tid is None:
            continue
        text = _card_text(table, viewer_id=tid)
        markup = _card_keyboard(table, viewer_id=tid)
        if markup is None:
            markup = types.InlineKeyboardMarkup()
        existing = next((row for row in chats if row.get("chat_id") == tid), None)
        msg_id = existing.get("card_msg_id") if isinstance(existing, dict) else None
        edited = False
        if isinstance(msg_id, int):
            try:
                await bot.edit_message_text(text, tid, msg_id, parse_mode="HTML", reply_markup=markup)
                edited = True
            except Exception as exc:
                if "not modified" in str(exc).lower():
                    edited = True
                elif _telegram_cannot_dm(exc):
                    if tid not in blocked:
                        blocked.append(tid)
                        changed = True
                    continue
                else:
                    logger.info("V2 BJ DM edit failed table=%s user=%s", _table_id(table), tid, exc_info=True)
        if edited:
            continue
        try:
            msg = await bot.send_message(tid, text, parse_mode="HTML", reply_markup=markup)
        except Exception as exc:
            if _telegram_cannot_dm(exc):
                if tid not in blocked:
                    blocked.append(tid)
                    changed = True
                logger.info("V2 BJ DM blocked table=%s user=%s", _table_id(table), tid)
            else:
                logger.exception("V2 BJ DM send failed table=%s user=%s", _table_id(table), tid)
            continue
        chats = _upsert_play_chat(chats, chat_id=tid, card_msg_id=int(msg.message_id))
        changed = True
    if not changed and blocked == _dm_blocked_ids(table):
        return table
    patch = _play_state_patch(table, chats) if changed else {}
    if blocked != _dm_blocked_ids(table):
        patch["dm_blocked"] = blocked
    if not patch:
        return table
    try:
        return await _persist(client, table, patch)
    except Exception:
        logger.exception("V2 BJ DM persist failed table=%s", _table_id(table))
        return table


async def open_blackjack_dm_table(bot: AsyncTeleBot, client, *, chat_id: int, user_id: int, table_id: str) -> bool:
    """Deep-link /start bj_<table_id>: show this player's private board if seated."""
    try:
        tables = await client.v2_tables_get("/v2/tables/active")
    except Exception:
        logger.warning("V2 BJ deep-link refresh failed table=%s user=%s", table_id, user_id, exc_info=True)
        await bot.send_message(chat_id, "Не удалось обновить стол. Повторите через несколько секунд.")
        return False
    items = tables.get("tables") if isinstance(tables, dict) else []
    table = next((item for item in items if isinstance(item, dict) and str(item.get("table_id")) == table_id), None)
    if not isinstance(table, dict):
        await bot.send_message(chat_id, "Стол уже недоступен или партия закончилась.")
        return False
    if _seat_for_player(table, user_id) is None:
        await bot.send_message(chat_id, "Вы не за этим столом.")
        return False
    await _sync_blackjack_dms(bot, client, table)
    return True


async def _bot_blackjack(bot: AsyncTeleBot, client, table: dict[str, Any], *, seat_no: int, cards: list[str]) -> dict[str, Any]:
    creator_id = int(table.get("creator_id") or 0)
    hands = dict(_state(table).get("hands") or {})
    decisions = dict(_state(table).get("decisions") or {})
    current = list(cards)
    round_no = _tie_round(_state(table))
    while bj_best_score(current) < _HIT_UNTIL:
        dealt = await client.v2_table_cards(
            _table_id(table), "deal", telegram_id=creator_id, hand_size=len(current) + 1, seat_no=seat_no,
            shoe_side=_shoe_side(seat_no, tie_round=round_no),
        )
        nxt = dealt.get("cards") if isinstance(dealt, dict) else current
        current = list(nxt) if isinstance(nxt, list) else current
        if bj_best_score(current) >= 21:
            break
    hands[str(seat_no)] = current
    decisions[str(seat_no)] = "stand"
    return await _persist_and_refresh(client, table, {"hands": hands, "decisions": decisions})


async def _continue_cards(bot: AsyncTeleBot, client, table: dict[str, Any]) -> None:
    await _prompt_card_actions(bot, client, table)


async def _maybe_finish_blackjack(bot: AsyncTeleBot, client, table: dict[str, Any]) -> None:
    state = _state(table)
    decisions = state.get("decisions") if isinstance(state.get("decisions"), dict) else {}
    active = _active_seat_nos(state, _table_seats(table))
    if any(str(seat_no) not in decisions for seat_no in active):
        return
    await _score_cards(bot, client, table)


async def _score_cards(bot: AsyncTeleBot, client, table: dict[str, Any]) -> None:
    table = await _refresh(client, table)
    state = _state(table)
    hands = state.get("hands") if isinstance(state.get("hands"), dict) else {}
    game_type = str(table.get("game_type"))
    active = _active_seat_nos(state, _table_seats(table))
    totals: dict[int, int] = {}
    for seat_no in active:
        totals[seat_no] = _seat_score(game_type, _hand_list(hands, seat_no))
    leaders = leader_seat_nos(totals)
    await _edit_board(bot, client, table)
    if len(leaders) == 1:
        await _commit_settle(bot, client, table, kind="winner", winner_seat_nos=leaders)
        return
    if _draw_policy(state) == "tie_split":
        await _commit_settle(bot, client, table, kind="tie_split", winner_seat_nos=leaders)
        return
    scores = "–".join(str(totals[seat_no]) for seat_no in leaders)
    committed = await client.v2_table_operation(
        _table_id(table), "commit-outcome",
        expected_state_version=_version(table),
        outcome_kind="tie_break",
        winner_seat_nos=leaders,
        idempotency_key=_idempotency("card-tie", _table_id(table), _version(table)),
    )
    table = committed.get("table") if isinstance(committed, dict) else table
    if not isinstance(table, dict):
        return
    round_no = _tie_round(state) + 1
    new_hands: dict[str, list[str]] = dict(_state(table).get("hands") or {})
    for seat_no in leaders:
        seat = next((row for row in _table_seats(table) if int(row["seat_no"]) == seat_no), None)
        actor = _deal_actor(table, seat) if isinstance(seat, dict) else int(table.get("creator_id") or 0)
        dealt = await client.v2_table_cards(
            _table_id(table), "deal", telegram_id=actor, hand_size=2, seat_no=seat_no, shoe_side=_shoe_side(seat_no, tie_round=round_no),
        )
        cards = dealt.get("cards") if isinstance(dealt, dict) else []
        new_hands[str(seat_no)] = list(cards) if isinstance(cards, list) else []
    table = await _persist_and_refresh(client, table, {
        "phase": "cards",
        "hands": new_hands,
        "decisions": {},
        "tie_break_seat_nos": leaders,
        "tie_break_round": round_no,
        "board_note": f"Ничья {scores}. Переброс лидеров.",
    })
    await start_card_reveal(bot, client, table, restart=True)
    await wait_drama(_reveal_key(_table_id(table)), REVEAL_HOLD_SECONDS)
    await _prompt_card_actions(bot, client, table)


async def handle_card_action(bot: AsyncTeleBot, client, call, *, hit: bool) -> None:
    chat_id = getattr(getattr(getattr(call, "message", None), "chat", None), "id", None)
    if isinstance(chat_id, int) and chat_id < 0:
        await bot.answer_callback_query(call.id, "Откройте личку игрового бота: карты и действия находятся там.", show_alert=True)
        return
    table_id = str(call.data).split(":", 1)[1]
    try:
        tables = await client.v2_tables_get("/v2/tables/active")
    except Exception:
        await bot.answer_callback_query(
            call.id,
            "Не удалось обновить стол. Повторите через несколько секунд.",
            show_alert=True,
        )
        return
    items = tables.get("tables") if isinstance(tables, dict) else []
    table = next((item for item in items if isinstance(item, dict) and str(item.get("table_id")) == table_id), None)
    if not isinstance(table, dict):
        await bot.answer_callback_query(call.id, "Игра уже завершена или отменена. Эта кнопка устарела.", show_alert=True)
        return
    seat = _seat_for_player(table, call.from_user.id)
    if seat is None:
        await bot.answer_callback_query(call.id, "Вы не за этим столом.", show_alert=True)
        return
    seat_no = int(seat["seat_no"])
    state = _state(table)
    decisions = dict(state.get("decisions") or {})
    if str(seat_no) in decisions:
        await bot.answer_callback_query(call.id, "Решение уже принято.")
        return
    hands = dict(state.get("hands") or {})
    cards = _hand_list(hands, seat_no)
    try:
        if hit:
            dealt = await client.v2_table_cards(
                table_id, "deal", telegram_id=call.from_user.id, hand_size=len(cards) + 1, seat_no=seat_no,
                shoe_side=_shoe_side(seat_no, tie_round=_tie_round(state)),
            )
        else:
            dealt = None
    except Exception as exc:
        response = getattr(exc, "response", None)
        detail = None
        if response is not None:
            with contextlib.suppress(Exception):
                body = response.json()
                detail = body.get("detail") if isinstance(body, dict) else None
        await bot.answer_callback_query(call.id, str(detail or "Игра уже изменилась или завершилась. Кнопка устарела.")[:200], show_alert=True)
        return
    if hit:
        nxt = dealt.get("cards") if isinstance(dealt, dict) else cards
        cards = list(nxt) if isinstance(nxt, list) else cards
        hands[str(seat_no)] = cards
        if bj_best_score(cards) >= 21:
            decisions[str(seat_no)] = "stand"
        try:
            table = await _persist_and_refresh(client, table, {"hands": hands, "decisions": decisions})
        except Exception:
            await bot.answer_callback_query(call.id, "Игра уже изменилась. Кнопка устарела, обновите карточку.", show_alert=True)
            return
        await bot.answer_callback_query(call.id)
        await _edit_board(bot, client, table, reply_markup=_card_keyboard(table))
        table = await _sync_blackjack_dms(bot, client, table)
    else:
        decisions[str(seat_no)] = "stand"
        try:
            table = await _persist_and_refresh(client, table, {"hands": hands, "decisions": decisions})
        except Exception:
            await bot.answer_callback_query(call.id, "Игра уже изменилась. Кнопка устарела, обновите карточку.", show_alert=True)
            return
        await bot.answer_callback_query(call.id, "Ок, карты оставлены.")
        await _edit_board(bot, client, table, reply_markup=_card_keyboard(table))
        table = await _sync_blackjack_dms(bot, client, table)
    await _maybe_finish_blackjack(bot, client, table)


def register_v2_runtime_handlers(bot: AsyncTeleBot, client) -> None:
    @bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and c.data.startswith("v2hit:"))
    async def v2_hit(call):
        await handle_card_action(bot, client, call, hit=True)

    @bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and c.data.startswith("v2stand:"))
    async def v2_stand(call):
        await handle_card_action(bot, client, call, hit=False)


async def run_v2_outbox_pass(bot: Any, client: Any, *, worker_id: str, limit: int = 50, lease_seconds: int = 60) -> int:
    response = await client.v2_recovery_or_outbox("/v2/outbox/claim", worker_id=worker_id, limit=limit, lease_seconds=lease_seconds)
    items = response.get("items") if isinstance(response, dict) else None
    if not isinstance(items, list):
        return 0
    processed = 0
    for message in items:
        if not isinstance(message, dict):
            continue
        outbox_id = message.get("outbox_id")
        claim_token = message.get("claim_token")
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        recipient_id = message.get("recipient_id")
        event_type = str(message.get("event_type") or "")
        table_id = str(payload.get("table_id") or message.get("table_id") or "")
        public_job = event_type in {"public_settled", "public_cancelled"}
        if public_job:
            try:
                remembered = recall_table(table_id)
                if remembered is None and isinstance(payload.get("table"), dict):
                    remembered = payload["table"]
                if event_type == "public_cancelled":
                    await discard_table_cards(bot, remembered, table_id=table_id)
                elif remembered is not None:
                    await publish_settled_table(bot, client, remembered, payload)
                else:
                    raise RuntimeError("public table snapshot is missing")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("V2 public board delivery failed for %s", outbox_id, exc_info=True)
                error_kind, retry_after_seconds = classify_telegram_delivery_error(exc)
                if error_kind == "dm_unavailable":
                    error_kind = "temporary"
                with contextlib.suppress(Exception):
                    await client.v2_recovery_or_outbox(
                        "/v2/outbox/fail",
                        outbox_id=outbox_id,
                        claim_token=claim_token,
                        error=str(exc)[:1000],
                        error_kind=error_kind,
                        retry_after_seconds=retry_after_seconds,
                    )
            else:
                with contextlib.suppress(Exception):
                    await client.v2_recovery_or_outbox(
                        "/v2/outbox/complete", outbox_id=outbox_id, claim_token=claim_token,
                    )
            processed += 1
            continue

        # Backward compatibility for rows created before public group delivery
        # became its own durable outbox event.  Failure remains independent of DM.
        if table_id and payload.get("public_delivery_separate") is not True:
            try:
                remembered = recall_table(table_id)
                if event_type == "cancelled" or str(payload.get("result") or "") == "cancel":
                    await discard_table_cards(bot, remembered, table_id=table_id)
                elif remembered is not None:
                    await publish_settled_table(bot, client, remembered, payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Legacy V2 public board delivery failed for %s", outbox_id, exc_info=True)

        try:
            if isinstance(recipient_id, int):
                await bot.send_message(
                    recipient_id,
                    format_personal_result_dm(payload, recipient_id=recipient_id),
                    parse_mode="HTML",
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("V2 personal result delivery failed for %s", outbox_id, exc_info=True)
            error_kind, retry_after_seconds = classify_telegram_delivery_error(exc)
            if error_kind == "dm_unavailable":
                with contextlib.suppress(Exception):
                    await _send_v2_outbox_dm_fallback(bot, payload, recipient_id)
            with contextlib.suppress(Exception):
                await client.v2_recovery_or_outbox(
                    "/v2/outbox/fail",
                    outbox_id=outbox_id,
                    claim_token=claim_token,
                    error=str(exc)[:1000],
                    error_kind=error_kind,
                    retry_after_seconds=retry_after_seconds,
                )
        else:
            try:
                await client.v2_recovery_or_outbox("/v2/outbox/complete", outbox_id=outbox_id, claim_token=claim_token)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("V2 result was sent but delivery acknowledgement failed for %s", outbox_id, exc_info=True)
        processed += 1
    return processed


def _fallback_chat_id(payload: dict[str, Any]) -> int | None:
    raw = payload.get("game_chat_id")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) and raw < 0:
        return raw
    if isinstance(raw, str):
        try:
            parsed = int(raw)
        except ValueError:
            return None
        return parsed if parsed < 0 else None
    return None


async def _send_v2_outbox_dm_fallback(bot: Any, payload: dict[str, Any], recipient_id: object) -> None:
    chat_id = _fallback_chat_id(payload)
    if chat_id is None:
        return
    username = (getattr(config, "BOT_USERNAME", "") or "focusludka_bot").strip().lstrip("@")
    table_id = str(payload.get("table_id") or "")
    short = fmt_id(table_id) if table_id else "стол"
    user_hint = str(recipient_id) if isinstance(recipient_id, int) and recipient_id > 0 else "игрока"
    text = (
        f"Не смог отправить личный результат для {short} пользователю {html.escape(user_hint)}.\n"
        f"Откройте личку @{html.escape(username)} и нажмите /start, результат будет доставлен повторно."
    )
    await bot.send_message(chat_id, text, disable_web_page_preview=True)


async def run_v2_recovery_pass(client: Any, *, worker_id: str, limit: int = 50, lease_seconds: int = 60) -> int:
    response = await client.v2_recovery_or_outbox("/v2/recovery/claim", worker_id=worker_id, limit=limit, lease_seconds=lease_seconds)
    items = response.get("items") if isinstance(response, dict) else None
    if not isinstance(items, list):
        return 0
    processed = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        table = item.get("table") if isinstance(item.get("table"), dict) else {}
        claim_token = item.get("claim_token")
        table_id = str(table.get("table_id") or "")
        status = str(table.get("status") or "")
        try:
            if status == "outcome_committed":
                await client.v2_table_operation(
                    table_id, "settle-committed-outcome",
                    expected_state_version=int(table.get("state_version") or 0),
                    idempotency_key=f"recovery-settle-{table_id}-{uuid.uuid4().hex}",
                )
            await client.v2_recovery_or_outbox("/v2/recovery/complete", table_id=table_id, claim_token=claim_token)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("V2 recovery failed table=%s", table_id)
        processed += 1
    return processed
