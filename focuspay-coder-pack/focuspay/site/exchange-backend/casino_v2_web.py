"""Website JWT surface for V2 equal-stake tables (dice, baccarat, blackjack 2–6)."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from casino_cards import pair_commit
from casino_chat import public_actors
from casino_default_avatar import default_avatar_url_for_user
from casino_duels import bot_chip
from casino_finance import MAX_BOTS_PER_TABLE, money
from casino_pvp_dice import hmac_pip
from casino_wallet import scope_filter_for, scope_or_mine_filter, viewer_scope

logger = logging.getLogger("casino_v2_web")

WEB_V2_GAME_TYPE = "pvp_dice"
WEB_V2_CARD_GAME_TYPES = frozenset({"blackjack", "baccara"})
WEB_V2_GAME_TYPES = frozenset({"pvp_dice", "blackjack", "baccara"})
WEB_V2_COMMISSION_RATE = Decimal("0.05")  # must match settle_v2_table_with_conn
WEB_V2_ROLL_TIMEOUT_SECONDS = 30
WEB_V2_TELEGRAM_HIT_TIMEOUT_SECONDS = 180
WEB_V2_DRAW_CHOICE_TIMEOUT_SECONDS = 60
HMAC_STATE_KEY = "hmac"
ACTIVE_LOBBY_STATUSES = (
    "open",
    "ready",
    "running",
    "tie_break_running",
    "outcome_committed",
    "settling",
)
PLAY_STATUSES = frozenset({"running", "tie_break_running"})
RETIRED_V2_GAME_TYPES = frozenset({"pvp_darts", "pvp_bowling", "pvp_football", "pvp_basketball"})
BLACKJACK_CARD_BACK = "back"
BLACKJACK_SHOWDOWN_STATUSES = frozenset(
    {"finished", "cancelled", "expired", "manual_review", "outcome_committed", "settled", "settling"}
)
# "scoring" is the deal window before hitting, not the showdown. Faces there
# flash open and then close when the phase becomes "hitting".
BLACKJACK_SHOWDOWN_PHASES = frozenset({"draw_choice", "settled"})
_STALE_DEADLINE_KEYS = ("draw_choice_deadline_at", "roll_deadline_at")
TELEGRAM_STALE_IDLE_SECONDS = 30 * 60


def _int_chat_id(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def telegram_play_surface(table: Mapping[str, Any] | None, state: Mapping[str, Any] | None = None) -> bool:
    """True when players throw Telegram dice in a group (play_chats or game_chat_id < 0).

    A group listing_chat_id alone is an announcement; play may be in DMs and still uses the web closer.
    """
    row = table if isinstance(table, Mapping) else {}
    blob = state if isinstance(state, Mapping) else None
    if blob is None:
        raw = row.get("game_state")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {}
        blob = raw if isinstance(raw, Mapping) else {}
    chats = blob.get("play_chats")
    if isinstance(chats, list):
        for item in chats:
            if not isinstance(item, Mapping):
                continue
            chat_id = _int_chat_id(item.get("chat_id"))
            if chat_id is not None and chat_id < 0:
                return True
    chat_id = _int_chat_id(row.get("game_chat_id"))
    return chat_id is not None and chat_id < 0


def _parse_v2_deadline(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def _start_stamp(table: Mapping[str, Any]) -> datetime | None:
    """When the round actually started. Ignore updated_at — card persist keeps bumping it."""
    for key in ("started_at", "created_at"):
        raw = table.get(key)
        if isinstance(raw, datetime):
            stamp = raw
        else:
            stamp = _parse_v2_deadline(raw)
        if stamp is None:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp
    return None


def blackjack_hit_timeout_seconds(table: Mapping[str, Any] | None, state: Mapping[str, Any] | None = None) -> int:
    """Group chat needs minutes to hit; web/DM keeps the 30s auto-stand."""
    blob = state
    if blob is None and isinstance(table, Mapping):
        raw = table.get("game_state")
        blob = raw if isinstance(raw, Mapping) else None
    if telegram_play_surface(table, blob if isinstance(blob, Mapping) else None):
        return WEB_V2_TELEGRAM_HIT_TIMEOUT_SECONDS
    return WEB_V2_ROLL_TIMEOUT_SECONDS


def effective_roll_deadline(table: Mapping[str, Any], state: Mapping[str, Any]) -> datetime | None:
    """Web/DM closer deadline. Missing roll_deadline_at means started_at + 30s, not 'never'."""
    if telegram_play_surface(table, state):
        return None
    deadline = _parse_v2_deadline(state.get("roll_deadline_at") if isinstance(state, Mapping) else None)
    if deadline is not None:
        return deadline
    start = _start_stamp(table)
    if start is None:
        return None
    return start + timedelta(seconds=WEB_V2_ROLL_TIMEOUT_SECONDS)


def v2_play_is_stale(table: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """True when a leftover sport/card/dice table should be refunded, not a live turn timeout."""
    status = str(table.get("status") or "")
    if status not in PLAY_STATUSES:
        return False
    gtype = str(table.get("game_type") or "")
    if gtype in RETIRED_V2_GAME_TYPES:
        return True
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    state = table.get("game_state")
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except json.JSONDecodeError:
            state = {}
    if not isinstance(state, Mapping):
        state = {}
    if gtype in WEB_V2_GAME_TYPES:
        # A turn deadline belongs to auto-roll/auto-stand, not cancellation.
        # The independent waiting worker may run before the game closer.
        stamp = _start_stamp(table)
        if stamp is None:
            deadlines = [_parse_v2_deadline(state.get(key)) for key in _STALE_DEADLINE_KEYS]
            stamp = min((value for value in deadlines if value is not None), default=None)
        if stamp is None:
            return False
        return (clock - stamp).total_seconds() >= TELEGRAM_STALE_IDLE_SECONDS
    for key in _STALE_DEADLINE_KEYS:
        deadline = _parse_v2_deadline(state.get(key))
        if deadline is not None and deadline <= clock:
            return True
    return False

_closer_started = False


class V2WebCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_type: str = WEB_V2_GAME_TYPE
    stake_rub: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    max_seats: int = Field(ge=2, le=6)
    bot_count: int = Field(default=0, ge=0, le=5)
    autojoin: bool = True

    @model_validator(mode="after")
    def bounds(self):
        if self.game_type not in WEB_V2_GAME_TYPES:
            raise ValueError("На сайте стол 2–6: кубики, баккара и блэкджек")
        if self.bot_count >= self.max_seats:
            raise ValueError("Хотя бы одно место должно остаться игроку")
        return self


class V2WebVersionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_state_version: int = Field(ge=0)


class V2WebDrawChoiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_state_version: int = Field(ge=0)
    choice: str = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def known_choice(self):
        if self.choice not in {"tie_split", "redeal"}:
            raise ValueError("Выберите раздел банка или перераздачу")
        return self


def _as_map(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def is_web_card_table(game_type: object) -> bool:
    return str(game_type or "") in WEB_V2_CARD_GAME_TYPES


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _text_money(value: object) -> str:
    return format(money(value or 0), ".2f")


def seat_roll_key(seat_no: int, roll_index: int) -> str:
    return f"s{int(seat_no)}r{int(roll_index)}"


def required_rolls(state: Mapping[str, Any]) -> int:
    try:
        rounds = int(state.get("rounds") or 1)
    except (TypeError, ValueError):
        rounds = 1
    return 2 if rounds == 2 else 1


def seat_nos_from_rolls(rolls: Mapping[str, Any]) -> list[int]:
    found: set[int] = set()
    for key in rolls:
        if not isinstance(key, str) or not key.startswith("s") or "r" not in key[1:]:
            continue
        try:
            found.add(int(key[1:].split("r", 1)[0]))
        except ValueError:
            continue
    return sorted(found)


def hydrate_roster(state: Mapping[str, Any], roster: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Keep finished seats visible even if the SQL roster was filtered to 'seated' only."""
    by_no: dict[int, dict[str, Any]] = {}
    for seat in roster or []:
        try:
            seat_no = int(seat["seat_no"])
        except (TypeError, ValueError, KeyError):
            continue
        by_no[seat_no] = dict(seat)
    implied: list[int] = []
    raw_seats = state.get("seat_nos")
    if isinstance(raw_seats, list):
        for item in raw_seats:
            try:
                implied.append(int(item))
            except (TypeError, ValueError):
                continue
    rolls = state.get("rolls") if isinstance(state.get("rolls"), dict) else {}
    implied.extend(seat_nos_from_rolls(rolls))
    for seat_no in implied:
        by_no.setdefault(seat_no, {"seat_no": seat_no, "participant_kind": "player"})
    return [by_no[n] for n in sorted(by_no)]


def occupied_seat_nos(state: Mapping[str, Any], roster: Iterable[Mapping[str, Any]] | None = None) -> list[int]:
    leaders = state.get("tie_break_seat_nos")
    if isinstance(leaders, list) and leaders:
        return [int(seat_no) for seat_no in leaders]
    seat_nos = state.get("seat_nos")
    if isinstance(seat_nos, list) and seat_nos:
        return [int(seat_no) for seat_no in seat_nos]
    if roster is None:
        return []
    return sorted(int(seat["seat_no"]) for seat in roster if seat.get("seat_no") is not None)


def blackjack_decisions_map(state: Mapping[str, Any]) -> dict[str, Any]:
    raw = state.get("decisions") if isinstance(state, Mapping) else None
    return dict(raw) if isinstance(raw, dict) else {}


def blackjack_web_decisions(state: Mapping[str, Any], *, seat_no: int, mark_stand: bool) -> dict[str, Any]:
    """Keep bot `_maybe_finish_blackjack` in sync: a truthy decision means the seat is done."""
    decisions = blackjack_decisions_map(state)
    if mark_stand:
        decisions[str(int(seat_no))] = "stand"
    return decisions


def blackjack_hole_cards_hidden(
    row: Mapping[str, Any],
    state: Mapping[str, Any],
    roster: Iterable[Mapping[str, Any]] | None,
) -> bool:
    """True while a V2 blackjack round is still private (own cards only)."""
    if str(row.get("game_type") or "") != "blackjack":
        return False
    status = str(row.get("status") or "")
    if status in BLACKJACK_SHOWDOWN_STATUSES:
        return False
    phase = str(state.get("phase") or "")
    if phase in BLACKJACK_SHOWDOWN_PHASES:
        return False
    from casino_v2_cards import stood_seats_from_state

    stood = stood_seats_from_state(state)
    active = occupied_seat_nos(state, roster)
    if not active:
        return True
    return not all(int(seat_no) in stood for seat_no in active)


def _hidden_blackjack_cards(cards: list[str]) -> list[str]:
    """Two backs, even after a hit. The count would show that the seat drew."""
    if not cards:
        return []
    return [BLACKJACK_CARD_BACK, BLACKJACK_CARD_BACK]


def _seat_key_no(key: object) -> int | None:
    try:
        return int(key)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def all_rolls_complete(rolls: Mapping[str, Any], seat_nos: Iterable[int], required: int) -> bool:
    for seat_no in seat_nos:
        for index in range(required):
            if seat_roll_key(seat_no, index) not in rolls:
                return False
    return True


def seat_totals(rolls: Mapping[str, Any], seat_nos: Iterable[int], required: int) -> dict[int, int]:
    totals: dict[int, int] = {}
    for seat_no in seat_nos:
        total = 0
        for index in range(required):
            total += int(rolls[seat_roll_key(seat_no, index)])
        totals[int(seat_no)] = total
    return totals


def leader_seat_nos(totals: Mapping[int, int]) -> list[int]:
    if not totals:
        return []
    best = max(totals.values())
    return sorted(seat_no for seat_no, total in totals.items() if total == best)


def apply_roll(
    game_state: Mapping[str, Any],
    *,
    seat_no: int,
    roll_index: int,
    value: int,
    required: int,
) -> dict[str, Any]:
    state = dict(game_state or {})
    rolls = dict(state.get("rolls") or {})
    key = seat_roll_key(seat_no, roll_index)
    if key in rolls:
        raise ValueError("roll already recorded")
    if roll_index < 0 or roll_index >= required:
        raise ValueError("roll index out of range")
    rolls[key] = int(value)
    state["rolls"] = rolls
    complete = all_rolls_complete(rolls, occupied_seat_nos(state), required)
    in_tie_break = bool(state.get("tie_break_seat_nos")) or state.get("phase") == "tie_break"
    if in_tie_break:
        state["phase"] = "scoring" if complete else "tie_break"
    else:
        state["phase"] = "scoring" if complete else "rolling"
    return state


def missing_roll_index(rolls: Mapping[str, Any], seat_no: int, required: int) -> int | None:
    for index in range(required):
        if seat_roll_key(seat_no, index) not in rolls:
            return index
    return None


def tie_break_state(game_state: Mapping[str, Any], leaders: list[int]) -> dict[str, Any]:
    state = dict(game_state or {})
    state["phase"] = "tie_break"
    state["tie_break_round"] = int(state.get("tie_break_round") or 0) + 1
    state["tie_break_seat_nos"] = list(leaders)
    rolls = dict(state.get("rolls") or {})
    for seat_no in leaders:
        prefix = f"s{int(seat_no)}r"
        for key in list(rolls):
            if str(key).startswith(prefix):
                rolls.pop(key, None)
    state["rolls"] = rolls
    return state


def preview_v2_equal_pot(stake_rub: Decimal | str | int | float, seat_count: int) -> dict[str, str]:
    """Same arithmetic as settle_v2_table_with_conn: 5% of the full pot, winner takes the rest."""
    if seat_count < 2:
        seat_count = 2
    stake = money(stake_rub)
    pot = money(stake * seat_count)
    commission = money(stake * seat_count * WEB_V2_COMMISSION_RATE)
    return {
        "pot_rub": _text_money(pot),
        "commission_rub": _text_money(commission),
        "net_payout_rub": _text_money(money(pot - commission)),
    }


def hmac_index(state: Mapping[str, Any], roll_index: int) -> int:
    """HMAC nonce for the current die. Tie-break rounds must not reuse round-0 material."""
    try:
        round_no = int(state.get("tie_break_round") or 0)
    except (TypeError, ValueError):
        round_no = 0
    if round_no < 0:
        round_no = 0
    return round_no * required_rolls(state) + int(roll_index)


def hmac_face(*, seed: str, table_id: str, seat_no: int, index: int, kind: str) -> int:
    return hmac_pip(seed, game_id=table_id, seat=f"s{int(seat_no)}", index=int(index), kind=kind)


def fill_hmac_rolls(
    state: Mapping[str, Any],
    roster: Iterable[Mapping[str, Any]],
    *,
    table_id: str,
    seed: str,
    kinds: frozenset[str],
    house: bool = False,
) -> dict[str, Any]:
    required = required_rolls(state)
    rolls = dict(state.get("rolls") or {})
    house_rolled = [str(item) for item in (state.get("house_rolled") or [])]
    active = set(occupied_seat_nos(state, roster))
    changed = False
    for seat in roster:
        kind = "bot" if seat.get("participant_kind") == "bot" else "player"
        if kind not in kinds:
            continue
        try:
            seat_no = int(seat["seat_no"])
        except (TypeError, ValueError, KeyError):
            continue
        if seat_no not in active:
            continue
        hmac_kind = "house" if house and kind == "player" else kind
        while True:
            index = missing_roll_index(rolls, seat_no, required)
            if index is None:
                break
            pip = hmac_face(
                seed=seed,
                table_id=table_id,
                seat_no=seat_no,
                index=hmac_index(state, index),
                kind=hmac_kind,
            )
            key = seat_roll_key(seat_no, index)
            rolls[key] = pip
            if hmac_kind == "house" and key not in house_rolled:
                house_rolled.append(key)
            changed = True
    if not changed:
        return dict(state)
    next_state = dict(state)
    next_state["rolls"] = rolls
    if house_rolled:
        next_state["house_rolled"] = house_rolled
    seats = occupied_seat_nos(next_state, roster)
    complete = all_rolls_complete(rolls, seats, required)
    in_tie = bool(next_state.get("tie_break_seat_nos")) or next_state.get("phase") == "tie_break"
    if complete:
        next_state["phase"] = "scoring"
    elif in_tie:
        next_state["phase"] = "tie_break"
    else:
        next_state["phase"] = "rolling"
    return next_state


def scoring_decision(
    state: Mapping[str, Any],
    roster: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    required = required_rolls(state)
    seats = occupied_seat_nos(state, roster)
    rolls = state.get("rolls") if isinstance(state.get("rolls"), dict) else {}
    if not seats or not all_rolls_complete(rolls, seats, required):
        return None
    totals = seat_totals(rolls, seats, required)
    leaders = leader_seat_nos(totals)
    if len(leaders) == 1:
        return {"kind": "winner", "winner_seat_nos": leaders, "totals": totals}
    policy = str(state.get("draw_policy") or "tie_break")
    if policy == "tie_split":
        return {"kind": "tie_split", "winner_seat_nos": leaders, "totals": totals}
    return {"kind": "tie_break", "winner_seat_nos": leaders, "totals": totals}


def public_game_state(
    state: Mapping[str, Any],
    *,
    finished: bool,
    hide_seat_nos: set[int] | None = None,
) -> dict[str, Any]:
    keep = (
        "bot_count",
        "draw_policy",
        "rounds",
        "phase",
        "rolls",
        "seat_nos",
        "tie_break_seat_nos",
        "tie_break_round",
        "draw_choice_deadline_at",
        "roll_deadline_at",
        "house_rolled",
        "hands",
        "scores",
        "cards_dealt_at",
        "stood_seats",
        "decisions",
    )
    out = {key: state[key] for key in keep if key in state}
    hidden = hide_seat_nos or set()
    if hidden:
        raw_hands = out.get("hands")
        if isinstance(raw_hands, dict):
            hands: dict[str, Any] = {}
            for key, cards in raw_hands.items():
                seat_no = _seat_key_no(key)
                if seat_no is None:
                    continue
                if seat_no in hidden:
                    hands[str(key)] = _hidden_blackjack_cards(
                        [str(card) for card in cards] if isinstance(cards, list) else []
                    )
                else:
                    hands[str(key)] = cards
            out["hands"] = hands
        raw_scores = out.get("scores")
        if isinstance(raw_scores, dict):
            out["scores"] = {
                str(key): value
                for key, value in raw_scores.items()
                if _seat_key_no(key) not in hidden
            }
    blob = _as_map(state.get(HMAC_STATE_KEY))
    if blob.get("commit"):
        out["commit"] = str(blob["commit"])
    if finished and blob.get("seed"):
        out["seed"] = str(blob["seed"])
    return out


def _parse_iso(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return _utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return None


def parse_deadline(state: Mapping[str, Any]) -> datetime | None:
    return _parse_iso(state.get("roll_deadline_at"))


def _hmac_seed(state: Mapping[str, Any]) -> str | None:
    seed = _as_map(state.get(HMAC_STATE_KEY)).get("seed")
    return str(seed) if isinstance(seed, str) and seed else None


def web_idempotency(operation: str, table_id: str, version: int, actor_id: int = 0) -> str:
    return f"web-{operation}-{table_id}-{version}-{actor_id}-{uuid4().hex[:10]}"


_V2_RU = {
    "V2 table state version conflicts": "Стол изменился. Обновите и повторите.",
    "V2 table is not open": "Стол уже не принимает игроков",
    "V2 table is full": "Стол заполнен",
    "V2 table has no reusable seat": "Стол заполнен",
    "Insufficient balance": "Недостаточно средств",
    "V2 bot capacity is unavailable": "Боты сейчас недоступны",
    "V2 robot concurrency limit reached": "Боты сейчас недоступны",
    "V2 robot exposure limit reached": "Боты сейчас недоступны",
    "V2 house bankroll is insufficient": "Боты сейчас недоступны",
    "Game type is disabled": "Игра выключена",
    "Existing v2 table conflicts": "Стол с таким id уже есть",
    "V2 table not found": "Стол не найден",
    "Only the table creator may start it": "Стартовать может только создатель",
    "Only the table creator may cancel it": "Отменить может только создатель",
    "V2 table cannot start": "Стол нельзя стартовать",
    "V2 table requires at least two seated participants": "Нужны минимум двое за столом",
    "Only an unstarted V2 table may be left or cancelled": "Из начавшейся игры выйти нельзя",
    "Player is not seated at this V2 table": "Вы не за этим столом",
    "V2 table is not mutable or its version conflicts": "Стол изменился. Обновите и повторите.",
    "V2 table state is not mutable or its version conflicts": "Стол изменился. Обновите и повторите.",
    "Blackjack draw choice is not available": "Сейчас нет выбора по ничьей",
    "Only seated players may choose the draw": "Выбор только для участников за столом",
    "Blackjack hit is not available": "Сейчас нельзя добрать",
    "Blackjack stand is not available": "Сейчас нельзя оставить",
    "Only seated players may act on blackjack": "Действие только для участников за столом",
    "V2 table cannot enter tie break": "Не удалось начать переброс. Обновите стол.",
}


def translate_v2(exc: HTTPException) -> HTTPException:
    detail = exc.detail
    if isinstance(detail, str) and detail in _V2_RU:
        return HTTPException(status_code=exc.status_code, detail=_V2_RU[detail])
    return exc


def _catch_v2(exc: HTTPException) -> None:
    raise translate_v2(exc) from exc


def public_table_view(
    row: Mapping[str, Any],
    roster: list[dict[str, Any]],
    *,
    viewer_id: int | None,
    actors: Mapping[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from casino_v2_cards import hands_from_state, stood_seats_from_state

    state = _as_map(row.get("game_state"))
    status = str(row.get("status") or "")
    finished = status in {"finished", "cancelled", "expired", "manual_review"}
    roster = hydrate_roster(state, roster)
    settlement = _as_map(row.get("settlement_payload"))
    outcome = _as_map(row.get("outcome"))
    winner_nos: set[int] = set()
    for raw in list(settlement.get("winner_seat_nos") or []) + list(outcome.get("winner_seat_nos") or []):
        try:
            winner_nos.add(int(raw))
        except (TypeError, ValueError):
            pass
    tie_nos: set[int] = set()
    if str(state.get("phase") or "") == "draw_choice":
        for raw in list(state.get("tie_break_seat_nos") or []):
            try:
                tie_nos.add(int(raw))
            except (TypeError, ValueError):
                pass
    payout_by_seat: dict[int, str] = {}
    for item in settlement.get("payouts") or []:
        if not isinstance(item, Mapping):
            continue
        try:
            seat_key = int(item.get("seat_no"))
        except (TypeError, ValueError):
            continue
        payout_by_seat[seat_key] = _text_money(item.get("amount_rub") or 0)
    max_seats = int(row.get("max_seats") or row.get("max_players") or 0)
    occupied = {int(seat["seat_no"]) for seat in roster if seat.get("seat_no") is not None}
    free_seats = [seat_no for seat_no in range(1, max_seats + 1) if seat_no not in occupied]
    stake = money(row.get("stake_rub") or 0)
    seated = max(len(roster), 2)
    money_preview = preview_v2_equal_pot(stake, seated)
    required = required_rolls(state)
    rolls = state.get("rolls") if isinstance(state.get("rolls"), dict) else {}
    creator_id = int(row["creator_id"])
    game_type = str(row.get("game_type") or WEB_V2_GAME_TYPE)
    hide_holes = blackjack_hole_cards_hidden(row, state, roster)
    my_seat = None
    public_roster: list[dict[str, Any]] = []
    for seat in roster:
        try:
            seat_no = int(seat["seat_no"])
        except (TypeError, ValueError, KeyError):
            continue
        kind = str(seat.get("participant_kind") or "player")
        telegram_id = seat.get("telegram_id")
        is_you = False
        if kind == "bot":
            bot = seat.get("bot") if isinstance(seat.get("bot"), dict) else {}
            actor = bot_chip(
                str(bot.get("display_name") or "Бот"),
                profile_id=bot.get("id") or bot.get("profile_id") or seat.get("robot_profile_id"),
                profile_key=bot.get("profile_key"),
                seat_no=seat_no,
            )
        else:
            uid = int(telegram_id) if telegram_id is not None else 0
            is_you = viewer_id is not None and uid != 0 and uid == int(viewer_id)
            if is_you:
                my_seat = seat_no
            actor = (actors or {}).get(uid) or {
                "user_id": uid,
                "display_name": str(uid) if uid else f"Место {seat_no}",
                "initial": str(uid)[:1] if uid else str(seat_no),
                "avatar_url": default_avatar_url_for_user(uid),
            }
        pips = None
        total = 0
        shown = 0
        for roll_index in range(required):
            item = rolls.get(seat_roll_key(seat_no, roll_index))
            if item is None:
                continue
            pips = int(item)
            total += int(item)
            shown += 1
        hands = state.get("hands") if isinstance(state.get("hands"), dict) else {}
        scores_map = state.get("scores") if isinstance(state.get("scores"), dict) else {}
        raw_cards = hands.get(str(seat_no), hands.get(seat_no))
        cards = [str(card) for card in raw_cards] if isinstance(raw_cards, list) else []
        raw_score = scores_map.get(str(seat_no), scores_map.get(seat_no))
        try:
            score = int(raw_score) if raw_score is not None else None
        except (TypeError, ValueError):
            score = None
        if hide_holes and not is_you:
            cards = _hidden_blackjack_cards(cards)
            score = None
        public_roster.append(
            {
                "seat_no": seat_no,
                "participant_kind": kind,
                "actor": actor,
                "is_you": is_you,
                "pips": pips,
                "total": total if shown else None,
                "rolled": shown,
                "cards": cards,
                "score": score,
                "is_winner": bool(finished and winner_nos and seat_no in winner_nos),
                "is_leader": bool(not finished and tie_nos and seat_no in tie_nos),
                "payout_rub": payout_by_seat.get(seat_no) if finished else None,
            }
        )
    card_hands = hands_from_state(state)
    stood_seats = stood_seats_from_state(state)
    can_blackjack_act = bool(
        game_type == "blackjack"
        and my_seat is not None
        and status in PLAY_STATUSES
        and str(state.get("phase") or "") == "hitting"
        and _blackjack_can_act(int(my_seat), card_hands, stood_seats)
    )
    can_roll = False
    if not is_web_card_table(game_type) and my_seat is not None and status in PLAY_STATUSES:
        active = occupied_seat_nos(state, roster)
        can_roll = my_seat in active and missing_roll_index(rolls, my_seat, required) is not None
    if settlement:
        money_preview = {
            "pot_rub": str(settlement.get("pot_rub") or money_preview["pot_rub"]),
            "commission_rub": str(settlement.get("commission_rub") or money_preview["commission_rub"]),
            "net_payout_rub": _text_money(
                sum((money(item.get("amount_rub") or 0) for item in settlement.get("payouts") or [] if isinstance(item, dict)), Decimal("0"))
            ) if settlement.get("payouts") else money_preview["net_payout_rub"],
        }
    started = row.get("started_at")
    state_starts = state.get("starts_at")
    counting_down = bool(state_starts) and status in {"open", "ready"}
    payload: dict[str, Any] = {
        "table_id": str(row.get("table_id") or ""),
        "game_type": str(row.get("game_type") or WEB_V2_GAME_TYPE),
        "stake_rub": _text_money(stake),
        "max_seats": max_seats,
        "status": status,
        "state_version": int(row.get("state_version") or 0),
        "started_at": _iso(started) if isinstance(started, datetime) else None,
        "countdown_ends_at": str(state_starts) if counting_down else None,
        "bot_count": sum(1 for seat in public_roster if seat["participant_kind"] == "bot"),
        "free_seats": free_seats,
        "roster": public_roster,
        "rolls_needed": required,
        "my_seat_no": my_seat,
        "can_roll": can_roll,
        "can_start": bool(
            viewer_id is not None
            and int(viewer_id) == creator_id
            and status in {"open", "ready"}
            and len(roster) >= 2
            and not counting_down
        ),
        "can_add_bot": bool(
            my_seat is not None
            and status in {"open", "ready"}
            and len(free_seats) > 0
            and sum(1 for seat in public_roster if seat["participant_kind"] == "bot") < MAX_BOTS_PER_TABLE
            and not counting_down
        ),
        "can_leave": bool(
            viewer_id is not None
            and my_seat is not None
            and int(viewer_id) != creator_id
            and status in {"open", "ready"}
            and not counting_down
        ),
        "can_cancel": bool(
            viewer_id is not None
            and int(viewer_id) == creator_id
            and status in {"open", "ready"}
            and not counting_down
        ),
        "can_choose_draw": bool(
            is_web_card_table(game_type)
            and my_seat is not None
            and status in PLAY_STATUSES
            and str(state.get("phase") or "") == "draw_choice"
            and tie_nos
        ),
        "can_hit": can_blackjack_act,
        "can_stand": can_blackjack_act,
        "is_seated": my_seat is not None,
        "is_creator": bool(viewer_id is not None and int(viewer_id) == creator_id),
        "roll_deadline_at": (
            state.get("draw_choice_deadline_at")
            if str(state.get("phase") or "") == "draw_choice"
            else state.get("roll_deadline_at")
        )
        if status in PLAY_STATUSES and str(state.get("phase") or "") in {"draw_choice", "hitting", "rolling", "tie_break", "scoring"}
        else None,
        "house_will_roll": bool(status in PLAY_STATUSES and can_roll),
        "game_state": public_game_state(
            state,
            finished=finished,
            hide_seat_nos=(
                {int(seat["seat_no"]) for seat in public_roster if not seat.get("is_you")}
                if hide_holes
                else None
            ),
        ),
        **money_preview,
    }
    if finished and settlement:
        payload["settlement"] = {
            "outcome_kind": settlement.get("outcome_kind"),
            "winner_seat_nos": settlement.get("winner_seat_nos"),
            "pot_rub": settlement.get("pot_rub"),
            "commission_rub": settlement.get("commission_rub"),
            "payouts": settlement.get("payouts"),
        }
    if outcome:
        payload["outcome"] = {"kind": outcome.get("kind"), "winner_seat_nos": outcome.get("winner_seat_nos")}
    return payload


async def _attach_actors(conn, view: dict[str, Any]) -> dict[str, Any]:
    ids: list[int] = []
    for seat in view.get("roster") or []:
        actor = seat.get("actor") if isinstance(seat, dict) else None
        if not isinstance(actor, dict):
            continue
        uid = int(actor.get("user_id") or 0)
        if uid != 0:
            ids.append(uid)
    if not ids:
        return view
    actors = await public_actors(conn, ids)
    roster = []
    for seat in view.get("roster") or []:
        item = dict(seat)
        actor = item.get("actor") if isinstance(item.get("actor"), dict) else {}
        uid = int(actor.get("user_id") or 0)
        if uid != 0 and uid in actors:
            item["actor"] = actors[uid]
        roster.append(item)
    view["roster"] = roster
    return view


async def load_public_table(conn, table_id: str, viewer_id: int | None) -> dict[str, Any]:
    from routers.internal_casino import _v2_table_response_with_conn

    row = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id=$1", table_id)
    if not row:
        raise HTTPException(status_code=404, detail="Стол не найден")
    payload = await _v2_table_response_with_conn(conn, row)
    view = public_table_view(row, list(payload.get("roster") or []), viewer_id=viewer_id)
    return await _attach_actors(conn, view)


async def list_public_tables(conn, *, game_type: str, viewer_id: int | None) -> dict[str, Any]:
    from routers.internal_casino import _v2_table_response_with_conn

    if game_type not in WEB_V2_GAME_TYPES:
        return {"success": True, "tables": []}
    # Игрок видит только столы своей области: бонусные и реальные лобби не пересекаются.
    # Исключение — стол, где он уже сидит: иначе смена кошелька спрячет живую игру.
    scope_and = await scope_or_mine_filter(
        conn,
        "casino_v2_tables",
        await viewer_scope(conn, viewer_id),
        mine_sql=(
            "EXISTS (SELECT 1 FROM casino_v2_table_seats seat"
            " WHERE seat.table_id = casino_v2_tables.id AND seat.telegram_id = $3"
            " AND seat.status = 'seated')"
        ),
    )
    params: list[Any] = [game_type, list(ACTIVE_LOBBY_STATUSES)]
    if scope_and:
        params.append(int(viewer_id or 0))
    rows = await conn.fetch(
        f"""
        SELECT * FROM casino_v2_tables
        WHERE game_type=$1 AND status=ANY($2::text[]){scope_and}
        ORDER BY created_at DESC
        LIMIT 40
        """,
        *params,
    )
    tables: list[dict[str, Any]] = []
    for row in rows:
        payload = await _v2_table_response_with_conn(conn, row)
        view = public_table_view(row, list(payload.get("roster") or []), viewer_id=viewer_id)
        tables.append(await _attach_actors(conn, view))
    return {"success": True, "tables": tables}


async def _persist_patch(conn, table_id: str, expected_version: int, patch: dict[str, Any], operation: str) -> dict[str, Any]:
    from routers.internal_casino import V2TablePersistStateRequest, persist_v2_table_state_with_conn

    try:
        result = await persist_v2_table_state_with_conn(
            conn,
            table_id,
            V2TablePersistStateRequest(
                expected_state_version=expected_version,
                idempotency_key=web_idempotency(operation, table_id, expected_version),
                game_state=patch,
            ),
        )
    except HTTPException as exc:
        _catch_v2(exc)
    table = result.get("table")
    if not isinstance(table, dict):
        raise HTTPException(status_code=409, detail="Стол не сохранился")
    return table


async def _reload_row(conn, table_id: str):
    row = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id=$1", table_id)
    if not row:
        raise HTTPException(status_code=404, detail="Стол не найден")
    return row


async def ensure_round_ready(conn, table_id: str) -> None:
    from routers.internal_casino import _v2_table_response_with_conn

    row = await _reload_row(conn, table_id)
    if str(row["status"]) not in PLAY_STATUSES:
        return
    if is_web_card_table(row.get("game_type")):
        await ensure_blackjack_round(conn, table_id)
        return
    payload = await _v2_table_response_with_conn(conn, row)
    roster = list(payload.get("roster") or [])
    state = _as_map(row.get("game_state"))
    version = int(row.get("state_version") or 0)
    seed = _hmac_seed(state)
    if not seed:
        seed = secrets.token_hex(32)
        seat_nos = [int(seat["seat_no"]) for seat in roster]
        init = {
            "seat_nos": seat_nos,
            "phase": "rolling" if not state.get("tie_break_seat_nos") else "tie_break",
            "rolls": state.get("rolls") if isinstance(state.get("rolls"), dict) else {},
            "rounds": required_rolls(state),
            "draw_policy": str(state.get("draw_policy") or "tie_break"),
            HMAC_STATE_KEY: {"seed": seed, "commit": pair_commit(seed)},
        }
        if telegram_play_surface(row, state) or telegram_play_surface(payload, state):
            init["roll_deadline_at"] = None
        else:
            deadline = datetime.now(timezone.utc) + timedelta(seconds=WEB_V2_ROLL_TIMEOUT_SECONDS)
            init["roll_deadline_at"] = _iso(deadline)
        payload_table = await _persist_patch(conn, table_id, version, init, "hmac-init")
        version = int(payload_table.get("state_version") or version + 1)
        state = _as_map(payload_table.get("game_state"))
        roster = list(payload_table.get("roster") or roster)
        row = await _reload_row(conn, table_id)
    elif not telegram_play_surface(row, state) and parse_deadline(state) is None:
        clock = datetime.now(timezone.utc)
        due = effective_roll_deadline(row, state)
        if due is not None and due > clock:
            payload_table = await _persist_patch(
                conn,
                table_id,
                version,
                {"roll_deadline_at": _iso(due)},
                "roll-deadline",
            )
            version = int(payload_table.get("state_version") or version + 1)
            state = _as_map(payload_table.get("game_state"))
            roster = list(payload_table.get("roster") or roster)
            row = await _reload_row(conn, table_id)
    filled = fill_hmac_rolls(state, roster, table_id=table_id, seed=seed, kinds=frozenset({"bot"}))
    if filled.get("rolls") != (state.get("rolls") or {}):
        bot_patch: dict[str, Any] = {"rolls": filled["rolls"], "phase": filled.get("phase")}
        if filled.get("house_rolled"):
            bot_patch["house_rolled"] = filled["house_rolled"]
        payload_table = await _persist_patch(
            conn,
            table_id,
            version,
            bot_patch,
            "bot-rolls",
        )
        version = int(payload_table.get("state_version") or version + 1)
        state = _as_map(payload_table.get("game_state"))
        roster = list(payload_table.get("roster") or roster)
    await maybe_score(conn, table_id)


async def _settle_blackjack_outcome(
    conn,
    table_id: str,
    *,
    version: int,
    kind: str,
    winners: list[int],
) -> None:
    from routers.internal_casino import (
        V2TableCommitOutcomeRequest,
        V2TableSettleCommittedRequest,
        commit_v2_table_outcome_with_conn,
        settle_committed_v2_table_with_conn,
    )

    try:
        committed = await commit_v2_table_outcome_with_conn(
            conn,
            table_id,
            V2TableCommitOutcomeRequest(
                expected_state_version=version,
                idempotency_key=web_idempotency("commit", table_id, version),
                outcome_kind=kind,  # type: ignore[arg-type]
                winner_seat_nos=winners,
            ),
        )
    except HTTPException as exc:
        _catch_v2(exc)
    table = committed.get("table") if isinstance(committed, dict) else None
    if not isinstance(table, dict):
        return
    try:
        await settle_committed_v2_table_with_conn(
            conn,
            table_id,
            V2TableSettleCommittedRequest(
                expected_state_version=int(table.get("state_version") or 0),
                idempotency_key=web_idempotency("settle", table_id, int(table.get("state_version") or 0)),
            ),
        )
    except HTTPException as exc:
        _catch_v2(exc)


def _roster_has_human(roster: list[dict[str, Any]]) -> bool:
    for seat in roster:
        if str(seat.get("participant_kind") or "") != "player":
            continue
        try:
            if int(seat.get("telegram_id") or 0) != 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _roster_by_seat(roster: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for seat in roster:
        try:
            out[int(seat["seat_no"])] = seat
        except (TypeError, ValueError, KeyError):
            continue
    return out


def _viewer_seat(roster: list[dict[str, Any]], viewer_id: int) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in roster
            if item.get("participant_kind") == "player" and int(item.get("telegram_id") or 0) == int(viewer_id)
        ),
        None,
    )


def _blackjack_can_act(seat_no: int, hands: Mapping[int, list[str]], stood_seats: set[int]) -> bool:
    from casino_v2_cards import blackjack_seat_done

    cards = hands.get(int(seat_no))
    if not cards:
        return False
    return not blackjack_seat_done(cards, stood=seat_no in stood_seats)


async def _finalize_blackjack_action(
    conn,
    table_id: str,
    *,
    game_type: str,
    version: int,
    hands: dict[int, list[str]],
    state: Mapping[str, Any],
    roster: list[dict[str, Any]],
    clock: datetime,
    table: Mapping[str, Any] | None = None,
) -> None:
    from casino_v2_cards import json_hands, json_scores, next_card_table_action, stood_seats_from_state

    stood = stood_seats_from_state(state)
    action = next_card_table_action(
        game_type,
        hands,
        now=clock,
        dealt_at=_parse_iso(state.get("cards_dealt_at")),
        roster_has_human=_roster_has_human(roster),
        phase=str(state.get("phase") or ""),
        stood_seats=stood,
    )
    if action["kind"] == "hitting":
        scores = action.get("scores") if isinstance(action.get("scores"), dict) else {}
        deadline = clock + timedelta(seconds=blackjack_hit_timeout_seconds(table, state))
        await _persist_patch(
            conn,
            table_id,
            version,
            {
                "phase": "hitting",
                "hands": json_hands(hands),
                "scores": json_scores(scores) if scores else {},
                "stood_seats": sorted(stood),
                "roll_deadline_at": _iso(deadline),
            },
            "bj-hitting",
        )
        return
    winners = [int(seat) for seat in list(action.get("winners") or [])]
    if action["kind"] == "settle":
        await _settle_blackjack_outcome(
            conn,
            table_id,
            version=version,
            kind=str(action.get("outcome_kind") or "tie_split"),
            winners=winners,
        )
        return
    deadline = clock + timedelta(seconds=WEB_V2_DRAW_CHOICE_TIMEOUT_SECONDS)
    scores = action.get("scores") if isinstance(action.get("scores"), dict) else {}
    await _persist_patch(
        conn,
        table_id,
        version,
        {
            "phase": "draw_choice",
            "tie_break_seat_nos": winners,
            "scores": json_scores(scores) if scores else state.get("scores"),
            "hands": json_hands(hands),
            "draw_choice_deadline_at": _iso(deadline),
            "roll_deadline_at": None,
            "draw_policy": "choose",
        },
        "bj-draw-choice",
        )


async def _redeal_card_leaders(
    conn,
    table_id: str,
    *,
    version: int,
    game_type: str,
    state: Mapping[str, Any],
    leaders: list[int],
    scores: Mapping[Any, Any] | None = None,
) -> None:
    from casino_v2_cards import card_table_decision, deal_v2_card_hands, hands_from_state, json_hands, json_scores

    if len(leaders) < 2:
        return
    hands = hands_from_state(state)
    try:
        redeal_round = int(state.get("tie_break_round") or 0) + 1
    except (TypeError, ValueError):
        redeal_round = 1
    seed = secrets.token_hex(32)
    fresh = deal_v2_card_hands(game_type, seed, table_id, leaders, nonce=redeal_round)
    merged = dict(hands)
    merged.update(fresh)
    decision = card_table_decision(game_type, merged)
    next_scores = decision["scores"] if isinstance(decision.get("scores"), dict) else {}
    pair_parts: list[str] = []
    source = scores if isinstance(scores, Mapping) else {}
    for seat_no in leaders:
        raw = source.get(seat_no)
        if raw is None:
            raw = source.get(str(seat_no))
        if raw is None:
            continue
        try:
            pair_parts.append(str(int(raw)))
        except (TypeError, ValueError):
            continue
    board_note = f"Ничья {'–'.join(pair_parts)}. Переброс лидеров." if pair_parts else "Ничья. Переброс лидеров."
    await _persist_patch(
        conn,
        table_id,
        version,
        {
            "phase": "scoring",
            "hands": json_hands(merged),
            "scores": json_scores(next_scores) if next_scores else {},
            "tie_break_seat_nos": [],
            "tie_break_round": redeal_round,
            "draw_choice_deadline_at": None,
            "draw_policy": "tie_break",
            "stood_seats": [],
            "cards_dealt_at": _iso(datetime.now(timezone.utc)),
            "board_note": board_note,
            HMAC_STATE_KEY: {"seed": seed, "commit": pair_commit(seed)},
        },
        "card-redeal",
    )
    await ensure_blackjack_round(conn, table_id)


async def ensure_blackjack_round(conn, table_id: str, *, now: datetime | None = None) -> None:
    from casino_cards import pair_commit
    from casino_v2_cards import (
        auto_hit_blackjack_to_seventeen,
        deal_v2_card_hands,
        hands_from_state,
        json_hands,
        json_scores,
        next_card_table_action,
        stood_seats_from_state,
    )
    from routers.internal_casino import _v2_table_response_with_conn

    row = await _reload_row(conn, table_id)
    game_type = str(row.get("game_type") or "")
    if not is_web_card_table(game_type) or str(row["status"]) not in PLAY_STATUSES:
        return
    state = _as_map(row.get("game_state"))
    version = int(row.get("state_version") or 0)
    clock = now or datetime.now(timezone.utc)
    payload = await _v2_table_response_with_conn(conn, row)
    roster = list(payload.get("roster") or [])
    seat_nos = occupied_seat_nos(state, roster)
    phase = str(state.get("phase") or "")

    if phase == "draw_choice":
        deadline = parse_deadline({**state, "roll_deadline_at": state.get("draw_choice_deadline_at")})
        leaders = []
        for raw in list(state.get("tie_break_seat_nos") or []):
            try:
                leaders.append(int(raw))
            except (TypeError, ValueError):
                continue
        if leaders and (deadline is None or clock >= deadline or not _roster_has_human(roster)):
            if game_type == "baccara":
                await _redeal_card_leaders(
                    conn,
                    table_id,
                    version=version,
                    game_type=game_type,
                    state=state,
                    leaders=sorted(set(leaders)),
                    scores=state.get("scores") if isinstance(state.get("scores"), dict) else {},
                )
            else:
                await _settle_blackjack_outcome(
                    conn, table_id, version=version, kind="tie_split", winners=sorted(set(leaders))
                )
        return

    hands = hands_from_state(state)
    if not hands:
        seed = _hmac_seed(state) or secrets.token_hex(32)
        hands = deal_v2_card_hands(game_type, seed, table_id, seat_nos)
        action = next_card_table_action(
            game_type,
            hands,
            now=clock,
            dealt_at=clock,
            roster_has_human=_roster_has_human(roster),
        )
        scores = action.get("scores") if isinstance(action.get("scores"), dict) else {}
        await _persist_patch(
            conn,
            table_id,
            version,
            {
                "seat_nos": seat_nos,
                "phase": "scoring",
                "hands": json_hands(hands),
                "scores": json_scores(scores) if scores else {},
                "cards_dealt_at": _iso(clock),
                "draw_policy": "choose" if game_type == "blackjack" else str(state.get("draw_policy") or "tie_break"),
                "tie_break_seat_nos": [],
                "stood_seats": [],
                HMAC_STATE_KEY: {"seed": seed, "commit": pair_commit(seed)},
            },
            "card-deal",
        )
        return

    if phase == "hitting":
        deadline = parse_deadline(state)
        stood = stood_seats_from_state(state)
        seed = _hmac_seed(state)
        try:
            redeal_round = int(state.get("tie_break_round") or 0)
        except (TypeError, ValueError):
            redeal_round = 0
        by_seat = _roster_by_seat(roster)
        changed = False
        for seat_no in seat_nos:
            cards = list(hands.get(seat_no) or [])
            seat = by_seat.get(seat_no) or {}
            if str(seat.get("participant_kind") or "") == "bot" and seed and seat_no not in stood:
                hands[seat_no] = auto_hit_blackjack_to_seventeen(
                    seed,
                    table_id,
                    cards,
                    seat_no=seat_no,
                    nonce=redeal_round,
                )
                stood.add(seat_no)
                changed = True
        if deadline and clock >= deadline:
            for seat_no in seat_nos:
                if _blackjack_can_act(seat_no, hands, stood):
                    stood.add(seat_no)
                    changed = True
        if changed:
            from casino_cards import blackjack_hand_score

            state = {**state, "stood_seats": sorted(stood)}
            await _persist_patch(
                conn,
                table_id,
                version,
                {
                    "hands": json_hands(hands),
                    "stood_seats": sorted(stood),
                    "scores": json_scores({seat: blackjack_hand_score(cards) for seat, cards in hands.items()}),
                },
                "bj-auto-stand",
            )
            row = await _reload_row(conn, table_id)
            state = _as_map(row.get("game_state"))
            version = int(row.get("state_version") or 0)
            hands = hands_from_state(state)
            stood = stood_seats_from_state(state)
        action = next_card_table_action(
            game_type,
            hands,
            now=clock,
            dealt_at=_parse_iso(state.get("cards_dealt_at")),
            roster_has_human=_roster_has_human(roster),
            phase="hitting",
            stood_seats=stood,
        )
        if action["kind"] == "hitting":
            if deadline is None or clock >= deadline:
                new_deadline = clock + timedelta(seconds=blackjack_hit_timeout_seconds(row, state))
                await _persist_patch(
                    conn,
                    table_id,
                    version,
                    {"roll_deadline_at": _iso(new_deadline)},
                    "bj-hit-deadline",
                )
            return
        winners = [int(seat) for seat in list(action.get("winners") or [])]
        if action["kind"] == "settle":
            await _settle_blackjack_outcome(
                conn,
                table_id,
                version=version,
                kind=str(action.get("outcome_kind") or "tie_split"),
                winners=winners,
            )
            return
        scores = action.get("scores") if isinstance(action.get("scores"), dict) else {}
        draw_deadline = clock + timedelta(seconds=WEB_V2_DRAW_CHOICE_TIMEOUT_SECONDS)
        await _persist_patch(
            conn,
            table_id,
            version,
            {
                "phase": "draw_choice",
                "tie_break_seat_nos": winners,
                "scores": json_scores(scores) if scores else state.get("scores"),
                "hands": json_hands(hands),
                "draw_choice_deadline_at": _iso(draw_deadline),
                "roll_deadline_at": None,
                "draw_policy": "choose",
            },
            "bj-draw-choice",
        )
        return

    action = next_card_table_action(
        game_type,
        hands,
        now=clock,
        dealt_at=_parse_iso(state.get("cards_dealt_at")),
        roster_has_human=_roster_has_human(roster),
        phase=phase,
    )
    if action["kind"] == "wait_reveal":
        return
    if action["kind"] == "hitting":
        seed = _hmac_seed(state)
        try:
            redeal_round = int(state.get("tie_break_round") or 0)
        except (TypeError, ValueError):
            redeal_round = 0
        stood: set[int] = set()
        by_seat = _roster_by_seat(roster)
        if seed:
            for seat_no in seat_nos:
                seat = by_seat.get(seat_no) or {}
                if str(seat.get("participant_kind") or "") == "bot":
                    hands[seat_no] = auto_hit_blackjack_to_seventeen(
                        seed,
                        table_id,
                        list(hands.get(seat_no) or []),
                        seat_no=seat_no,
                        nonce=redeal_round,
                    )
                    stood.add(seat_no)
        scores = action.get("scores") if isinstance(action.get("scores"), dict) else {}
        deadline = clock + timedelta(seconds=blackjack_hit_timeout_seconds(row, state))
        await _persist_patch(
            conn,
            table_id,
            version,
            {
                "phase": "hitting",
                "hands": json_hands(hands),
                "scores": json_scores(scores) if scores else {},
                "stood_seats": sorted(stood),
                "roll_deadline_at": _iso(deadline),
            },
            "bj-hitting",
        )
        return
    winners = [int(seat) for seat in list(action.get("winners") or [])]
    if action["kind"] == "settle":
        await _settle_blackjack_outcome(
            conn,
            table_id,
            version=version,
            kind=str(action.get("outcome_kind") or "tie_split"),
            winners=winners,
        )
        return
    if action["kind"] == "redeal":
        await _redeal_card_leaders(
            conn,
            table_id,
            version=version,
            game_type=game_type,
            state={**state, "hands": json_hands(hands)},
            leaders=winners,
            scores=action.get("scores") if isinstance(action.get("scores"), dict) else {},
        )
        return

    deadline = clock + timedelta(seconds=WEB_V2_DRAW_CHOICE_TIMEOUT_SECONDS)
    scores = action.get("scores") if isinstance(action.get("scores"), dict) else {}
    await _persist_patch(
        conn,
        table_id,
        version,
        {
            "phase": "draw_choice",
            "tie_break_seat_nos": winners,
            "scores": json_scores(scores) if scores else state.get("scores"),
            "hands": json_hands(hands),
            "draw_choice_deadline_at": _iso(deadline),
            "draw_policy": "choose",
        },
        "bj-draw-choice",
    )


async def choose_draw_web_table(conn, table_id: str, body: V2WebDrawChoiceBody, *, viewer_id: int) -> dict[str, Any]:
    from routers.internal_casino import _v2_table_response_with_conn

    ensure_closer()
    row = await _reload_row(conn, table_id)
    game_type = str(row.get("game_type") or "")
    if not is_web_card_table(game_type):
        raise HTTPException(status_code=409, detail="Выбор ничьей недоступен")
    if str(row["status"]) not in PLAY_STATUSES:
        raise HTTPException(status_code=409, detail="Выбор ничьей недоступен")
    if int(row.get("state_version") or 0) != body.expected_state_version:
        raise HTTPException(status_code=409, detail="Стол изменился. Обновите и повторите.")
    state = _as_map(row.get("game_state"))
    if str(state.get("phase") or "") != "draw_choice":
        raise HTTPException(status_code=409, detail="Выбор ничьей недоступен")
    payload = await _v2_table_response_with_conn(conn, row)
    roster = list(payload.get("roster") or [])
    seat = next(
        (
            item
            for item in roster
            if item.get("participant_kind") == "player" and int(item.get("telegram_id") or 0) == int(viewer_id)
        ),
        None,
    )
    if not seat:
        raise HTTPException(status_code=403, detail="Only seated players may choose the draw")
    leaders: list[int] = []
    for raw in list(state.get("tie_break_seat_nos") or []):
        try:
            leaders.append(int(raw))
        except (TypeError, ValueError):
            continue
    leaders = sorted(set(leaders))
    if len(leaders) < 2:
        raise HTTPException(status_code=409, detail="Выбор ничьей недоступен")
    version = body.expected_state_version
    if body.choice == "tie_split":
        await _settle_blackjack_outcome(conn, table_id, version=version, kind="tie_split", winners=leaders)
        view = await load_public_table(conn, table_id, viewer_id)
        return {"success": True, "table_id": table_id, "table": view, "choice": "tie_split"}

    await _redeal_card_leaders(
        conn,
        table_id,
        version=version,
        game_type=game_type,
        state=state,
        leaders=leaders,
        scores=state.get("scores") if isinstance(state.get("scores"), dict) else {},
    )
    view = await load_public_table(conn, table_id, viewer_id)
    return {"success": True, "table_id": table_id, "table": view, "choice": "redeal"}


async def maybe_score(conn, table_id: str) -> None:
    from routers.internal_casino import (
        V2TableCommitOutcomeRequest,
        V2TableSettleCommittedRequest,
        _v2_table_response_with_conn,
        commit_v2_table_outcome_with_conn,
        settle_committed_v2_table_with_conn,
    )

    row = await _reload_row(conn, table_id)
    if str(row["status"]) not in PLAY_STATUSES:
        return
    payload = await _v2_table_response_with_conn(conn, row)
    roster = list(payload.get("roster") or [])
    state = _as_map(row.get("game_state"))
    decision = scoring_decision(state, roster)
    if not decision:
        return
    version = int(row.get("state_version") or 0)
    kind = str(decision["kind"])
    winners = list(decision["winner_seat_nos"])
    try:
        committed = await commit_v2_table_outcome_with_conn(
            conn,
            table_id,
            V2TableCommitOutcomeRequest(
                expected_state_version=version,
                idempotency_key=web_idempotency("commit", table_id, version),
                outcome_kind=kind,  # type: ignore[arg-type]
                winner_seat_nos=winners,
            ),
        )
    except HTTPException as exc:
        _catch_v2(exc)
    table = committed.get("table") if isinstance(committed, dict) else None
    if not isinstance(table, dict):
        return
    if kind == "tie_break" or committed.get("tie_break"):
        cleared = tie_break_state(_as_map(table.get("game_state")), winners)
        deadline = datetime.now(timezone.utc) + timedelta(seconds=WEB_V2_ROLL_TIMEOUT_SECONDS)
        next_table = await _persist_patch(
            conn,
            table_id,
            int(table.get("state_version") or 0),
            {
                "phase": "tie_break",
                "rolls": cleared.get("rolls") or {},
                "tie_break_seat_nos": winners,
                "tie_break_round": cleared.get("tie_break_round"),
                "roll_deadline_at": _iso(deadline),
            },
            "tie-break",
        )
        seed = _hmac_seed(_as_map(next_table.get("game_state")))
        if seed:
            filled = fill_hmac_rolls(
                _as_map(next_table.get("game_state")),
                list(next_table.get("roster") or roster),
                table_id=table_id,
                seed=seed,
                kinds=frozenset({"bot"}),
            )
            if filled.get("rolls") != (_as_map(next_table.get("game_state")).get("rolls") or {}):
                await _persist_patch(
                    conn,
                    table_id,
                    int(next_table.get("state_version") or 0),
                    {"rolls": filled["rolls"], "phase": filled.get("phase")},
                    "tie-bots",
                )
        return
    try:
        await settle_committed_v2_table_with_conn(
            conn,
            table_id,
            V2TableSettleCommittedRequest(
                expected_state_version=int(table.get("state_version") or 0),
                idempotency_key=web_idempotency("settle", table_id, int(table.get("state_version") or 0)),
            ),
        )
    except HTTPException as exc:
        _catch_v2(exc)


async def house_fill_table(conn, table_id: str, *, now: datetime | None = None) -> None:
    row = await _reload_row(conn, table_id)
    if str(row["status"]) not in PLAY_STATUSES:
        return
    if is_web_card_table(row.get("game_type")):
        await ensure_blackjack_round(conn, table_id, now=now)
        return
    state = _as_map(row.get("game_state"))
    if telegram_play_surface(row, state):
        return
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    deadline = effective_roll_deadline(row, state)
    if deadline is None or clock < deadline:
        return
    await ensure_round_ready(conn, table_id)
    row = await _reload_row(conn, table_id)
    if str(row["status"]) not in PLAY_STATUSES:
        return
    from routers.internal_casino import _v2_table_response_with_conn

    payload = await _v2_table_response_with_conn(conn, row)
    roster = list(payload.get("roster") or [])
    state = _as_map(row.get("game_state"))
    seed = _hmac_seed(state)
    if not seed:
        return
    filled = fill_hmac_rolls(
        state,
        roster,
        table_id=table_id,
        seed=seed,
        kinds=frozenset({"player", "bot"}),
        house=True,
    )
    if filled.get("rolls") == (state.get("rolls") or {}):
        await maybe_score(conn, table_id)
        return
    await _persist_patch(
        conn,
        table_id,
        int(row.get("state_version") or 0),
        {"rolls": filled["rolls"], "phase": filled.get("phase"), "house_rolled": filled.get("house_rolled") or []},
        "house-fill",
    )
    await maybe_score(conn, table_id)


async def house_fill_due(conn, *, now: datetime | None = None) -> int:
    rows = await conn.fetch(
        """
        SELECT table_id FROM casino_v2_tables
        WHERE status = ANY($1::text[]) AND game_type = ANY($2::text[])
        ORDER BY updated_at ASC
        LIMIT 20
        """,
        list(PLAY_STATUSES),
        list(WEB_V2_GAME_TYPES),
    )
    filled = 0
    for row in rows:
        table_id = str(row["table_id"])
        try:
            async with conn.transaction():
                before = await _reload_row(conn, table_id)
                await house_fill_table(conn, table_id, now=now)
                after = await conn.fetchrow(
                    "SELECT status, state_version FROM casino_v2_tables WHERE table_id=$1",
                    table_id,
                )
                if after and (
                    int(after["state_version"]) != int(before.get("state_version") or 0)
                    or str(after["status"]) != str(before.get("status"))
                ):
                    filled += 1
        except Exception:
            logger.exception("v2 house fill %s", table_id)
    return filled


async def auto_join_due(conn, *, now: datetime | None = None) -> int:
    """Open tables wait for a person. A bot sits only when a seated player adds one."""
    del conn, now
    return 0


async def start_due(conn, *, now: datetime | None = None) -> int:
    clock = now or datetime.now(timezone.utc)
    rows = await conn.fetch(
        """
        SELECT table_id FROM casino_v2_tables
        WHERE status = 'ready'
          AND COALESCE(game_state->>'starts_at', '') <> ''
        ORDER BY updated_at ASC
        LIMIT 20
        """
    )
    started = 0
    for row in rows:
        table_id = str(row["table_id"])
        try:
            async with conn.transaction():
                table = await _reload_row(conn, table_id)
                if str(table.get("status") or "") != "ready":
                    continue
                raw = _as_map(table.get("game_state")).get("starts_at")
                if not raw:
                    continue
                try:
                    ends = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ends.tzinfo is None:
                    ends = ends.replace(tzinfo=timezone.utc)
                if ends > clock:
                    continue
                state = _as_map(table.get("game_state"))
                state.pop("starts_at", None)
                promoted = await conn.fetchrow(
                    """
                    UPDATE casino_v2_tables
                    SET status='running', started_at=now(), state_version=state_version+1,
                        game_state=$2::jsonb, updated_at=now()
                    WHERE table_id=$1 AND status='ready'
                    RETURNING *
                    """,
                    table_id,
                    json.dumps(state, separators=(",", ":")),
                )
                if not promoted:
                    continue
                await ensure_round_ready(conn, table_id)
                started += 1
        except Exception:
            logger.exception("v2 start %s", table_id)
    return started


def ensure_closer() -> None:
    global _closer_started
    if _closer_started:
        return
    _closer_started = True
    asyncio.create_task(_closer_loop())
    from casino_waiting import ensure_closer as waiting_ensure_closer

    waiting_ensure_closer()


async def _closer_loop() -> None:
    from db import get_pool

    while True:
        await asyncio.sleep(1)
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await start_due(conn)
                    await house_fill_due(conn)
                    from routers.internal_casino import expire_stale_v2_play_with_conn

                    await expire_stale_v2_play_with_conn(conn)
        except Exception:
            logger.exception("v2 web dice closer")


async def create_web_table(conn, body: V2WebCreateBody, *, viewer_id: int) -> dict[str, Any]:
    from routers.internal_casino import V2TableCreateRequest, V2TableJoinRequest, create_v2_table_with_conn, join_v2_table_with_conn

    ensure_closer()
    stake = money(body.stake_rub)
    if body.autojoin:
        scope_and = await scope_filter_for(
            conn, "casino_v2_tables", await viewer_scope(conn, viewer_id)
        )
        waiting = await conn.fetch(
            f"""
            SELECT * FROM casino_v2_tables
            WHERE game_type=$1 AND status='open' AND stake_rub=$2{scope_and}
            ORDER BY created_at ASC
            LIMIT 20
            """,
            body.game_type,
            stake,
        )
        for row in waiting:
            if int(row["creator_id"]) == viewer_id:
                continue
            table_id = str(row["table_id"])
            version = int(row.get("state_version") or 0)
            try:
                joined = await join_v2_table_with_conn(
                    conn,
                    table_id,
                    V2TableJoinRequest(
                        telegram_id=viewer_id,
                        expected_state_version=version,
                        idempotency_key=web_idempotency("join", table_id, version, viewer_id),
                    ),
                )
            except HTTPException:
                continue
            if joined.get("auto_started"):
                await ensure_round_ready(conn, table_id)
            view = await load_public_table(conn, table_id, viewer_id)
            return {"success": True, "joined": True, "created": False, "table_id": table_id, "table": view}
    table_id = f"web-{uuid4().hex[:16]}"
    try:
        created = await create_v2_table_with_conn(
            conn,
            V2TableCreateRequest(
                table_id=table_id,
                game_type=body.game_type,
                creator_id=viewer_id,
                stake_rub=stake,
                max_players=body.max_seats,
                bot_count=body.bot_count,
                expected_state_version=0,
                idempotency_key=web_idempotency("create", table_id, 0, viewer_id),
                draw_policy="tie_split" if is_web_card_table(body.game_type) else "tie_break",
                rounds=1,
            ),
        )
    except HTTPException as exc:
        _catch_v2(exc)
    if created.get("auto_started"):
        await ensure_round_ready(conn, table_id)
    view = await load_public_table(conn, table_id, viewer_id)
    if str(view.get("status") or "") in {"open", "ready"}:
        from casino_open_alerts import enqueue_open_table_alerts

        await enqueue_open_table_alerts(
            conn,
            game_id=table_id,
            game_type=body.game_type,
            creator_id=viewer_id,
            stake_rub=stake,
            seats=int(body.max_seats),
            href=f"/casino/tables/{table_id}",
        )
    return {"success": True, "joined": False, "created": True, "table_id": table_id, "table": view}


async def join_web_table(conn, table_id: str, body: V2WebVersionBody, *, viewer_id: int) -> dict[str, Any]:
    from routers.internal_casino import V2TableJoinRequest, join_v2_table_with_conn

    ensure_closer()
    try:
        result = await join_v2_table_with_conn(
            conn,
            table_id,
            V2TableJoinRequest(
                telegram_id=viewer_id,
                expected_state_version=body.expected_state_version,
                idempotency_key=web_idempotency("join", table_id, body.expected_state_version, viewer_id),
            ),
        )
    except HTTPException as exc:
        _catch_v2(exc)
    if result.get("auto_started"):
        await ensure_round_ready(conn, table_id)
    view = await load_public_table(conn, table_id, viewer_id)
    return {"success": True, "joined": True, "table_id": table_id, "table": view, "auto_started": bool(result.get("auto_started"))}


async def add_web_bot(conn, table_id: str, body: V2WebVersionBody, *, viewer_id: int) -> dict[str, Any]:
    from routers.internal_casino import V2TableAddBotRequest, add_v2_bot_with_conn

    ensure_closer()
    try:
        result = await add_v2_bot_with_conn(
            conn,
            table_id,
            V2TableAddBotRequest(
                telegram_id=viewer_id,
                expected_state_version=body.expected_state_version,
                idempotency_key=web_idempotency("add-bot", table_id, body.expected_state_version, viewer_id),
            ),
        )
    except HTTPException as exc:
        _catch_v2(exc)
    if result.get("auto_started"):
        await ensure_round_ready(conn, table_id)
    view = await load_public_table(conn, table_id, viewer_id)
    return {
        "success": True,
        "table_id": table_id,
        "table": view,
        "auto_started": bool(result.get("auto_started")),
    }


async def start_web_table(conn, table_id: str, body: V2WebVersionBody, *, viewer_id: int) -> dict[str, Any]:
    from routers.internal_casino import V2TableStartRequest, start_v2_table_with_conn

    ensure_closer()
    try:
        await start_v2_table_with_conn(
            conn,
            table_id,
            V2TableStartRequest(
                creator_id=viewer_id,
                expected_state_version=body.expected_state_version,
                idempotency_key=web_idempotency("start", table_id, body.expected_state_version, viewer_id),
            ),
        )
    except HTTPException as exc:
        _catch_v2(exc)
    await ensure_round_ready(conn, table_id)
    view = await load_public_table(conn, table_id, viewer_id)
    return {"success": True, "table_id": table_id, "table": view}


async def leave_web_table(conn, table_id: str, body: V2WebVersionBody, *, viewer_id: int, cancel: bool) -> dict[str, Any]:
    from routers.internal_casino import V2TableLeaveRequest, leave_v2_table_with_conn

    try:
        await leave_v2_table_with_conn(
            conn,
            table_id,
            V2TableLeaveRequest(
                telegram_id=viewer_id,
                expected_state_version=body.expected_state_version,
                idempotency_key=web_idempotency("cancel" if cancel else "leave", table_id, body.expected_state_version, viewer_id),
            ),
            cancel=cancel,
        )
    except HTTPException as exc:
        _catch_v2(exc)
    view = await load_public_table(conn, table_id, viewer_id)
    return {"success": True, "table_id": table_id, "table": view}


async def roll_web_table(conn, table_id: str, body: V2WebVersionBody, *, viewer_id: int) -> dict[str, Any]:
    from routers.internal_casino import _v2_table_response_with_conn

    ensure_closer()
    await ensure_round_ready(conn, table_id)
    row = await _reload_row(conn, table_id)
    if is_web_card_table(row.get("game_type")):
        raise HTTPException(status_code=409, detail="В этой игре за столом бросок не нужен")
    if str(row["status"]) not in PLAY_STATUSES:
        raise HTTPException(status_code=409, detail="Стол уже не принимает броски")
    if int(row.get("state_version") or 0) != body.expected_state_version:
        raise HTTPException(status_code=409, detail="Стол изменился. Обновите и повторите.")
    payload = await _v2_table_response_with_conn(conn, row)
    roster = list(payload.get("roster") or [])
    seat = next(
        (
            item
            for item in roster
            if item.get("participant_kind") == "player" and int(item.get("telegram_id") or 0) == int(viewer_id)
        ),
        None,
    )
    if not seat:
        raise HTTPException(status_code=403, detail="Бросок только для участников")
    seat_no = int(seat["seat_no"])
    state = _as_map(row.get("game_state"))
    seed = _hmac_seed(state)
    if not seed:
        raise HTTPException(status_code=409, detail="HMAC сид ещё не готов")
    required = required_rolls(state)
    active = occupied_seat_nos(state, roster)
    if seat_no not in active:
        raise HTTPException(status_code=409, detail="Сейчас бросают другие места")
    index = missing_roll_index(state.get("rolls") if isinstance(state.get("rolls"), dict) else {}, seat_no, required)
    if index is None:
        await maybe_score(conn, table_id)
        view = await load_public_table(conn, table_id, viewer_id)
        return {"success": True, "idempotent": True, "table_id": table_id, "table": view}
    pip = hmac_face(seed=seed, table_id=table_id, seat_no=seat_no, index=hmac_index(state, index), kind="player")
    try:
        next_state = apply_roll(state, seat_no=seat_no, roll_index=index, value=pip, required=required)
    except ValueError:
        view = await load_public_table(conn, table_id, viewer_id)
        return {"success": True, "idempotent": True, "table_id": table_id, "table": view}
    await _persist_patch(
        conn,
        table_id,
        body.expected_state_version,
        {"rolls": next_state["rolls"], "phase": next_state.get("phase")},
        "player-roll",
    )
    await maybe_score(conn, table_id)
    view = await load_public_table(conn, table_id, viewer_id)
    return {"success": True, "idempotent": False, "table_id": table_id, "table": view, "pips": pip}


async def _blackjack_player_action(
    conn,
    table_id: str,
    body: V2WebVersionBody,
    *,
    viewer_id: int,
    action: str,
) -> dict[str, Any]:
    from casino_house_cards import hit_blackjack_hand
    from casino_v2_cards import hands_from_state, json_hands, stood_seats_from_state
    from routers.internal_casino import _v2_table_response_with_conn

    ensure_closer()
    await ensure_blackjack_round(conn, table_id)
    row = await _reload_row(conn, table_id)
    if str(row.get("game_type") or "") != "blackjack":
        raise HTTPException(status_code=409, detail=f"Blackjack {action} is not available")
    if str(row["status"]) not in PLAY_STATUSES:
        raise HTTPException(status_code=409, detail=f"Blackjack {action} is not available")
    if int(row.get("state_version") or 0) != body.expected_state_version:
        raise HTTPException(status_code=409, detail="Стол изменился. Обновите и повторите.")
    state = _as_map(row.get("game_state"))
    if str(state.get("phase") or "") != "hitting":
        raise HTTPException(status_code=409, detail=f"Blackjack {action} is not available")
    payload = await _v2_table_response_with_conn(conn, row)
    roster = list(payload.get("roster") or [])
    seat = _viewer_seat(roster, viewer_id)
    if not seat:
        raise HTTPException(status_code=403, detail="Only seated players may act on blackjack")
    seat_no = int(seat["seat_no"])
    hands = hands_from_state(state)
    stood = stood_seats_from_state(state)
    if not _blackjack_can_act(seat_no, hands, stood):
        view = await load_public_table(conn, table_id, viewer_id)
        return {"success": True, "idempotent": True, "table_id": table_id, "table": view, "action": action}
    seed = _hmac_seed(state)
    if not seed:
        raise HTTPException(status_code=409, detail="HMAC сид ещё не готов")
    try:
        redeal_round = int(state.get("tie_break_round") or 0)
    except (TypeError, ValueError):
        redeal_round = 0
    clock = datetime.now(timezone.utc)
    if action == "hit":
        from casino_v2_cards import blackjack_seat_done

        cards = hit_blackjack_hand(
            seed,
            table_id,
            f"seat{seat_no}",
            list(hands.get(seat_no) or []),
            nonce=redeal_round,
        )
        hands[seat_no] = cards
        seat_done = blackjack_seat_done(cards, stood=False)
        if seat_done:
            stood.add(seat_no)
        patch: dict[str, Any] = {
            "hands": json_hands(hands),
            "stood_seats": sorted(stood),
            "decisions": blackjack_web_decisions(state, seat_no=seat_no, mark_stand=seat_done),
            "roll_deadline_at": _iso(clock + timedelta(seconds=blackjack_hit_timeout_seconds(row, state))),
        }
        await _persist_patch(conn, table_id, body.expected_state_version, patch, "bj-hit")
    else:
        stood.add(seat_no)
        await _persist_patch(
            conn,
            table_id,
            body.expected_state_version,
            {
                "stood_seats": sorted(stood),
                "decisions": blackjack_web_decisions(state, seat_no=seat_no, mark_stand=True),
            },
            "bj-stand",
        )
    row = await _reload_row(conn, table_id)
    state = _as_map(row.get("game_state"))
    hands = hands_from_state(state)
    await _finalize_blackjack_action(
        conn,
        table_id,
        game_type="blackjack",
        version=int(row.get("state_version") or 0),
        hands=hands,
        state=state,
        roster=roster,
        clock=clock,
        table=row,
    )
    view = await load_public_table(conn, table_id, viewer_id)
    return {"success": True, "table_id": table_id, "table": view, "action": action}


async def hit_web_table(conn, table_id: str, body: V2WebVersionBody, *, viewer_id: int) -> dict[str, Any]:
    return await _blackjack_player_action(conn, table_id, body, viewer_id=viewer_id, action="hit")


async def stand_web_table(conn, table_id: str, body: V2WebVersionBody, *, viewer_id: int) -> dict[str, Any]:
    return await _blackjack_player_action(conn, table_id, body, viewer_id=viewer_id, action="stand")
