"""House dice vs casino: one human (solo table) or leftover multi-seat rows.

Players do not share a pot. house_robot seats sit for the house and never debit
user wallets. Fast 1×1 still uses HMAC cub (`play_cub_with_conn`). Solo table 2–6
compares HMAC d6 faces: lose to any bot → 0; beat all → ×(N+1); ties (no losses)
→ take ×(K+1) for K wins or one reroll (×2 on locked wins plus usual for new).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Awaitable, Callable, Literal, Mapping, Sequence
from uuid import uuid4

from fastapi import HTTPException

from casino_cub_faces import cub_presentation_pips
from casino_duels import bot_chip
from casino_finance import (
    allocate_commission,
    calculate_equal_stake_settlement,
    calculate_house_settlement,
    casino_ledger_order_ref,
    commission_shares_for_rate,
    confirm_unified_hold,
    load_casino_settings,
    lock_casino_game,
    lock_casino_users,
    money,
    reserve_unified_funds,
)
from casino_play import house_bots_cub_odds, load_cub_play_quote, stake_bound_error

GAME_TYPE = "pvp_dice"
HOUSE_MONEY_GAME = "cub"
MIN_HUMANS = 1
MIN_START_HUMANS = 1
MAX_HUMANS = 6
SOLO_MAX_SEATS = 1
MIN_HOUSE_BOTS = 0
MAX_HOUSE_BOTS = 6
HUMAN_SEAT_MIN = 1
HUMAN_SEAT_MAX = 6
HOUSE_BOT_SEAT_BASE = 11
CUB_HMAC_MESSAGE_TEMPLATE = "{game_id}:{nonce}"
MIN_HOUSE_BOTS_FOR_FACE = 2

SeatKind = Literal["player", "house_robot"]
PlayHumanCub = Callable[..., Awaitable[Mapping[str, Any]]]
ChoiceAction = Literal["take", "reroll"]


@dataclass(frozen=True)
class HouseSeatSpec:
    seat_no: int
    kind: SeatKind
    telegram_id: int | None
    stake_rub: Decimal
    display_name: str = ""
    profile_key: str | None = None
    player_pips: int | None = None
    house_pips: int | None = None
    payout_rub: Decimal | None = None
    commission_rub: Decimal | None = None
    won: bool | None = None
    cub_game_id: str | None = None


@dataclass(frozen=True)
class SeatHouseSettlement:
    stake_rub: Decimal
    won: bool
    payout_rub: Decimal
    commission_rub: Decimal
    house_delta_rub: Decimal


@dataclass(frozen=True)
class DiceCompare:
    player_pips: int
    win_seats: tuple[int, ...]
    tie_seats: tuple[int, ...]
    lose_seats: tuple[int, ...]

    @property
    def wins(self) -> int:
        return len(self.win_seats)

    @property
    def ties(self) -> int:
        return len(self.tie_seats)

    @property
    def losses(self) -> int:
        return len(self.lose_seats)

    @property
    def kind(self) -> Literal["loss", "win", "choice"]:
        if self.losses:
            return "loss"
        if self.ties:
            return "choice"
        return "win"


def validate_max_seats(max_seats: int) -> int:
    seats = int(max_seats)
    if seats < MIN_HUMANS or seats > MAX_HUMANS:
        raise HTTPException(status_code=400, detail="За столом против казино 1–6 игроков")
    return seats


def _seated_elsewhere_error(table_id: str) -> HTTPException:
    tid = str(table_id)
    return HTTPException(
        status_code=409,
        detail={
            "message": "Сначала встаньте с другого стола против казино",
            "table_id": tid,
            "href": f"/casino/play/pvp_dice?mode=house&view=table&ht={tid}",
        },
    )


def is_solo_table(table: Mapping[str, Any] | int) -> bool:
    # asyncpg.Record is not collections.abc.Mapping — use [] / int, not isinstance(Mapping).
    if isinstance(table, int):
        seats = table
    else:
        seats = int(table["max_seats"] or 0)
    return seats <= SOLO_MAX_SEATS


def validate_house_bot_count(count: int) -> int:
    n = int(count)
    if n < MIN_HOUSE_BOTS or n > MAX_HOUSE_BOTS:
        raise HTTPException(status_code=400, detail="Ботов за казино может быть 0–6")
    return n


def human_seats(seats: Sequence[HouseSeatSpec | Mapping[str, Any]]) -> list[HouseSeatSpec]:
    return [as_seat(row) for row in seats if as_seat(row).kind == "player"]


def house_bot_seats(seats: Sequence[HouseSeatSpec | Mapping[str, Any]]) -> list[HouseSeatSpec]:
    return [as_seat(row) for row in seats if as_seat(row).kind == "house_robot"]


def as_seat(row: HouseSeatSpec | Mapping[str, Any]) -> HouseSeatSpec:
    if isinstance(row, HouseSeatSpec):
        return row
    kind = str(row.get("kind") or "player")
    if kind not in ("player", "house_robot"):
        kind = "player"
    stake = money(row.get("stake_rub") or 0)
    telegram_raw = row.get("telegram_id")
    telegram_id = int(telegram_raw) if telegram_raw not in (None, "") else None
    pips_player = row.get("player_pips")
    pips_house = row.get("house_pips")
    payout = row.get("payout_rub")
    commission = row.get("commission_rub")
    won_raw = row.get("won")
    return HouseSeatSpec(
        seat_no=int(row.get("seat_no") or 0),
        kind=kind,  # type: ignore[arg-type]
        telegram_id=telegram_id,
        stake_rub=stake,
        display_name=str(row.get("display_name") or ""),
        profile_key=str(row.get("profile_key") or "") or None,
        player_pips=int(pips_player) if pips_player is not None else None,
        house_pips=int(pips_house) if pips_house is not None else None,
        payout_rub=money(payout) if payout is not None else None,
        commission_rub=money(commission) if commission is not None else None,
        won=bool(won_raw) if won_raw is not None else None,
        cub_game_id=str(row.get("cub_game_id") or "") or None,
    )


def house_bot_wallet_debit(seat: HouseSeatSpec | Mapping[str, Any]) -> Decimal:
    """Bots for the house never touch a user wallet."""
    spec = as_seat(seat)
    if spec.kind != "house_robot":
        raise ValueError("house_bot_wallet_debit is only for house_robot seats")
    return Decimal("0.00")


def seat_house_settlement(
    stake_rub: Decimal | int | float | str,
    *,
    won: bool,
    payout_multiplier: Decimal | int | float | str = Decimal("2"),
    commission_rate: Decimal | int | float | str = Decimal("5"),
    commission_cap_rub: Decimal | int | float | str = Decimal("0"),
    commission_min_rub: Decimal | int | float | str = Decimal("0"),
) -> SeatHouseSettlement:
    """One human vs house. Same formula as cub: hold stake, pay calculate_house_settlement."""
    stake = money(stake_rub)
    if stake <= 0:
        raise ValueError("Human stake must be positive")
    multiplier = Decimal(str(payout_multiplier)) if won else Decimal("0")
    settlement = calculate_house_settlement(
        stake,
        multiplier,
        commission_rate,
        commission_cap_rub=commission_cap_rub,
        commission_min_rub=commission_min_rub,
    )
    return SeatHouseSettlement(
        stake_rub=stake,
        won=bool(won),
        payout_rub=settlement.payout,
        commission_rub=settlement.commission,
        house_delta_rub=settlement.house_delta,
    )


def table_win_reserve(
    human_stakes: Sequence[Decimal | int | float | str],
    *,
    payout_multiplier: Decimal | int | float | str = Decimal("2"),
    commission_rate: Decimal | int | float | str = Decimal("5"),
    commission_cap_rub: Decimal | int | float | str = Decimal("0"),
    commission_min_rub: Decimal | int | float | str = Decimal("0"),
) -> Decimal:
    """House must cover the sum of per-seat win payouts. Not a shared pot."""
    total = Decimal("0.00")
    for stake in human_stakes:
        item = seat_house_settlement(
            stake,
            won=True,
            payout_multiplier=payout_multiplier,
            commission_rate=commission_rate,
            commission_cap_rub=commission_cap_rub,
            commission_min_rub=commission_min_rub,
        )
        total = money(total + item.payout_rub)
    return total


def table_settlements(
    results: Sequence[tuple[Decimal | int | float | str, bool]],
    *,
    payout_multiplier: Decimal | int | float | str = Decimal("2"),
    commission_rate: Decimal | int | float | str = Decimal("5"),
    commission_cap_rub: Decimal | int | float | str = Decimal("0"),
    commission_min_rub: Decimal | int | float | str = Decimal("0"),
) -> list[SeatHouseSettlement]:
    return [
        seat_house_settlement(
            stake,
            won=won,
            payout_multiplier=payout_multiplier,
            commission_rate=commission_rate,
            commission_cap_rub=commission_cap_rub,
            commission_min_rub=commission_min_rub,
        )
        for stake, won in results
    ]


def v2_equal_stake_payout(
    stake_each: Decimal | int | float | str,
    commission_rate: Decimal | int | float | str = Decimal("5"),
) -> Decimal:
    """Contrast only: V2 winner-takes-pot. House-multi must not equal this."""
    return calculate_equal_stake_settlement(stake_each, commission_rate).payout


def cub_hmac_outcome(
    seed: str,
    game_id: str,
    nonce: int,
    win_probability: Decimal | int | float | str,
) -> dict[str, object]:
    """Same HMAC-SHA256 cub decision as play_cub: message is game_id:nonce."""
    message = CUB_HMAC_MESSAGE_TEMPLATE.format(game_id=game_id, nonce=int(nonce))
    digest = hmac.new(seed.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    digest_value = int.from_bytes(digest.digest(), "big")
    probability = Decimal(str(win_probability))
    threshold = int((probability * Decimal(1 << 256)).to_integral_value())
    won = digest_value < threshold
    player_pips, house_pips = cub_presentation_pips(digest_value, won=won)
    return {
        "message": message,
        "digest_hex": digest.hexdigest(),
        "digest_value": digest_value,
        "threshold": str(threshold),
        "won": won,
        "player_pips": player_pips,
        "house_pips": house_pips,
        "algorithm": "HMAC-SHA256",
    }


def house_bot_die_pips(seed: str, table_id: str, seat_no: int, nonce: int = 0) -> int:
    """HMAC d6 for a house bot. On solo table 2–6 this face is compared to the player."""
    message = f"{table_id}:house:{int(seat_no)}:{int(nonce)}"
    digest = hmac.new(seed.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return 1 + (int.from_bytes(digest.digest(), "big") % 6)


def player_die_pips(seed: str, table_id: str, seat_no: int, nonce: int = 0) -> int:
    """HMAC d6 for the seated human. Compared to each house bot, not a win-threshold."""
    message = f"{table_id}:player:{int(seat_no)}:{int(nonce)}"
    digest = hmac.new(seed.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return 1 + (int.from_bytes(digest.digest(), "big") % 6)


def compare_dice(player_pips: int, bots: Sequence[tuple[int, int]]) -> DiceCompare:
    """bots is (seat_no, pips). Player must strictly beat a bot to count a win."""
    pips = int(player_pips)
    if pips < 1 or pips > 6:
        raise ValueError("player_pips must be 1–6")
    wins: list[int] = []
    ties: list[int] = []
    losses: list[int] = []
    for seat_no, bot_pips in bots:
        face = int(bot_pips)
        if face < 1 or face > 6:
            raise ValueError("bot pips must be 1–6")
        seat = int(seat_no)
        if pips > face:
            wins.append(seat)
        elif pips == face:
            ties.append(seat)
        else:
            losses.append(seat)
    return DiceCompare(
        player_pips=pips,
        win_seats=tuple(wins),
        tie_seats=tuple(ties),
        lose_seats=tuple(losses),
    )


def uses_face_money(table: Mapping[str, Any] | int, house_bot_count: int | None = None) -> bool:
    """Solo 2–6 vs house: faces decide money. 1×1 cub and leftover multi-seat stay HMAC-threshold."""
    if isinstance(table, int):
        solo = is_solo_table(table)
        bots = int(house_bot_count or 0)
    else:
        solo = is_solo_table(table)
        bots = int(house_bot_count if house_bot_count is not None else (table.get("house_bot_count") or 0))
    return solo and bots >= MIN_HOUSE_BOTS_FOR_FACE


def take_multiplier(win_count: int) -> Decimal:
    """K beaten bots, no losses. K=0 (all ties) returns the stake (×1 push)."""
    wins = max(int(win_count), 0)
    if wins <= 0:
        return Decimal("1")
    odds = house_bots_cub_odds(wins)
    if odds:
        return odds[0]
    return Decimal(wins + 1)


def reroll_win_multiplier(locked_wins: int, new_wins: int) -> Decimal:
    """One reroll: ×2 on locked K plus usual for newly beaten ties. No locked wins → usual only."""
    locked = max(int(locked_wins), 0)
    fresh = max(int(new_wins), 0)
    if locked <= 0:
        return take_multiplier(fresh)
    return Decimal(2 * (locked + 1) + (fresh + 1))


def after_reroll_multiplier(locked_wins: int, result: DiceCompare) -> Decimal:
    if result.losses:
        return Decimal("0")
    if result.ties:
        return take_multiplier(int(locked_wins) + result.wins)
    return reroll_win_multiplier(int(locked_wins), result.wins)


def face_max_multiplier(bot_count: int) -> Decimal:
    """House reserve: beat-all ×(N+1) or best one-reroll win, whichever is larger."""
    n = max(int(bot_count), 0)
    if n < 1:
        return Decimal("2")
    beat_all = take_multiplier(n)
    if n < MIN_HOUSE_BOTS_FOR_FACE:
        return beat_all
    return max(beat_all, reroll_win_multiplier(n - 1, 1))


def payout_for_multiplier(
    stake_rub: Decimal | int | float | str,
    payout_multiplier: Decimal | int | float | str,
    *,
    commission_rate: Decimal | int | float | str = Decimal("5"),
    commission_cap_rub: Decimal | int | float | str = Decimal("0"),
    commission_min_rub: Decimal | int | float | str = Decimal("0"),
) -> SeatHouseSettlement:
    stake = money(stake_rub)
    multiplier = Decimal(str(payout_multiplier))
    if multiplier < 0:
        multiplier = Decimal("0")
    settlement = calculate_house_settlement(
        stake,
        multiplier,
        commission_rate,
        commission_cap_rub=commission_cap_rub,
        commission_min_rub=commission_min_rub,
    )
    return SeatHouseSettlement(
        stake_rub=stake,
        won=multiplier > 1,
        payout_rub=settlement.payout,
        commission_rub=settlement.commission,
        house_delta_rub=settlement.house_delta,
    )


def choice_quote(
    stake_rub: Decimal | int | float | str,
    *,
    wins: int,
    ties: int,
    win_seats: Sequence[int],
    tie_seats: Sequence[int],
    commission_rate: Decimal | int | float | str = Decimal("5"),
    commission_cap_rub: Decimal | int | float | str = Decimal("0"),
    commission_min_rub: Decimal | int | float | str = Decimal("0"),
    can_reroll: bool = True,
) -> dict[str, object]:
    stake = money(stake_rub)
    take_mult = take_multiplier(wins)
    reroll_mult = reroll_win_multiplier(wins, ties)
    take = payout_for_multiplier(
        stake,
        take_mult,
        commission_rate=commission_rate,
        commission_cap_rub=commission_cap_rub,
        commission_min_rub=commission_min_rub,
    )
    reroll = payout_for_multiplier(
        stake,
        reroll_mult,
        commission_rate=commission_rate,
        commission_cap_rub=commission_cap_rub,
        commission_min_rub=commission_min_rub,
    )
    return {
        "wins": int(wins),
        "ties": int(ties),
        "win_seats": [int(n) for n in win_seats],
        "tie_seats": [int(n) for n in tie_seats],
        "take_multiplier": float(take_mult),
        "take_payout_rub": float(take.payout_rub),
        "reroll_multiplier": float(reroll_mult),
        "reroll_payout_rub": float(reroll.payout_rub),
        "can_reroll": bool(can_reroll),
    }


def validate_roster_for_start(seats: Sequence[HouseSeatSpec | Mapping[str, Any]]) -> list[HouseSeatSpec]:
    parsed = [as_seat(row) for row in seats]
    humans = [row for row in parsed if row.kind == "player"]
    bots = [row for row in parsed if row.kind == "house_robot"]
    if len(humans) < MIN_START_HUMANS:
        raise HTTPException(status_code=409, detail="Сядьте за стол")
    if len(humans) > MAX_HUMANS:
        raise HTTPException(status_code=409, detail="Нужно не больше 6 игроков против казино")
    seen: set[int] = set()
    human_nos: set[int] = set()
    for human in humans:
        if human.telegram_id is None or int(human.telegram_id) == 0:
            raise HTTPException(status_code=409, detail="У игрока нет id")
        if human.telegram_id in seen:
            raise HTTPException(status_code=409, detail="Игрок уже за столом")
        seen.add(int(human.telegram_id))
        if human.stake_rub <= 0:
            raise HTTPException(status_code=409, detail="Ставка игрока должна быть больше нуля")
        if human.seat_no < HUMAN_SEAT_MIN or human.seat_no > HUMAN_SEAT_MAX:
            raise HTTPException(status_code=409, detail="Место игрока 1–6")
        if human.seat_no in human_nos:
            raise HTTPException(status_code=409, detail="Место занято")
        human_nos.add(human.seat_no)
    for bot in bots:
        if bot.telegram_id is not None:
            raise HTTPException(status_code=409, detail="Бот казино не привязан к кошельку")
        if bot.stake_rub != Decimal("0.00"):
            raise HTTPException(status_code=409, detail="Бот казино не ставит с баланса игрока")
        if house_bot_wallet_debit(bot) != Decimal("0.00"):
            raise HTTPException(status_code=409, detail="Бот казино не ставит с баланса игрока")
    return parsed


def next_human_seat_no(occupied: Sequence[int], max_seats: int) -> int:
    taken = {int(n) for n in occupied}
    for seat in range(HUMAN_SEAT_MIN, int(max_seats) + 1):
        if seat not in taken:
            return seat
    raise HTTPException(status_code=409, detail="Стол заполнен")


def canvas_dice(seats: Sequence[HouseSeatSpec | Mapping[str, Any]]) -> dict[str, list[dict[str, object]]]:
    """N player dice + house die/dice. Money is HMAC cub, faces illustrate."""
    parsed = [as_seat(row) for row in seats]
    players: list[dict[str, object]] = []
    house: list[dict[str, object]] = []
    for row in sorted(parsed, key=lambda item: item.seat_no):
        if row.kind == "player":
            players.append(
                {
                    "seat_no": row.seat_no,
                    "kind": "player",
                    "label": row.display_name or f"Игрок {row.telegram_id}",
                    "telegram_id": row.telegram_id,
                    "pips": row.player_pips,
                    "stake_rub": float(row.stake_rub),
                    "payout_rub": float(row.payout_rub) if row.payout_rub is not None else None,
                    "won": row.won,
                }
            )
        else:
            house.append(
                {
                    "seat_no": row.seat_no,
                    "kind": "house_robot",
                    "label": row.display_name or "Казино",
                    "pips": row.house_pips,
                    "stake_rub": 0.0,
                    "profile_key": row.profile_key,
                }
            )
    if not house:
        fallback = next((row.house_pips for row in parsed if row.kind == "player" and row.house_pips), None)
        house.append(
            {
                "seat_no": HOUSE_BOT_SEAT_BASE,
                "kind": "house_robot",
                "label": "Казино",
                "pips": fallback,
                "stake_rub": 0.0,
                "profile_key": None,
            }
        )
    return {"players": players, "house": house}


def public_table_card(table: Mapping[str, Any], seats: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    humans = [row for row in seats if str(row.get("kind")) == "player"]
    bots = [row for row in seats if str(row.get("kind")) == "house_robot"]
    return {
        "table_id": str(table.get("table_id") or ""),
        "game_type": str(table.get("game_type") or GAME_TYPE),
        "status": str(table.get("status") or "open"),
        "max_seats": int(table.get("max_seats") or MAX_HUMANS),
        "human_count": len(humans),
        "house_bot_count": len(bots),
        "state_version": int(table.get("state_version") or 0),
        "free_seats": max(0, int(table.get("max_seats") or 0) - len(humans)),
    }


def build_snapshot(
    table: Mapping[str, Any],
    seats: Sequence[Mapping[str, Any]],
    actors: Mapping[int, Mapping[str, Any]] | None,
    viewer_id: int | None,
) -> dict[str, object]:
    named: list[dict[str, object]] = []
    for row in seats:
        item = dict(row)
        kind = str(item.get("kind") or "player")
        telegram_raw = item.get("telegram_id")
        uid = int(telegram_raw) if telegram_raw not in (None, "") else None
        if kind == "player" and uid and actors and uid in actors:
            actor = actors[uid]
            item["display_name"] = str(actor.get("display_name") or item.get("display_name") or uid)
            item["actor"] = dict(actor)
        elif kind == "house_robot":
            item["display_name"] = str(item.get("display_name") or "Казино")
            item["actor"] = bot_chip(
                str(item["display_name"]),
                profile_id=item.get("profile_id"),
                profile_key=item.get("profile_key"),
                seat_no=item.get("seat_no"),
            )
        named.append(item)
    specs = [as_seat(item) for item in named]
    dice = canvas_dice(specs)
    humans = [spec for spec in specs if spec.kind == "player"]
    viewer_seat = next((spec for spec in humans if spec.telegram_id == viewer_id), None)
    last_round = {}
    choice = None
    raw_data = table.get("game_data")
    parsed_data: dict[str, Any] = {}
    if isinstance(raw_data, Mapping):
        parsed_data = dict(raw_data)
    elif isinstance(raw_data, str) and raw_data:
        try:
            loaded = json.loads(raw_data)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, Mapping):
            parsed_data = dict(loaded)
    last_round = dict(parsed_data.get("last_round") or {})
    choice = _choice_public(parsed_data.get("choice"))
    return {
        "success": True,
        "table_id": str(table.get("table_id") or ""),
        "game_type": GAME_TYPE,
        "status": str(table.get("status") or "open"),
        "max_seats": int(table.get("max_seats") or MAX_HUMANS),
        "house_bot_count": int(table.get("house_bot_count") or 0),
        "state_version": int(table.get("state_version") or 0),
        "is_seated": viewer_seat is not None,
        "solo": is_solo_table(table),
        "can_start": str(table.get("status")) == "open"
        and choice is None
        and MIN_START_HUMANS <= len(humans) <= min(MAX_HUMANS, int(table.get("max_seats") or MAX_HUMANS)),
        "viewer_seat_no": viewer_seat.seat_no if viewer_seat else None,
        "seats": [_public_seat(item, viewer_id) for item in named],
        "dice": dice,
        "last_round": last_round,
        "choice": choice,
        "money": "house",
    }


def _public_seat(row: Mapping[str, Any], viewer_id: int | None) -> dict[str, object]:
    kind = str(row.get("kind") or "player")
    telegram_raw = row.get("telegram_id")
    uid = int(telegram_raw) if telegram_raw not in (None, "") else None
    stake = money(row.get("stake_rub") or 0)
    payout = row.get("payout_rub")
    return {
        "seat_no": int(row.get("seat_no") or 0),
        "kind": kind,
        "telegram_id": uid if kind == "player" else None,
        "is_self": bool(uid and viewer_id and uid == viewer_id),
        "display_name": str(row.get("display_name") or ("Казино" if kind == "house_robot" else "Игрок")),
        "actor": row.get("actor"),
        "stake_rub": float(stake) if kind == "player" else 0.0,
        "payout_rub": float(money(payout)) if payout is not None else None,
        "won": row.get("won"),
        "player_pips": row.get("player_pips"),
        "house_pips": row.get("house_pips"),
        "status": str(row.get("status") or "seated"),
    }


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _choice_public(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, Mapping):
        return None
    return {str(key): value for key, value in raw.items() if str(key) != "money"}


async def _lock_table(conn, table_id: str) -> Mapping[str, Any]:
    row = await conn.fetchrow(
        """
        SELECT * FROM casino_house_tables
        WHERE table_id = $1
        FOR UPDATE
        """,
        table_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Стол не найден")
    return row


async def _load_table(conn, table_id: str) -> Mapping[str, Any]:
    row = await conn.fetchrow(
        "SELECT * FROM casino_house_tables WHERE table_id = $1",
        table_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Стол не найден")
    return row


async def _seats(conn, table_pk: int) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT seat_no, kind, telegram_id, profile_id, profile_key, display_name,
               stake_rub, payout_rub, commission_rub, won, player_pips, house_pips,
               cub_game_id, status
        FROM casino_house_table_seats
        WHERE table_pk = $1
        ORDER BY seat_no
        """,
        table_pk,
    )
    return [dict(row) for row in rows]


async def _actors_for_seats(conn, seats: Sequence[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    from casino_chat import public_actors

    ids = [
        int(row["telegram_id"])
        for row in seats
        if str(row.get("kind")) == "player" and row.get("telegram_id") not in (None, "")
    ]
    if not ids:
        return {}
    return await public_actors(conn, ids)


async def snapshot(conn, *, table_id: str, viewer_id: int | None) -> dict[str, object]:
    table = await _load_table(conn, table_id.strip())
    seats = await _seats(conn, int(table["id"]))
    actors = await _actors_for_seats(conn, seats)
    return build_snapshot(table, seats, actors, viewer_id)


async def list_open_tables(conn, *, viewer_id: int | None = None) -> dict[str, object]:
    rows = await conn.fetch(
        """
        SELECT t.id, t.table_id, t.game_type, t.status, t.max_seats, t.house_bot_count,
               t.state_version, t.created_at,
               (SELECT count(*) FROM casino_house_table_seats s
                 WHERE s.table_pk = t.id AND s.kind = 'player') AS human_count
        FROM casino_house_tables t
        WHERE t.status = 'open' AND t.game_type = $1
        ORDER BY t.created_at DESC
        LIMIT 40
        """,
        GAME_TYPE,
    )
    tables = []
    for row in rows:
        seats = await _seats(conn, int(row["id"]))
        actors = await _actors_for_seats(conn, seats)
        named: list[dict[str, object]] = []
        for seat in seats:
            item = dict(seat)
            kind = str(item.get("kind") or "player")
            telegram_raw = item.get("telegram_id")
            uid = int(telegram_raw) if telegram_raw not in (None, "") else None
            if kind == "player" and uid and uid in actors:
                actor = actors[uid]
                item["display_name"] = str(actor.get("display_name") or item.get("display_name") or uid)
                item["actor"] = dict(actor)
            elif kind == "house_robot":
                item["display_name"] = str(item.get("display_name") or "Казино")
                item["actor"] = bot_chip(
                    str(item["display_name"]),
                    profile_id=item.get("profile_id"),
                    profile_key=item.get("profile_key"),
                    seat_no=item.get("seat_no"),
                )
            named.append(item)
        card = public_table_card(row, seats)
        if is_solo_table(card["max_seats"]):
            continue
        card["seats"] = [_public_seat(item, viewer_id) for item in named]
        tables.append(card)
    return {"tables": tables}


async def _insert_house_bots(conn, *, table_pk: int, count: int) -> None:
    n = validate_house_bot_count(count)
    if n <= 0:
        return
    profiles = await conn.fetch(
        """
        SELECT rp.id, rp.profile_key, rp.display_name
        FROM casino_robot_profiles rp
        JOIN casino_house_accounts ha ON ha.id = rp.account_id
        WHERE rp.mode = 'house_robot' AND rp.is_active = TRUE
          AND ha.is_active = TRUE
          AND rp.allowed_games ? 'cub'
        ORDER BY rp.id
        """
    )
    for index in range(n):
        profile = profiles[index % len(profiles)] if profiles else None
        display = str(profile["display_name"]) if profile else "Казино"
        key = str(profile["profile_key"]) if profile else None
        profile_id = int(profile["id"]) if profile else None
        await conn.execute(
            """
            INSERT INTO casino_house_table_seats (
                table_pk, seat_no, kind, telegram_id, profile_id, profile_key,
                display_name, stake_rub, status
            ) VALUES ($1, $2, 'house_robot', NULL, $3, $4, $5, 0, 'seated')
            """,
            table_pk,
            HOUSE_BOT_SEAT_BASE + index,
            profile_id,
            key,
            display,
        )


async def create_table(
    conn,
    *,
    creator_id: int,
    stake_rub: Decimal | int | float | str,
    max_seats: int = 1,
    house_bot_count: int = 2,
    auto_start: bool | None = None,
    play_seat: PlayHumanCub | None = None,
) -> dict[str, object]:
    seats = validate_max_seats(max_seats)
    bots = validate_house_bot_count(house_bot_count)
    stake = money(stake_rub)
    settings = await load_casino_settings(conn)
    if not settings.enabled_games.get(HOUSE_MONEY_GAME, False):
        raise HTTPException(status_code=409, detail="Кубик против казино выключен")
    quote = await load_cub_play_quote(
        conn, stake_rub=stake, viewer_id=creator_id, house_bot_count=bots
    )
    if not quote.get("enabled"):
        raise HTTPException(status_code=409, detail="Кубик против казино выключен")
    bound = quote.get("bound_error") or stake_bound_error(
        stake, money(quote["min_bet_rub"]), money(quote["max_bet_rub"])
    )
    if bound:
        raise HTTPException(status_code=400, detail=str(bound))
    elsewhere = await conn.fetchval(
        """
        SELECT t.table_id FROM casino_house_table_seats s
        JOIN casino_house_tables t ON t.id = s.table_pk
        WHERE s.telegram_id = $1 AND t.status IN ('open', 'running')
        LIMIT 1
        """,
        creator_id,
    )
    if elsewhere:
        other = await _load_table(conn, str(elsewhere))
        if is_solo_table(other) and str(other["status"]) != "running":
            await leave(conn, table_id=str(elsewhere), user_id=creator_id)
        else:
            pending = _json_object(other.get("game_data")).get("choice")
            if pending:
                raise HTTPException(status_code=409, detail="Сначала заберите выигрыш или перебросьте")
            raise _seated_elsewhere_error(str(elsewhere))
    table_id = f"ht-{uuid4().hex[:12]}"
    seed = secrets.token_hex(32)
    inserted = await conn.fetchrow(
        """
        INSERT INTO casino_house_tables (
            table_id, game_type, creator_id, max_seats, house_bot_count, status, rng_seed
        ) VALUES ($1, $2, $3, $4, $5, 'open', $6)
        RETURNING *
        """,
        table_id,
        GAME_TYPE,
        creator_id,
        seats,
        bots,
        seed,
    )
    await conn.execute(
        """
        INSERT INTO casino_house_table_seats (
            table_pk, seat_no, kind, telegram_id, stake_rub, status
        ) VALUES ($1, $2, 'player', $3, $4, 'seated')
        """,
        int(inserted["id"]),
        1,
        creator_id,
        stake,
    )
    await _insert_house_bots(conn, table_pk=int(inserted["id"]), count=bots)
    should_start = auto_start if auto_start is not None else is_solo_table(seats)
    if should_start:
        return await start_round(conn, table_id=table_id, user_id=creator_id, play_seat=play_seat)
    return await snapshot(conn, table_id=table_id, viewer_id=creator_id)


async def sit(
    conn,
    *,
    table_id: str,
    user_id: int,
    stake_rub: Decimal | int | float | str,
    seat_no: int | None = None,
) -> dict[str, object]:
    stake = money(stake_rub)
    table = await _lock_table(conn, table_id.strip())
    if is_solo_table(table):
        raise HTTPException(status_code=409, detail="Этот стол только для создателя")
    if str(table["status"]) != "open":
        raise HTTPException(status_code=409, detail="Стол уже играет")
    if str(table["game_type"]) != GAME_TYPE:
        raise HTTPException(status_code=409, detail="Этот стол не для кубиков")
    settings = await load_casino_settings(conn)
    if not settings.enabled_games.get(HOUSE_MONEY_GAME, False):
        raise HTTPException(status_code=409, detail="Кубик против казино выключен")
    quote = await load_cub_play_quote(
        conn,
        stake_rub=stake,
        viewer_id=user_id,
        house_bot_count=int(table.get("house_bot_count") or 0),
    )
    bound = quote.get("bound_error") or stake_bound_error(
        stake, money(quote["min_bet_rub"]), money(quote["max_bet_rub"])
    )
    if bound:
        raise HTTPException(status_code=400, detail=str(bound))
    seats = await _seats(conn, int(table["id"]))
    humans = [row for row in seats if str(row["kind"]) == "player"]
    if any(int(row["telegram_id"]) == user_id for row in humans):
        raise HTTPException(status_code=409, detail="Вы уже за этим столом")
    elsewhere = await conn.fetchval(
        """
        SELECT t.table_id FROM casino_house_table_seats s
        JOIN casino_house_tables t ON t.id = s.table_pk
        WHERE s.telegram_id = $1 AND t.status IN ('open', 'running') AND t.table_id <> $2
        LIMIT 1
        """,
        user_id,
        str(table["table_id"]),
    )
    if elsewhere:
        raise _seated_elsewhere_error(str(elsewhere))
    occupied = [int(row["seat_no"]) for row in humans]
    wanted = int(seat_no) if seat_no is not None else next_human_seat_no(occupied, int(table["max_seats"]))
    if wanted < HUMAN_SEAT_MIN or wanted > int(table["max_seats"]):
        raise HTTPException(status_code=400, detail="Нет такого места")
    if wanted in occupied:
        raise HTTPException(status_code=409, detail="Место занято")
    if len(humans) >= int(table["max_seats"]):
        raise HTTPException(status_code=409, detail="Стол заполнен")
    await conn.execute(
        """
        INSERT INTO casino_house_table_seats (
            table_pk, seat_no, kind, telegram_id, stake_rub, status
        ) VALUES ($1, $2, 'player', $3, $4, 'seated')
        """,
        int(table["id"]),
        wanted,
        user_id,
        stake,
    )
    await conn.execute(
        """
        UPDATE casino_house_tables
        SET state_version = state_version + 1, updated_at = now()
        WHERE id = $1
        """,
        int(table["id"]),
    )
    from casino_inbox import notify_player_joined

    other_ids = [int(row["telegram_id"]) for row in humans if row.get("telegram_id") is not None]
    await notify_player_joined(
        conn,
        joiner_id=int(user_id),
        other_ids=other_ids,
        kind="house",
        game_id=str(table["table_id"]),
        game_type=str(table.get("game_type") or GAME_TYPE),
        stake_rub=stake,
    )
    return await snapshot(conn, table_id=str(table["table_id"]), viewer_id=user_id)


async def leave(conn, *, table_id: str, user_id: int) -> dict[str, object]:
    table = await _lock_table(conn, table_id.strip())
    if str(table["status"]) == "running":
        pending = _json_object(table.get("game_data")).get("choice")
        if pending:
            raise HTTPException(status_code=409, detail="Сначала заберите выигрыш или перебросьте")
        raise HTTPException(status_code=409, detail="Дождитесь конца раунда")
    seats = await _seats(conn, int(table["id"]))
    mine = next(
        (row for row in seats if str(row["kind"]) == "player" and int(row["telegram_id"]) == user_id),
        None,
    )
    if not mine:
        raise HTTPException(status_code=409, detail="Вы не за столом")
    await conn.execute(
        "DELETE FROM casino_house_table_seats WHERE table_pk = $1 AND telegram_id = $2",
        int(table["id"]),
        user_id,
    )
    remaining = [row for row in seats if str(row["kind"]) == "player" and int(row["telegram_id"]) != user_id]
    if not remaining:
        await conn.execute(
            """
            UPDATE casino_house_tables
            SET status = 'closed', state_version = state_version + 1, updated_at = now()
            WHERE id = $1
            """,
            int(table["id"]),
        )
    else:
        await conn.execute(
            """
            UPDATE casino_house_tables
            SET state_version = state_version + 1, updated_at = now()
            WHERE id = $1
            """,
            int(table["id"]),
        )
    return await snapshot(conn, table_id=str(table["table_id"]), viewer_id=user_id)


async def expire_open_unjoined(conn, *, now: datetime | None = None, limit: int = 20) -> int:
    """Close multi-seat house tables still waiting after the join timeout. Solo auto-starts."""
    from casino_waiting import waiting_cutoff

    cutoff = waiting_cutoff(now)
    rows = await conn.fetch(
        """
        /* house:expire-unjoined */
        SELECT table_id
        FROM casino_house_tables
        WHERE status = 'open'
          AND max_seats > $1
          AND created_at <= $2
        ORDER BY created_at
        LIMIT $3
        """,
        SOLO_MAX_SEATS,
        cutoff,
        int(limit),
    )
    closed = 0
    for row in rows:
        table_id = str(row["table_id"])
        table = await _lock_table(conn, table_id)
        if str(table["status"]) != "open" or is_solo_table(table):
            continue
        seats = await _seats(conn, int(table["id"]))
        humans = [
            int(item["telegram_id"])
            for item in seats
            if str(item["kind"]) == "player" and item.get("telegram_id") not in (None, "")
        ]
        if not humans:
            await conn.execute(
                """
                UPDATE casino_house_tables
                SET status = 'closed', state_version = state_version + 1, updated_at = now()
                WHERE id = $1 AND status = 'open'
                """,
                int(table["id"]),
            )
            closed += 1
            continue
        for uid in humans:
            await leave(conn, table_id=table_id, user_id=uid)
        closed += 1
    return closed


async def _load_face_house(conn, *, telegram_id: int, stake: Decimal, max_multiplier: Decimal) -> dict[str, Any]:
    from casino_wagering import commission_profile_for_player, commission_rate_for_player
    from routers.internal_casino import _assert_stake_within_limits

    settings = await load_casino_settings(conn)
    if not settings.enabled_games.get(HOUSE_MONEY_GAME, False):
        raise HTTPException(status_code=409, detail="Кубик против казино выключен")
    commission_rate = await commission_rate_for_player(conn, telegram_id)
    commission_profile, _ = await commission_profile_for_player(conn, telegram_id)
    policy = await conn.fetchrow(
        """
        SELECT id, payout_multiplier, win_probability, terms
        FROM casino_house_policies
        WHERE game_type = 'cub' AND is_active = TRUE
        FOR UPDATE
        """
    )
    profile = await conn.fetchrow(
        """
        SELECT rp.id, rp.account_id, rp.min_bet_rub, rp.max_bet_rub, rp.max_exposure_rub,
               ha.account_key, ha.balance_rub, ha.reserved_rub, ha.is_active AS account_active
        FROM casino_robot_profiles rp
        JOIN casino_house_accounts ha ON ha.id = rp.account_id
        WHERE rp.mode = 'house_robot' AND rp.is_active = TRUE
          AND rp.allowed_games ? 'cub'
        ORDER BY rp.id
        LIMIT 1
        FOR UPDATE OF rp, ha
        """
    )
    if not policy or not profile or not bool(profile["account_active"]):
        raise HTTPException(status_code=409, detail="Кубик против казино выключен")
    if stake < money(profile["min_bet_rub"]) or stake > money(profile["max_bet_rub"]):
        raise HTTPException(status_code=409, detail="Ставка вне лимита робота")
    _assert_stake_within_limits(
        settings,
        "cub",
        stake,
        payout_multiplier=max_multiplier,
        bankroll_rub=money(profile["balance_rub"]),
    )
    max_settlement = calculate_house_settlement(
        stake,
        max_multiplier,
        commission_rate,
        commission_cap_rub=settings.commission_cap_rub,
        commission_min_rub=settings.commission_min_rub,
    )
    exposure_limit = money(profile["max_exposure_rub"])
    available = money(profile["balance_rub"]) - money(profile["reserved_rub"])
    if (exposure_limit > 0 and max_settlement.payout > exposure_limit) or available < max_settlement.payout:
        raise HTTPException(status_code=409, detail="Банк казино не покрывает выплату")
    return {
        "settings": settings,
        "commission_rate": commission_rate,
        "commission_profile": commission_profile,
        "policy": policy,
        "profile": profile,
        "max_settlement": max_settlement,
    }


async def _open_face_hold(
    conn,
    *,
    telegram_id: int,
    stake: Decimal,
    max_multiplier: Decimal,
    rng_audit: Mapping[str, Any],
) -> dict[str, Any]:
    from routers import internal_casino as ic

    house = await _load_face_house(conn, telegram_id=telegram_id, stake=stake, max_multiplier=max_multiplier)
    await lock_casino_users(conn, (telegram_id,))
    game_id = f"htcub-{uuid4().hex[:12]}"
    await lock_casino_game(conn, game_id)
    hold_id = f"casino-{game_id}-player"
    order_ref = casino_ledger_order_ref(hold_id)
    try:
        await reserve_unified_funds(conn, user_id=telegram_id, order_ref=order_ref, amount_rub=stake)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Недостаточно средств") from exc
    creator_cut, l1, l2 = commission_shares_for_rate(
        house["settings"],
        profile=house["commission_profile"],
        commission_rate=house["commission_rate"],
    )
    pricing = ic._pricing_snapshot_payload(
        commission_profile=house["commission_profile"],
        commission_rate=house["commission_rate"],
        creator_cut_percent=creator_cut,
        referral_l1_percent=l1,
        referral_l2_percent=l2,
        commission_cap_rub=house["settings"].commission_cap_rub,
        commission_min_rub=house["settings"].commission_min_rub,
    )
    game_data = {
        "source": "house_table_faces",
        "pricing_snapshot": pricing,
        "rng_audit": dict(rng_audit),
        "house_policy_snapshot": {
            "policy_id": int(house["policy"]["id"]),
            "max_payout_multiplier": ic._text_money(max_multiplier),
        },
    }
    reserved = house["max_settlement"].payout
    game = await conn.fetchrow(
        """
        INSERT INTO casino_games (
            game_id, game_type, creator_id, bet_rub, settlement_base_rub, payout_rub,
            creator_hold_id, status, counterparty_kind, house_account_id,
            robot_profile_id, house_policy_id, rng_seed_reveal, game_data, started_at
        ) VALUES (
            $1, 'cub', $2, $3, $3, 0, $4, 'active', 'house_robot', $5,
            $6, $7, $8, $9::jsonb, now()
        )
        RETURNING id
        """,
        game_id,
        telegram_id,
        stake,
        hold_id,
        int(house["profile"]["account_id"]),
        int(house["profile"]["id"]),
        int(house["policy"]["id"]),
        str(rng_audit.get("seed") or ""),
        json.dumps(game_data, separators=(",", ":")),
    )
    if not game:
        raise HTTPException(status_code=409, detail="Не удалось открыть раунд")
    await conn.execute(
        """
        INSERT INTO casino_balance_holds (
            hold_id, telegram_id, game_id, amount_rub, role, ledger_order_ref, status, expires_at
        ) VALUES ($1, $2, $3, $4, 'player', $5, 'active', now() + interval '2 hours')
        """,
        hold_id,
        telegram_id,
        game_id,
        stake,
        order_ref,
    )
    reservation = await conn.fetchrow(
        """
        UPDATE casino_house_accounts
        SET reserved_rub = reserved_rub + $2, updated_at = now()
        WHERE id = $1 AND balance_rub - reserved_rub >= $2
        RETURNING balance_rub, reserved_rub
        """,
        int(house["profile"]["account_id"]),
        reserved,
    )
    if not reservation:
        raise HTTPException(status_code=409, detail="Банк казино не покрывает выплату")
    await conn.execute(
        """
        INSERT INTO casino_house_reservations (reservation_key, account_id, game_id, amount_rub)
        VALUES ($1, $2, $3, $4)
        """,
        f"cub-reserve-{game_id}",
        int(house["profile"]["account_id"]),
        game_id,
        reserved,
    )
    return {
        "game_id": game_id,
        "game_pk": int(game["id"]),
        "hold_id": hold_id,
        "order_ref": order_ref,
        "account_id": int(house["profile"]["account_id"]),
        "reserved_rub": str(reserved),
        "pricing_snapshot": pricing,
        "commission_rate": str(house["commission_rate"]),
    }


async def _close_face_hold(
    conn,
    *,
    telegram_id: int,
    stake: Decimal,
    multiplier: Decimal,
    money_ref: Mapping[str, Any],
    rng_audit: Mapping[str, Any],
) -> SeatHouseSettlement:
    from routers import internal_casino as ic

    pricing = dict(money_ref["pricing_snapshot"])
    rate = Decimal(str(pricing.get("commission_rate") or money_ref.get("commission_rate") or 5))
    settlement = calculate_house_settlement(
        stake,
        multiplier,
        rate,
        commission_cap_rub=ic._snapshot_amount(pricing, "commission_cap_rub"),
        commission_min_rub=ic._snapshot_amount(pricing, "commission_min_rub"),
    )
    game_id = str(money_ref["game_id"])
    hold_id = str(money_ref["hold_id"])
    order_ref = str(money_ref["order_ref"])
    account_id = int(money_ref["account_id"])
    reserved = money(money_ref["reserved_rub"])
    game_pk = int(money_ref["game_pk"])
    won = settlement.payout > 0 and multiplier > 1
    pushed = multiplier == Decimal("1")
    await confirm_unified_hold(
        conn,
        user_id=telegram_id,
        order_ref=order_ref,
        amount_rub=stake,
        note=f"Casino house-table stake: {game_id}",
    )
    if settlement.payout > 0:
        await ic._credit_winner(conn, game_id=game_id, winner_id=telegram_id, payout_rub=settlement.payout)
    account = await conn.fetchrow(
        """
        UPDATE casino_house_accounts
        SET balance_rub = balance_rub + $2 - $3,
            reserved_rub = reserved_rub - $4,
            updated_at = now()
        WHERE id = $1 AND reserved_rub >= $4
        RETURNING balance_rub, reserved_rub
        """,
        account_id,
        stake,
        settlement.payout,
        reserved,
    )
    if not account:
        raise HTTPException(status_code=409, detail="Резерв казино не сошёлся")
    if multiplier != Decimal("1"):
        casino_creator_account = await ic._resolve_active_creator_account(conn)
        referral_l1_id, referral_l2_id = await ic._resolve_loser_referrals(conn, telegram_id)
        allocations = allocate_commission(
            stake,
            commission_rate=pricing["commission_rate"],
            creator_percent=pricing["creator_cut_percent"],
            referral_l1_percent=pricing["referral_l1_percent"],
            referral_l2_percent=pricing["referral_l2_percent"],
            has_creator=casino_creator_account is not None,
            has_referral_l1=referral_l1_id is not None,
            has_referral_l2=referral_l2_id is not None,
            commission_cap_rub=ic._snapshot_amount(pricing, "commission_cap_rub"),
            commission_min_rub=ic._snapshot_amount(pricing, "commission_min_rub"),
        )
        await ic._record_commissions(
            conn,
            game_pk=game_pk,
            game_id=game_id,
            casino_creator_account=casino_creator_account,
            referral_l1_id=referral_l1_id,
            referral_l2_id=referral_l2_id,
            allocations=allocations,
        )
    reason = "push" if pushed else ("win" if won else "loss")
    await conn.execute(
        """
        INSERT INTO casino_house_ledger (
            account_id, game_id, entry_key, entry_type, amount_rub, balance_after_rub, reason
        ) VALUES ($1, $2, $3, 'game_settlement', $4, $5, $6)
        """,
        account_id,
        game_id,
        f"cub-settlement-{game_id}",
        settlement.house_delta,
        money(account["balance_rub"]),
        f"House-table {reason} settlement",
    )
    await conn.execute(
        """
        UPDATE casino_house_reservations SET status = 'settled', settled_at = now()
        WHERE game_id = $1 AND status = 'active'
        """,
        game_id,
    )
    await conn.execute(
        """
        UPDATE casino_balance_holds SET status = 'confirmed', confirmed_at = now()
        WHERE hold_id = $1 AND status = 'active'
        """,
        hold_id,
    )
    outcome = {
        "kind": "push" if pushed else ("win" if won else "loss"),
        "winner_id": telegram_id if settlement.payout > 0 else None,
        "faces": dict(rng_audit),
    }
    merged = dict(rng_audit)
    await conn.execute(
        """
        UPDATE casino_games
        SET payout_rub = $2, status = 'finished', winner_id = $3, outcome = $4::jsonb,
            commission_rub = $5, finished_at = now(), updated_at = now(),
            game_data = COALESCE(game_data, '{}'::jsonb) || $6::jsonb
        WHERE game_id = $1
        """,
        game_id,
        settlement.payout,
        telegram_id if settlement.payout > 0 else None,
        json.dumps(outcome, separators=(",", ":")),
        settlement.commission,
        json.dumps({"rng_audit": merged}, separators=(",", ":")),
    )
    from casino_level_bonus import maybe_grant_reached_level_bonuses

    await maybe_grant_reached_level_bonuses(conn, telegram_id)
    return SeatHouseSettlement(
        stake_rub=stake,
        won=won,
        payout_rub=settlement.payout,
        commission_rub=settlement.commission,
        house_delta_rub=settlement.house_delta,
    )


async def play_human_cub(
    conn,
    *,
    telegram_id: int,
    stake_rub: Decimal,
    house_bot_count: int = 0,
) -> Mapping[str, Any]:
    """One HMAC cub round for a seated human. House bots never call this."""
    from routers.internal_casino import CubPlayRequest, PrepareCubRequest, play_cub_with_conn, prepare_cub_with_conn

    prepared = await prepare_cub_with_conn(conn, PrepareCubRequest(telegram_id=telegram_id))
    return await play_cub_with_conn(
        conn,
        CubPlayRequest(
            game_id=str(prepared["game_id"]),
            telegram_id=telegram_id,
            stake_rub=stake_rub,
            house_bot_count=int(house_bot_count or 0),
        ),
    )


def _result_money(value: object) -> Decimal:
    return money(value or 0)


def _money_blob(ref: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "game_id": str(ref["game_id"]),
        "game_pk": int(ref["game_pk"]),
        "hold_id": str(ref["hold_id"]),
        "order_ref": str(ref["order_ref"]),
        "account_id": int(ref["account_id"]),
        "reserved_rub": str(ref["reserved_rub"]),
        "pricing_snapshot": dict(ref["pricing_snapshot"]),
        "commission_rate": str(ref["commission_rate"]),
    }


def _choice_rates(money_ref: Mapping[str, Any]) -> tuple[Decimal, object, object]:
    pricing = dict(money_ref.get("pricing_snapshot") or {})
    rate = Decimal(str(pricing.get("commission_rate") or money_ref.get("commission_rate") or 5))
    return rate, pricing.get("commission_cap_rub") or 0, pricing.get("commission_min_rub") or 0


def _build_choice_payload(
    *,
    compared: DiceCompare,
    human: HouseSeatSpec,
    nonce: int,
    money_ref: Mapping[str, Any],
    can_reroll: bool = True,
) -> dict[str, Any]:
    rate, cap, mn = _choice_rates(money_ref)
    quote = choice_quote(
        human.stake_rub,
        wins=compared.wins,
        ties=compared.ties,
        win_seats=compared.win_seats,
        tie_seats=compared.tie_seats,
        commission_rate=rate,
        commission_cap_rub=cap,
        commission_min_rub=mn,
        can_reroll=can_reroll,
    )
    quote.update(
        {
            "player_seat_no": int(human.seat_no),
            "player_pips": compared.player_pips,
            "nonce": int(nonce),
            "money": _money_blob(money_ref),
        }
    )
    return quote


def _face_audit(
    *,
    seed: str,
    table_id: str,
    nonce: int,
    player_pips: int,
    bots: Sequence[tuple[int, int]],
    compared: DiceCompare,
    phase: str,
) -> dict[str, Any]:
    return {
        "algorithm": "HMAC-SHA256",
        "seed": seed,
        "table_id": table_id,
        "nonce": int(nonce),
        "phase": phase,
        "player_pips": int(player_pips),
        "bots": [{"seat_no": int(seat), "pips": int(pips)} for seat, pips in bots],
        "wins": compared.wins,
        "ties": compared.ties,
        "losses": compared.losses,
        "kind": compared.kind,
    }


async def _mark_running(conn, table: Mapping[str, Any]) -> None:
    await conn.execute(
        """
        UPDATE casino_house_tables
        SET status = 'running', state_version = state_version + 1, updated_at = now()
        WHERE id = $1 AND status = 'open'
        """,
        int(table["id"]),
    )


async def _write_bot_faces(conn, *, table_pk: int, faces: Sequence[tuple[int, int]]) -> None:
    for seat_no, pips in faces:
        await conn.execute(
            """
            UPDATE casino_house_table_seats
            SET house_pips = $3, status = 'settled'
            WHERE table_pk = $1 AND seat_no = $2
            """,
            table_pk,
            int(seat_no),
            int(pips),
        )


async def _write_human_face(
    conn,
    *,
    table_pk: int,
    seat_no: int,
    player_pips: int,
    cub_game_id: str | None,
    status: str,
    payout: Decimal | None = None,
    commission: Decimal | None = None,
    won: bool | None = None,
) -> None:
    await conn.execute(
        """
        /* house:face-human */
        UPDATE casino_house_table_seats
        SET player_pips = $3, cub_game_id = $4, status = $5,
            payout_rub = $6, commission_rub = $7, won = $8
        WHERE table_pk = $1 AND seat_no = $2
        """,
        table_pk,
        int(seat_no),
        int(player_pips),
        cub_game_id,
        status,
        payout,
        commission,
        won,
    )


async def _keep_running_choice(conn, *, table_pk: int, game_data: Mapping[str, Any]) -> None:
    await conn.execute(
        """
        /* house:face-keep */
        UPDATE casino_house_tables
        SET game_data = $2::jsonb, state_version = state_version + 1, updated_at = now()
        WHERE id = $1
        """,
        table_pk,
        json.dumps(game_data, separators=(",", ":")),
    )


async def _finish_face_table(
    conn,
    *,
    table: Mapping[str, Any],
    user_id: int,
    human: HouseSeatSpec,
    player_pips: int,
    bots: Sequence[tuple[int, int]],
    settlement: SeatHouseSettlement,
    cub_game_id: str,
    compared: DiceCompare,
    multiplier: Decimal,
    nonce: int,
) -> dict[str, object]:
    await _write_human_face(
        conn,
        table_pk=int(table["id"]),
        seat_no=human.seat_no,
        player_pips=player_pips,
        cub_game_id=cub_game_id,
        status="settled",
        payout=settlement.payout_rub,
        commission=settlement.commission_rub,
        won=bool(settlement.won),
    )
    await _write_bot_faces(conn, table_pk=int(table["id"]), faces=bots)
    game_data = _json_object(table.get("game_data"))
    game_data.pop("choice", None)
    game_data["last_round"] = {
        "money": "house",
        "shared_pot": False,
        "faces": True,
        "house_bot_count": int(table.get("house_bot_count") or 0),
        "kind": "win" if multiplier > 1 else ("push" if multiplier == Decimal("1") else "loss"),
        "payout_multiplier": float(multiplier),
        "nonce": int(nonce),
        "seats": [
            {
                "seat_no": human.seat_no,
                "telegram_id": human.telegram_id,
                "stake_rub": float(human.stake_rub),
                "payout_rub": float(settlement.payout_rub),
                "commission_rub": float(settlement.commission_rub),
                "won": bool(settlement.won),
                "cub_game_id": cub_game_id,
                "player_pips": player_pips,
            }
        ],
    }
    await conn.execute(
        """
        UPDATE casino_house_tables
        SET status = 'open', game_data = $2::jsonb,
            state_version = state_version + 1, updated_at = now()
        WHERE id = $1
        """,
        int(table["id"]),
        json.dumps(game_data, separators=(",", ":")),
    )
    return await snapshot(conn, table_id=str(table["table_id"]), viewer_id=user_id)


async def _start_face_round(
    conn,
    *,
    table: Mapping[str, Any],
    user_id: int,
    specs: Sequence[HouseSeatSpec],
) -> dict[str, object]:
    humans = [row for row in specs if row.kind == "player"]
    bots_spec = [row for row in specs if row.kind == "house_robot"]
    human = humans[0]
    await _mark_running(conn, table)
    seed = str(table.get("rng_seed") or secrets.token_hex(32))
    nonce = int(table.get("state_version") or 0) + 1
    table_id = str(table["table_id"])
    player_pips = player_die_pips(seed, table_id, human.seat_no, nonce)
    bot_faces = [
        (bot.seat_no, house_bot_die_pips(seed, table_id, bot.seat_no, nonce)) for bot in bots_spec
    ]
    compared = compare_dice(player_pips, bot_faces)
    max_mult = face_max_multiplier(int(table.get("house_bot_count") or len(bot_faces)))
    audit = _face_audit(
        seed=seed,
        table_id=table_id,
        nonce=nonce,
        player_pips=player_pips,
        bots=bot_faces,
        compared=compared,
        phase="open",
    )
    money_ref = await _open_face_hold(
        conn,
        telegram_id=int(human.telegram_id or 0),
        stake=human.stake_rub,
        max_multiplier=max_mult,
        rng_audit=audit,
    )
    cub_id = str(money_ref["game_id"])
    await _write_bot_faces(conn, table_pk=int(table["id"]), faces=bot_faces)
    if compared.kind == "choice":
        payload = _build_choice_payload(
            compared=compared,
            human=human,
            nonce=nonce,
            money_ref=money_ref,
            can_reroll=True,
        )
        await _write_human_face(
            conn,
            table_pk=int(table["id"]),
            seat_no=human.seat_no,
            player_pips=player_pips,
            cub_game_id=cub_id,
            status="playing",
        )
        game_data = _json_object(table.get("game_data"))
        game_data["choice"] = payload
        game_data.pop("last_round", None)
        await _keep_running_choice(conn, table_pk=int(table["id"]), game_data=game_data)
        return await snapshot(conn, table_id=table_id, viewer_id=user_id)
    multiplier = Decimal("0") if compared.kind == "loss" else take_multiplier(compared.wins)
    settlement = await _close_face_hold(
        conn,
        telegram_id=int(human.telegram_id or 0),
        stake=human.stake_rub,
        multiplier=multiplier,
        money_ref=money_ref,
        rng_audit=audit,
    )
    return await _finish_face_table(
        conn,
        table=table,
        user_id=user_id,
        human=human,
        player_pips=player_pips,
        bots=bot_faces,
        settlement=settlement,
        cub_game_id=cub_id,
        compared=compared,
        multiplier=multiplier,
        nonce=nonce,
    )


async def resolve_round(
    conn,
    *,
    table_id: str,
    user_id: int,
    action: ChoiceAction,
) -> dict[str, object]:
    table = await _lock_table(conn, table_id.strip())
    if str(table["status"]) != "running":
        raise HTTPException(status_code=409, detail="Сейчас нечего забирать")
    game_data = _json_object(table.get("game_data"))
    raw_choice = game_data.get("choice")
    if not isinstance(raw_choice, Mapping):
        raise HTTPException(status_code=409, detail="Сейчас нечего забирать")
    seats = await _seats(conn, int(table["id"]))
    specs = [as_seat(row) for row in seats]
    humans = [row for row in specs if row.kind == "player"]
    if not any(row.telegram_id == user_id for row in humans):
        raise HTTPException(status_code=409, detail="Сначала сядьте за стол")
    human = next(row for row in humans if row.telegram_id == user_id)
    money_ref = dict(raw_choice.get("money") or {})
    if not money_ref.get("game_id"):
        raise HTTPException(status_code=409, detail="Раунд уже закрыт")
    seed = str(table.get("rng_seed") or "")
    nonce = int(raw_choice.get("nonce") or 0)
    locked_wins = int(raw_choice.get("wins") or 0)
    win_seats = [int(n) for n in (raw_choice.get("win_seats") or [])]
    tie_seats = [int(n) for n in (raw_choice.get("tie_seats") or [])]
    player_pips = int(raw_choice.get("player_pips") or human.player_pips or 0)
    bot_map = {
        int(row.seat_no): int(row.house_pips or 0)
        for row in specs
        if row.kind == "house_robot"
    }
    chosen = str(action)
    if chosen not in ("take", "reroll"):
        raise HTTPException(status_code=400, detail="Нужно забрать или перебросить")
    if chosen == "reroll" and not bool(raw_choice.get("can_reroll", True)):
        raise HTTPException(status_code=409, detail="Переброс уже был")
    cub_id = str(money_ref["game_id"])
    table_key = str(table["table_id"])
    if chosen == "take":
        multiplier = take_multiplier(locked_wins)
        compared = DiceCompare(
            player_pips=player_pips,
            win_seats=tuple(win_seats),
            tie_seats=tuple(tie_seats),
            lose_seats=(),
        )
        audit = _face_audit(
            seed=seed,
            table_id=table_key,
            nonce=nonce,
            player_pips=player_pips,
            bots=list(bot_map.items()),
            compared=compared,
            phase="take",
        )
        settlement = await _close_face_hold(
            conn,
            telegram_id=user_id,
            stake=human.stake_rub,
            multiplier=multiplier,
            money_ref=money_ref,
            rng_audit=audit,
        )
        return await _finish_face_table(
            conn,
            table=table,
            user_id=user_id,
            human=human,
            player_pips=player_pips,
            bots=list(bot_map.items()),
            settlement=settlement,
            cub_game_id=cub_id,
            compared=compared,
            multiplier=multiplier,
            nonce=nonce,
        )
    reroll_nonce = nonce + 1
    player_pips = player_die_pips(seed, table_key, human.seat_no, reroll_nonce)
    for seat_no in tie_seats:
        bot_map[seat_no] = house_bot_die_pips(seed, table_key, seat_no, reroll_nonce)
    remaining = [(seat_no, bot_map[seat_no]) for seat_no in tie_seats]
    compared = compare_dice(player_pips, remaining)
    multiplier = after_reroll_multiplier(locked_wins, compared)
    audit = _face_audit(
        seed=seed,
        table_id=table_key,
        nonce=reroll_nonce,
        player_pips=player_pips,
        bots=list(bot_map.items()),
        compared=compared,
        phase="reroll",
    )
    settlement = await _close_face_hold(
        conn,
        telegram_id=user_id,
        stake=human.stake_rub,
        multiplier=multiplier,
        money_ref=money_ref,
        rng_audit=audit,
    )
    finish_kind = DiceCompare(
        player_pips=player_pips,
        win_seats=tuple(win_seats) + compared.win_seats,
        tie_seats=compared.tie_seats,
        lose_seats=compared.lose_seats,
    )
    return await _finish_face_table(
        conn,
        table=table,
        user_id=user_id,
        human=human,
        player_pips=player_pips,
        bots=list(bot_map.items()),
        settlement=settlement,
        cub_game_id=cub_id,
        compared=finish_kind,
        multiplier=multiplier,
        nonce=reroll_nonce,
    )


async def expire_pending_choices(conn, *, now: datetime | None = None, limit: int = 20) -> int:
    """Auto-take a stalled take/reroll after the waiting timeout. Stake is not forfeited."""
    from casino_waiting import waiting_cutoff

    cutoff = waiting_cutoff(now)
    rows = await conn.fetch(
        """
        /* house:expire-choice */
        SELECT table_id
        FROM casino_house_tables
        WHERE status = 'running'
          AND game_data ? 'choice'
          AND COALESCE(updated_at, created_at) <= $1
        ORDER BY COALESCE(updated_at, created_at)
        LIMIT $2
        """,
        cutoff,
        int(limit),
    )
    closed = 0
    for row in rows:
        tid = str(row["table_id"])
        try:
            table = await _load_table(conn, tid)
            seats = await _seats(conn, int(table["id"]))
            human = next(
                (item for item in seats if str(item.get("kind")) == "player" and item.get("telegram_id")),
                None,
            )
            if not human:
                continue
            await resolve_round(conn, table_id=tid, user_id=int(human["telegram_id"]), action="take")
        except HTTPException:
            continue
        closed += 1
    return closed


async def start_round(
    conn,
    *,
    table_id: str,
    user_id: int,
    play_seat: PlayHumanCub | None = None,
) -> dict[str, object]:
    table = await _lock_table(conn, table_id.strip())
    if str(table["status"]) != "open":
        raise HTTPException(status_code=409, detail="Стол уже играет")
    seats = await _seats(conn, int(table["id"]))
    specs = validate_roster_for_start(seats)
    humans = [row for row in specs if row.kind == "player"]
    if not any(row.telegram_id == user_id for row in humans):
        raise HTTPException(status_code=409, detail="Сначала сядьте за стол")
    if uses_face_money(table) and play_seat is None:
        return await _start_face_round(conn, table=table, user_id=user_id, specs=specs)
    await conn.execute(
        """
        UPDATE casino_house_tables
        SET status = 'running', state_version = state_version + 1, updated_at = now()
        WHERE id = $1 AND status = 'open'
        """,
        int(table["id"]),
    )
    play = play_seat or play_human_cub
    seed = str(table.get("rng_seed") or secrets.token_hex(32))
    nonce = int(table.get("state_version") or 0)
    bots_n = int(table.get("house_bot_count") or 0)
    round_rows: list[dict[str, object]] = []
    for human in humans:
        result = await play(
            conn,
            telegram_id=int(human.telegram_id or 0),
            stake_rub=human.stake_rub,
            house_bot_count=bots_n,
        )
        outcome = result.get("outcome") if isinstance(result.get("outcome"), Mapping) else {}
        won = str((outcome or {}).get("kind") or "") == "win" or bool((result.get("rng") or {}).get("won"))
        player_pips = result.get("player_pips")
        house_pips = result.get("house_pips")
        rng = result.get("rng") if isinstance(result.get("rng"), Mapping) else {}
        if player_pips is None:
            player_pips = rng.get("player_pips")
        if house_pips is None:
            house_pips = rng.get("house_pips")
        payout = _result_money(result.get("payout_rub"))
        commission = _result_money(result.get("commission_rub"))
        cub_id = str(result.get("game_id") or "")
        await conn.execute(
            """
            UPDATE casino_house_table_seats
            SET payout_rub = $3, commission_rub = $4, won = $5,
                player_pips = $6, house_pips = $7, cub_game_id = $8, status = 'settled'
            WHERE table_pk = $1 AND seat_no = $2
            """,
            int(table["id"]),
            human.seat_no,
            payout,
            commission,
            won,
            int(player_pips) if player_pips is not None else None,
            int(house_pips) if house_pips is not None else None,
            cub_id or None,
        )
        round_rows.append(
            {
                "seat_no": human.seat_no,
                "telegram_id": human.telegram_id,
                "stake_rub": float(human.stake_rub),
                "payout_rub": float(payout),
                "commission_rub": float(commission),
                "won": won,
                "cub_game_id": cub_id,
                "player_pips": player_pips,
                "house_pips": house_pips,
            }
        )
    bots = [row for row in specs if row.kind == "house_robot"]
    if not bots:
        visual = house_bot_die_pips(seed, str(table["table_id"]), HOUSE_BOT_SEAT_BASE, nonce)
        await conn.execute(
            """
            INSERT INTO casino_house_table_seats (
                table_pk, seat_no, kind, telegram_id, display_name, stake_rub,
                house_pips, status
            ) VALUES ($1, $2, 'house_robot', NULL, 'Казино', 0, $3, 'settled')
            ON CONFLICT (table_pk, seat_no) DO UPDATE SET house_pips = EXCLUDED.house_pips
            """,
            int(table["id"]),
            HOUSE_BOT_SEAT_BASE,
            visual,
        )
    for bot in bots:
        pips = house_bot_die_pips(seed, str(table["table_id"]), bot.seat_no, nonce)
        await conn.execute(
            """
            UPDATE casino_house_table_seats
            SET house_pips = $3, status = 'settled'
            WHERE table_pk = $1 AND seat_no = $2
            """,
            int(table["id"]),
            bot.seat_no,
            pips,
        )
    last_round = {
        "money": "house",
        "shared_pot": False,
        "house_bot_count": bots_n,
        "seats": round_rows,
    }
    game_data = _json_object(table.get("game_data"))
    game_data["last_round"] = last_round
    await conn.execute(
        """
        UPDATE casino_house_tables
        SET status = 'open', game_data = $2::jsonb,
            state_version = state_version + 1, updated_at = now()
        WHERE id = $1
        """,
        int(table["id"]),
        json.dumps(game_data, separators=(",", ":")),
    )
    return await snapshot(conn, table_id=str(table["table_id"]), viewer_id=user_id)
