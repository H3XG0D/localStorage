"""Pure V2 table gameplay helpers for Telegram DM rounds.

Backend remains the source of truth for money and lifecycle. This module only
derives seat-scoped roll state, leader detection, and tie-break transitions
from versioned game_state snapshots.
"""
from __future__ import annotations

from typing import Any, Iterable


def occupied_seats(roster: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seats = [seat for seat in roster if isinstance(seat, dict) and seat.get("status", "seated") == "seated"]
    return sorted(seats, key=lambda seat: int(seat.get("seat_no", 0)))


def required_roll_count(game_type: str, *, configured_rolls: int | None = None) -> int:
    if configured_rolls is not None:
        return max(1, int(configured_rolls))
    return 2 if str(game_type).startswith("2") else 1


def seat_roll_key(seat_no: int, roll_index: int) -> str:
    return f"s{int(seat_no)}r{int(roll_index)}"


def occupied_seat_nos(game_state: dict[str, Any]) -> list[int]:
    leaders = game_state.get("tie_break_seat_nos")
    if isinstance(leaders, list) and leaders:
        return [int(seat_no) for seat_no in leaders]
    roster = game_state.get("roster")
    if isinstance(roster, list):
        return [int(seat["seat_no"]) for seat in occupied_seats(roster)]
    seat_nos = game_state.get("seat_nos")
    if isinstance(seat_nos, list):
        return [int(seat_no) for seat_no in seat_nos]
    return []


def apply_roll(
    game_state: dict[str, Any],
    *,
    seat_no: int,
    roll_index: int,
    value: int,
    required_rolls: int,
) -> dict[str, Any]:
    state = dict(game_state or {})
    rolls = dict(state.get("rolls") or {})
    key = seat_roll_key(seat_no, roll_index)
    if key in rolls:
        raise ValueError("roll already recorded")
    if roll_index < 0 or roll_index >= required_rolls:
        raise ValueError("roll index out of range")
    rolls[key] = int(value)
    state["rolls"] = rolls
    complete = all_rolls_complete(rolls, occupied_seat_nos(state), required_rolls)
    in_tie_break = bool(state.get("tie_break_seat_nos")) or state.get("phase") == "tie_break"
    if in_tie_break:
        state["phase"] = "scoring" if complete else "tie_break"
    else:
        state["phase"] = "scoring" if complete else "rolling"
    return state


def all_rolls_complete(rolls: dict[str, Any], seat_nos: Iterable[int], required_rolls: int) -> bool:
    for seat_no in seat_nos:
        for roll_index in range(required_rolls):
            if seat_roll_key(seat_no, roll_index) not in rolls:
                return False
    return True


def seat_totals(rolls: dict[str, Any], seat_nos: Iterable[int], required_rolls: int) -> dict[int, int]:
    totals: dict[int, int] = {}
    for seat_no in seat_nos:
        total = 0
        for roll_index in range(required_rolls):
            total += int(rolls[seat_roll_key(seat_no, roll_index)])
        totals[int(seat_no)] = total
    return totals


def leader_seat_nos(totals: dict[int, int]) -> list[int]:
    if not totals:
        return []
    best = max(totals.values())
    return sorted(seat_no for seat_no, total in totals.items() if total == best)


def outcome_kind_for_totals(totals: dict[int, int]) -> str:
    leaders = leader_seat_nos(totals)
    if len(leaders) == 1:
        return "winner"
    return "tie_break"


def tie_break_state(game_state: dict[str, Any], leaders: list[int]) -> dict[str, Any]:
    state = dict(game_state or {})
    state["phase"] = "tie_break"
    state["tie_break_round"] = int(state.get("tie_break_round") or 0) + 1
    state["tie_break_seat_nos"] = list(leaders)
    rolls = dict(state.get("rolls") or {})
    for seat_no in leaders:
        prefix = f"s{int(seat_no)}r"
        for key in list(rolls):
            if key.startswith(prefix):
                rolls.pop(key, None)
    state["rolls"] = rolls
    return state
