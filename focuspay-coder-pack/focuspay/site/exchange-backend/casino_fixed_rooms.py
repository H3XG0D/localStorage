"""Fixed-stake rooms 2–N: equal bet, N seats, HMAC commit-reveal winner.

Not CSGETGO jackpot. Ticket-weighted pots stay in casino_jackpot.py.
Bots sit like V2 tables: house reserve, equal stake, may win the pot.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping, Sequence
from uuid import uuid4

from fastapi import HTTPException

from casino_finance import (
    casino_ledger_order_ref,
    casino_operation_ref,
    confirm_unified_hold,
    credit_house_game_settlement,
    load_casino_settings,
    lock_casino_users,
    money,
    maybe_credit_tournament_payout,
    MAX_BOTS_PER_TABLE,
    reserve_unified_funds,
)
from casino_live_sessions import START_COUNTDOWN_SECONDS, assert_can_sit, countdown_deadline
from casino_wallet import (
    active_scope,
    assert_player_may_sit,
    scope_filter_for,
    scope_or_mine_filter,
    scope_from_row,
    scope_insert_sql,
    viewer_scope,
)
from casino_settings_registry import REGISTRY, default_numeric

logger = logging.getLogger("casino_fixed_rooms")

GAME_TYPE = "fixed_room"
HMAC_ALGORITHM = "hmac-sha256-commit-reveal"
_subscribers: set[asyncio.Queue] = set()
_closer_started = False


@dataclass(frozen=True)
class RoomConfig:
    enabled: bool
    max_seats: int
    collect_seconds: int
    rake_percent: Decimal
    min_bet: Decimal
    max_bet: Decimal


def make_server_seed() -> str:
    return secrets.token_hex(32)


def commit_seed(seed: str) -> str:
    return hashlib.sha256((seed or "").encode("utf-8")).hexdigest()


def hmac_index(seed: str, message: str, modulus: int) -> int:
    if modulus <= 0:
        raise ValueError("no seats")
    digest = hmac.new((seed or "").encode("utf-8"), (message or "").encode("utf-8"), hashlib.sha256).digest()
    return int.from_bytes(digest, "big") % int(modulus)


def fairness_message(round_id: str, user_ids: Sequence[int]) -> str:
    joined = ",".join(str(int(uid)) for uid in user_ids)
    return f"{round_id}:{joined}"


def bot_reel_id(seat_no: int) -> int:
    """Unique negative id so the avatar reel can tell bots apart."""
    return -(int(seat_no) + 1)


def rake_split(pot: Decimal, percent: Decimal) -> tuple[Decimal, Decimal]:
    bank = money(pot)
    rake = money(bank * money(percent) / Decimal("100"))
    payout = money(bank - rake)
    return rake, payout


def split_even(amount: Decimal, n: int) -> list[Decimal]:
    total = money(amount)
    count = int(n)
    if count <= 0:
        return []
    share = (total / Decimal(count)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    parts = [share] * count
    parts[0] = money(total - share * (count - 1))
    return parts


def verify_hmac_round(
    *,
    seed: str,
    commit: str,
    message: str,
    modulus: int,
    expected_index: int | None = None,
) -> dict[str, object]:
    computed = commit_seed(seed)
    commit_matches = computed.lower() == (commit or "").strip().lower()
    index = hmac_index(seed, message, modulus) if modulus > 0 else None
    index_matches = expected_index is None or index == int(expected_index)
    return {
        "matches": bool(commit_matches and index_matches),
        "commit_matches": commit_matches,
        "index_matches": index_matches,
        "computed_commit": computed,
        "winner_index": index,
        "modulus": modulus,
        "algorithm": HMAC_ALGORITHM,
    }


def _setting_int(values: Mapping[str, object], key: str) -> int:
    raw = values.get(key)
    if isinstance(raw, Mapping) and raw.get("value") is not None:
        return int(raw["value"])
    spec = REGISTRY.get(key)
    return int(spec.default) if spec is not None else 0  # type: ignore[arg-type]


def _setting_percent(values: Mapping[str, object], key: str) -> Decimal:
    raw = values.get(key)
    if isinstance(raw, Mapping) and raw.get("percent") is not None:
        return money(raw["percent"])
    spec = REGISTRY.get(key)
    return money(spec.default) if spec is not None else money(0)  # type: ignore[arg-type]


async def load_room_config(conn) -> RoomConfig:
    settings = await load_casino_settings(conn)
    rows = {str(row["key"]): row["value"] for row in await conn.fetch("/* room:settings */ SELECT key, value FROM casino_settings")}
    max_seats = _setting_int(rows, "fixed_room_max_seats") or 10
    collect = _setting_int(rows, "fixed_room_collect_seconds") or 600
    rake = _setting_percent(rows, "fixed_room_rake_percent")
    if rake == 0 and "fixed_room_rake_percent" not in rows:
        rake = money(default_numeric("fixed_room_rake_percent"))
    return RoomConfig(
        enabled=bool(settings.enabled_games.get(GAME_TYPE, False)),
        max_seats=max(2, min(max_seats, 20)),
        collect_seconds=max(30, min(collect, 3600)),
        rake_percent=rake,
        min_bet=settings.min_bet_rub,
        max_bet=settings.max_bet_rub,
    )


def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    _subscribers.discard(queue)


def publish(payload: Mapping[str, object]) -> None:
    for queue in list(_subscribers):
        try:
            queue.put_nowait(dict(payload))
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(dict(payload))
            except asyncio.QueueFull:
                pass


def ensure_closer() -> None:
    global _closer_started
    if _closer_started:
        return
    _closer_started = True
    asyncio.create_task(_closer_loop())


async def _closer_loop() -> None:
    from db import get_pool

    while True:
        await asyncio.sleep(1)
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await maybe_close_due(conn)
        except Exception:
            logger.exception("fixed-room closer")


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


def _unique_violation(exc: BaseException) -> bool:
    return type(exc).__name__ == "UniqueViolationError"


def _is_bot(seat: Mapping[str, Any]) -> bool:
    return str(seat.get("participant_kind") or "player") == "bot"


def _seat_user(seat: Mapping[str, Any]) -> int | None:
    if _is_bot(seat):
        return None
    raw = seat.get("user_id")
    if raw is None or raw == "":
        return None
    try:
        uid = int(raw)
    except (TypeError, ValueError):
        return None
    # Web-only accounts use negative client_user_id (-1, -2, …). 0 is unused.
    return uid if uid != 0 else None


def _reel_id(seat: Mapping[str, Any]) -> int:
    if _is_bot(seat):
        return bot_reel_id(int(seat["seat_no"]))
    uid = _seat_user(seat)
    return int(uid or 0)


def _human_seats(seats: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [seat for seat in seats if not _is_bot(seat) and _seat_user(seat)]


def _bot_stakes(seats: Sequence[Mapping[str, Any]], stake: Decimal) -> Decimal:
    return money(stake * Decimal(sum(1 for seat in seats if _is_bot(seat))))


def _next_seat_no(seats: Sequence[Mapping[str, Any]], seat_count: int) -> int:
    occupied = {int(seat["seat_no"]) for seat in seats}
    for index in range(int(seat_count)):
        if index not in occupied:
            return index
    raise HTTPException(status_code=409, detail="Комната заполнена")


def _disabled() -> HTTPException:
    return HTTPException(status_code=409, detail="Комнаты выключены")


async def _seats(conn, room_pk: int) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        /* room:seats */
        SELECT s.user_id, s.seat_no, s.hold_order_ref,
               COALESCE(s.participant_kind, 'player') AS participant_kind,
               s.robot_profile_id,
               rp.display_name AS bot_name,
               rp.profile_key AS bot_key
        FROM casino_fixed_room_seats s
        LEFT JOIN casino_robot_profiles rp ON rp.id = s.robot_profile_id
        WHERE s.room_pk = $1
        ORDER BY s.seat_no
        """,
        room_pk,
    )
    return [dict(row) for row in rows]


async def _live_seat(conn, user_id: int):
    return await conn.fetchrow(
        """
        /* room:live-seat */
        SELECT s.room_pk, r.room_id
        FROM casino_fixed_room_seats s
        JOIN casino_fixed_room_rounds r ON r.id = s.room_pk
        WHERE s.user_id = $1 AND r.status IN ('open', 'countdown', 'locked')
        LIMIT 1
        """,
        int(user_id),
    )


def _public_room(
    row: Mapping[str, Any],
    seats: Sequence[Mapping[str, Any]],
    cfg: RoomConfig,
    *,
    actors: Mapping[int, Mapping[str, Any]],
    viewer_id: int | None = None,
) -> dict[str, object]:
    from casino_chat import actor_chip
    from casino_duels import bot_chip

    stake = money(row["stake_rub"])
    pot = money(row["pot_rub"]) if row.get("pot_rub") is not None else money(len(seats) * stake)
    locked = str(row["status"]) in {"locked", "settled"}
    filled = len(seats)
    chance = (100.0 / filled) if filled else 0.0
    players: list[dict[str, object]] = []
    reel_ids: list[int] = []
    my_seat = None
    occupied: set[int] = set()
    for seat in seats:
        seat_no = int(seat["seat_no"])
        occupied.add(seat_no)
        reel = _reel_id(seat)
        reel_ids.append(reel)
        if _is_bot(seat):
            chip = bot_chip(
                str(seat.get("bot_name") or "Бот"),
                profile_id=seat.get("robot_profile_id"),
                profile_key=seat.get("bot_key"),
                seat_no=seat_no,
            )
            display_name = str(chip.get("display_name") or "Бот")
            initial = str(chip.get("initial") or "?")
            avatar_url = chip.get("avatar_url")
            kind = "bot"
        else:
            uid = _seat_user(seat) or 0
            actor = actor_chip(actors, uid)
            display_name = str(actor.get("display_name") or uid)
            initial = str(actor.get("initial") or "?")
            avatar_url = actor.get("avatar_url")
            kind = "player"
            if viewer_id and uid == int(viewer_id):
                my_seat = seat_no
        players.append(
            {
                "user_id": reel,
                "seat_no": seat_no,
                "participant_kind": kind,
                "display_name": display_name,
                "initial": initial,
                "avatar_url": avatar_url,
                "amount_rub": float(stake),
                "chance_pct": chance,
            }
        )
    seat_count = int(row["seat_count"])
    free_seats = [index for index in range(seat_count) if index not in occupied]
    humans = _human_seats(seats)
    seated = my_seat is not None
    open_status = str(row["status"]) == "open"
    return {
        "room_id": str(row["room_id"]),
        "status": str(row["status"]),
        "creator_id": int(row["creator_id"]),
        "commit_hash": str(row["commit_hash"]),
        "server_seed": str(row["server_seed"]) if locked else None,
        "hmac_message": fairness_message(str(row["room_id"]), reel_ids) if reel_ids else str(row["room_id"]),
        "algorithm": HMAC_ALGORITHM,
        "closes_at": _iso(row.get("closes_at")),
        "countdown_ends_at": _iso(row.get("countdown_ends_at")),
        "stake_rub": float(stake),
        "seat_count": seat_count,
        "filled": filled,
        "free_seats": free_seats,
        "pot_rub": float(pot),
        "rake_percent": float(cfg.rake_percent),
        "rake_rub": float(money(row["rake_rub"])) if locked else None,
        "payout_rub": float(money(row["payout_rub"])) if locked else None,
        "winner_id": int(row["winner_id"]) if row.get("winner_id") is not None else None,
        "winner_index": int(row["winner_index"]) if row.get("winner_index") is not None else None,
        "players": players,
        "my_seat": my_seat,
        "my_amount_rub": float(stake) if seated else 0.0,
        "my_chance_pct": chance if seated else 0.0,
        "can_add_bot": bool(
            open_status
            and seated
            and free_seats
            and sum(1 for seat in seats if _is_bot(seat)) < MAX_BOTS_PER_TABLE
        ),
        "can_leave": bool(open_status and seated),
        "can_cancel": bool(
            open_status
            and seated
            and int(row["creator_id"]) == int(viewer_id or 0)
            and len(humans) == 1
        ),
        "min_bet_rub": float(cfg.min_bet),
        "max_bet_rub": float(cfg.max_bet),
        "max_seats": cfg.max_seats,
        "collect_seconds": cfg.collect_seconds,
        "countdown_seconds": START_COUNTDOWN_SECONDS,
        "enabled": cfg.enabled,
    }


async def _named_public(conn, row: Mapping[str, Any], cfg: RoomConfig, viewer_id: int | None) -> dict[str, object]:
    from casino_chat import public_actors

    seats = await _seats(conn, int(row["id"]))
    human_ids = [int(uid) for uid in (_seat_user(seat) for seat in seats) if uid]
    actors = await public_actors(conn, human_ids) if human_ids else {}
    return _public_room(row, seats, cfg, actors=actors, viewer_id=viewer_id)


async def snapshot(conn, room_id: str, *, viewer_id: int | None = None) -> dict[str, object]:
    cfg = await load_room_config(conn)
    await maybe_close_due(conn)
    row = await conn.fetchrow(
        "/* room:get */ SELECT * FROM casino_fixed_room_rounds WHERE room_id = $1",
        room_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    return await _named_public(conn, row, cfg, viewer_id)


async def list_open(conn, *, viewer_id: int | None = None, limit: int = 30) -> dict[str, object]:
    cfg = await load_room_config(conn)
    await maybe_close_due(conn)
    # Комнаты видны только в своей области: фишки и рубли не попадают в одно лобби.
    scope = await viewer_scope(conn, viewer_id)
    # Своя занятая комната видна всегда, иначе смена кошелька прячет живую игру.
    scope_and = await scope_or_mine_filter(
        conn,
        "casino_fixed_room_rounds",
        scope,
        mine_sql=(
            "EXISTS (SELECT 1 FROM casino_fixed_room_seats seat"
            " WHERE seat.room_pk = casino_fixed_room_rounds.id AND seat.user_id = $2)"
        ),
    )
    params: list[object] = [max(1, min(int(limit), 50))]
    if scope_and:
        params.append(int(viewer_id or 0))
    rows = await conn.fetch(
        f"""
        /* room:list-open */
        SELECT * FROM casino_fixed_room_rounds
        WHERE (status IN ('open', 'countdown', 'locked')
           OR (status = 'settled' AND settled_at > now() - interval '20 seconds')){scope_and}
        ORDER BY
            CASE
                WHEN status = 'countdown' THEN 0
                WHEN status = 'locked' THEN 1
                WHEN status = 'settled' THEN 2
                ELSE 3
            END,
            created_at DESC
        LIMIT $1
        """,
        *params,
    )
    rooms = [await _named_public(conn, row, cfg, viewer_id) for row in rows]
    return {
        "enabled": cfg.enabled,
        "rake_percent": float(cfg.rake_percent),
        "max_seats": cfg.max_seats,
        "min_bet_rub": float(cfg.min_bet),
        "max_bet_rub": float(cfg.max_bet),
        "rooms": rooms,
    }


async def _hold_stake(conn, *, user_id: int, room_id: str, amount: Decimal) -> str:
    hold_id = f"fixed-{room_id}-{user_id}-{uuid4().hex[:8]}"
    order_ref = casino_ledger_order_ref(hold_id)
    try:
        await reserve_unified_funds(conn, user_id=user_id, order_ref=order_ref, amount_rub=amount)
        await confirm_unified_hold(
            conn,
            user_id=user_id,
            order_ref=order_ref,
            amount_rub=amount,
            note=f"Fixed room {room_id}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Недостаточно средств") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="Не удалось списать ставку") from exc
    return order_ref


async def _credit(conn, *, room_id: str, user_id: int, amount: Decimal, kind: str) -> None:
    payout = money(amount)
    if payout <= 0 or int(user_id) == 0:
        return
    order_id = casino_operation_ref(kind, room_id, str(user_id))
    if await maybe_credit_tournament_payout(
        conn, user_id=user_id, order_id=order_id, amount_rub=payout, game_id=room_id
    ):
        return
    inserted = await conn.fetchrow(
        """
        /* room:credit */
        INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
        VALUES ($1, 'accrual', $2, $3, $4)
        ON CONFLICT (order_id) DO NOTHING
        RETURNING user_id, amount_rub
        """,
        user_id,
        payout,
        order_id,
        f"Fixed room {kind} {room_id}",
    )
    existing = inserted or await conn.fetchrow(
        "/* room:credit-get */ SELECT user_id, amount_rub FROM user_cashback_ledger WHERE order_id = $1",
        order_id,
    )
    if not existing or int(existing["user_id"]) != user_id or money(existing["amount_rub"]) != payout:
        raise HTTPException(status_code=409, detail="Fixed room payout conflicts")


async def _credit_house(conn, *, amount: Decimal, entry_key: str, reason: str, allow_zero: bool = False) -> None:
    try:
        await credit_house_game_settlement(
            conn,
            amount_rub=amount,
            entry_key=entry_key,
            reason=reason,
            sql_tag="room",
            allow_zero=allow_zero,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _house_reserve(conn, amount: Decimal) -> None:
    stake = money(amount)
    if stake <= 0:
        return
    row = await conn.fetchrow(
        """
        /* room:house-reserve */
        UPDATE casino_house_accounts
        SET reserved_rub = reserved_rub + $1, updated_at = now()
        WHERE account_key = 'main' AND COALESCE(is_active, TRUE)
          AND balance_rub - reserved_rub >= $1
        RETURNING id
        """,
        stake,
    )
    if not row:
        raise HTTPException(status_code=409, detail="Боты сейчас недоступны")


async def _house_release(
    conn,
    amount: Decimal,
    *,
    consume: bool,
    room_id: str | None = None,
) -> None:
    stake = money(amount)
    if stake <= 0:
        return
    if consume:
        entry_key = f"room-bot-consume-{room_id}" if room_id else None
        if entry_key:
            existing = await conn.fetchrow(
                """
                /* room:house-ledger-get */
                SELECT amount_rub FROM casino_house_ledger WHERE entry_key = $1
                """,
                entry_key,
            )
            if existing:
                if money(existing["amount_rub"]) != money(-stake):
                    raise HTTPException(status_code=409, detail="House settlement conflicts")
                return
        await conn.execute(
            """
            /* room:house-release-consume */
            UPDATE casino_house_accounts
            SET reserved_rub = GREATEST(reserved_rub - $1, 0),
                balance_rub = balance_rub - $1,
                updated_at = now()
            WHERE account_key = 'main'
            """,
            stake,
        )
        if entry_key:
            await conn.fetchrow(
                """
                /* room:house-ledger */
                INSERT INTO casino_house_ledger (
                    account_id, entry_key, entry_type, amount_rub, balance_after_rub, reason
                )
                SELECT id, $1, 'game_settlement', $2, balance_rub, $3
                FROM casino_house_accounts WHERE account_key = 'main'
                ON CONFLICT (entry_key) DO NOTHING
                RETURNING id
                """,
                entry_key,
                money(-stake),
                f"Fixed room bot stakes: {room_id}",
            )
        return
    await conn.execute(
        """
        /* room:house-release */
        UPDATE casino_house_accounts
        SET reserved_rub = GREATEST(reserved_rub - $1, 0), updated_at = now()
        WHERE account_key = 'main'
        """,
        stake,
    )


async def _insert_player_seat(conn, *, room_pk: int, user_id: int, seat_no: int, hold_order_ref: str) -> None:
    await conn.execute(
        """
        /* room:insert-seat */
        INSERT INTO casino_fixed_room_seats (
            room_pk, user_id, seat_no, hold_order_ref, participant_kind, robot_profile_id
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        room_pk,
        int(user_id),
        int(seat_no),
        hold_order_ref,
        "player",
        None,
    )


async def _set_pot(conn, room_pk: int, filled: int, stake: Decimal) -> None:
    await conn.execute(
        "/* room:set-pot */ UPDATE casino_fixed_room_rounds SET pot_rub = $2 WHERE id = $1",
        room_pk,
        money(stake * Decimal(filled)),
    )


async def create_room(conn, *, user_id: int, stake_rub: Decimal, seat_count: int) -> dict[str, object]:
    cfg = await load_room_config(conn)
    if not cfg.enabled:
        raise _disabled()
    stake = money(stake_rub)
    seats = int(seat_count)
    if stake < cfg.min_bet or stake > cfg.max_bet:
        raise HTTPException(status_code=400, detail="Ставка вне лимита")
    if seats < 2 or seats > cfg.max_seats:
        raise HTTPException(status_code=400, detail=f"Мест: от 2 до {cfg.max_seats}")
    await lock_casino_users(conn, (user_id,))
    await assert_can_sit(conn, user_id)
    seed = make_server_seed()
    room_id = f"fr-{uuid4().hex[:12]}"
    closes_at = datetime.now(timezone.utc) + timedelta(seconds=cfg.collect_seconds)
    scope = await active_scope(conn, user_id)
    scope_cols, scope_params, scope_values = await scope_insert_sql(
        conn, "casino_fixed_room_rounds", scope, next_index=8
    )
    created = await conn.fetchrow(
        f"""
        /* room:insert */
        INSERT INTO casino_fixed_room_rounds (
            room_id, status, creator_id, stake_rub, seat_count, commit_hash, server_seed, closes_at, pot_rub{scope_cols}
        )
        VALUES ($1, 'open', $2, $3, $4, $5, $6, $7, $3{scope_params})
        RETURNING *
        """,
        room_id,
        int(user_id),
        stake,
        seats,
        commit_seed(seed),
        seed,
        closes_at,
        *scope_values,
    )
    order_ref = await _hold_stake(conn, user_id=user_id, room_id=room_id, amount=stake)
    await _insert_player_seat(
        conn, room_pk=int(created["id"]), user_id=user_id, seat_no=0, hold_order_ref=order_ref
    )
    live = await conn.fetchrow("/* room:get-pk */ SELECT * FROM casino_fixed_room_rounds WHERE id = $1", int(created["id"]))
    snap = await _named_public(conn, live, cfg, user_id)
    publish({"type": "create", "room_id": room_id})
    return snap


async def join_room(conn, *, user_id: int, room_id: str) -> dict[str, object]:
    cfg = await load_room_config(conn)
    if not cfg.enabled:
        raise _disabled()
    await maybe_close_due(conn)
    row = await conn.fetchrow(
        "/* room:lock */ SELECT * FROM casino_fixed_room_rounds WHERE room_id = $1 FOR UPDATE",
        room_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    if str(row["status"]) != "open":
        raise HTTPException(status_code=409, detail="Комната уже закрыта")
    seats = await _seats(conn, int(row["id"]))
    if any(_seat_user(seat) == int(user_id) for seat in seats):
        return await _named_public(conn, row, cfg, user_id)
    if len(seats) >= int(row["seat_count"]):
        raise HTTPException(status_code=409, detail="Комната заполнена")
    await assert_player_may_sit(conn, row, user_id)
    await lock_casino_users(conn, (user_id,))
    await assert_can_sit(conn, user_id)
    stake = money(row["stake_rub"])
    order_ref = await _hold_stake(conn, user_id=user_id, room_id=str(row["room_id"]), amount=stake)
    seat_no = _next_seat_no(seats, int(row["seat_count"]))
    try:
        await _insert_player_seat(
            conn, room_pk=int(row["id"]), user_id=user_id, seat_no=seat_no, hold_order_ref=order_ref
        )
    except Exception as exc:
        if _unique_violation(exc):
            raise HTTPException(status_code=409, detail="Вы уже в этой комнате") from exc
        raise
    await _set_pot(conn, int(row["id"]), len(seats) + 1, stake)
    publish({"type": "join", "room_id": str(row["room_id"])})
    from casino_inbox import notify_player_joined

    other_ids = [int(uid) for uid in (_seat_user(seat) for seat in seats) if uid]
    creator = int(row["creator_id"])
    if creator not in other_ids and creator != int(user_id):
        other_ids.append(creator)
    await notify_player_joined(
        conn,
        joiner_id=int(user_id),
        other_ids=other_ids,
        kind="room",
        game_id=str(row["room_id"]),
        game_type="fixed_room",
        stake_rub=stake,
    )
    if len(seats) + 1 >= int(row["seat_count"]):
        await _begin_countdown(conn, room_pk=int(row["id"]), room_id=str(row["room_id"]))
        settled = await conn.fetchrow("/* room:get-pk */ SELECT * FROM casino_fixed_room_rounds WHERE id = $1", int(row["id"]))
        return await _named_public(conn, settled, cfg, user_id)
    live_row = await conn.fetchrow("/* room:get-pk */ SELECT * FROM casino_fixed_room_rounds WHERE id = $1", int(row["id"]))
    return await _named_public(conn, live_row, cfg, user_id)


async def add_bot(conn, *, user_id: int, room_id: str) -> dict[str, object]:
    cfg = await load_room_config(conn)
    if not cfg.enabled:
        raise _disabled()
    await maybe_close_due(conn)
    row = await conn.fetchrow(
        "/* room:lock */ SELECT * FROM casino_fixed_room_rounds WHERE room_id = $1 FOR UPDATE",
        room_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    if str(row["status"]) != "open":
        raise HTTPException(status_code=409, detail="Комната уже закрыта")
    seats = await _seats(conn, int(row["id"]))
    if not any(_seat_user(seat) == int(user_id) for seat in seats):
        raise HTTPException(status_code=409, detail="Сначала сядьте в комнату")
    if len(seats) >= int(row["seat_count"]):
        raise HTTPException(status_code=409, detail="Комната заполнена")
    if sum(1 for seat in seats if _is_bot(seat)) >= MAX_BOTS_PER_TABLE:
        raise HTTPException(
            status_code=409,
            detail=f"В комнате может быть не больше {MAX_BOTS_PER_TABLE} бота",
        )
    stake = money(row["stake_rub"])
    profile = await conn.fetchrow(
        """
        /* room:bot-profile */
        SELECT rp.id, rp.account_id, rp.display_name, rp.profile_key
        FROM casino_robot_profiles rp
        JOIN casino_house_accounts ha ON ha.id = rp.account_id
        WHERE rp.mode = 'pvp_robot' AND rp.is_active AND COALESCE(ha.is_active, TRUE)
          AND rp.allowed_games ? $1 AND rp.min_bet_rub <= $2 AND rp.max_bet_rub >= $2
        ORDER BY rp.id
        LIMIT 1
        """,
        GAME_TYPE,
        stake,
    )
    if not profile:
        raise HTTPException(status_code=409, detail="Боты сейчас недоступны")
    if scope_from_row(row).is_rub:
        await _house_reserve(conn, stake)
    seat_no = _next_seat_no(seats, int(row["seat_count"]))
    hold = f"house-fixed-{row['room_id']}-s{seat_no}"
    await conn.execute(
        """
        /* room:insert-seat */
        INSERT INTO casino_fixed_room_seats (
            room_pk, user_id, seat_no, hold_order_ref, participant_kind, robot_profile_id
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        int(row["id"]),
        None,
        seat_no,
        hold,
        "bot",
        int(profile["id"]),
    )
    await _set_pot(conn, int(row["id"]), len(seats) + 1, stake)
    publish({"type": "join", "room_id": str(row["room_id"])})
    if len(seats) + 1 >= int(row["seat_count"]):
        await _begin_countdown(conn, room_pk=int(row["id"]), room_id=str(row["room_id"]))
        settled = await conn.fetchrow("/* room:get-pk */ SELECT * FROM casino_fixed_room_rounds WHERE id = $1", int(row["id"]))
        return await _named_public(conn, settled, cfg, user_id)
    live_row = await conn.fetchrow("/* room:get-pk */ SELECT * FROM casino_fixed_room_rounds WHERE id = $1", int(row["id"]))
    return await _named_public(conn, live_row, cfg, user_id)


async def leave_room(conn, *, user_id: int, room_id: str) -> dict[str, object]:
    cfg = await load_room_config(conn)
    row = await conn.fetchrow(
        "/* room:lock */ SELECT * FROM casino_fixed_room_rounds WHERE room_id = $1 FOR UPDATE",
        room_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    if str(row["status"]) != "open":
        raise HTTPException(status_code=409, detail="Из этой комнаты уже нельзя выйти")
    seats = await _seats(conn, int(row["id"]))
    mine = next((seat for seat in seats if _seat_user(seat) == int(user_id)), None)
    if not mine:
        raise HTTPException(status_code=409, detail="Вы не в этой комнате")
    await _refund_seat(conn, row=row, seat=mine)
    await conn.execute(
        "/* room:delete-seat */ DELETE FROM casino_fixed_room_seats WHERE room_pk = $1 AND seat_no = $2",
        int(row["id"]),
        int(mine["seat_no"]),
    )
    leftover = [seat for seat in seats if int(seat["seat_no"]) != int(mine["seat_no"])]
    if not _human_seats(leftover):
        await _refund(conn, row=row, seats=leftover)
        refunded = await conn.fetchrow("/* room:get-pk */ SELECT * FROM casino_fixed_room_rounds WHERE id = $1", int(row["id"]))
        return await _named_public(conn, refunded, cfg, user_id)
    await _set_pot(conn, int(row["id"]), len(leftover), money(row["stake_rub"]))
    publish({"type": "leave", "room_id": str(row["room_id"])})
    live = await conn.fetchrow("/* room:get-pk */ SELECT * FROM casino_fixed_room_rounds WHERE id = $1", int(row["id"]))
    return await _named_public(conn, live, cfg, user_id)


async def cancel_room(conn, *, user_id: int, room_id: str) -> dict[str, object]:
    cfg = await load_room_config(conn)
    row = await conn.fetchrow(
        "/* room:lock */ SELECT * FROM casino_fixed_room_rounds WHERE room_id = $1 FOR UPDATE",
        room_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    if str(row["status"]) != "open":
        raise HTTPException(status_code=409, detail="Комнату уже нельзя отменить")
    if int(row["creator_id"]) != int(user_id):
        raise HTTPException(status_code=403, detail="Отменить может только создатель")
    seats = await _seats(conn, int(row["id"]))
    humans = _human_seats(seats)
    if len(humans) != 1 or _seat_user(humans[0]) != int(user_id):
        raise HTTPException(status_code=409, detail="Отмена только пока вы один живой в комнате")
    await _refund(conn, row=row, seats=seats)
    refunded = await conn.fetchrow("/* room:get-pk */ SELECT * FROM casino_fixed_room_rounds WHERE id = $1", int(row["id"]))
    return await _named_public(conn, refunded, cfg, user_id)


async def _refund_seat(conn, *, row: Mapping[str, Any], seat: Mapping[str, Any]) -> None:
    stake = money(row["stake_rub"])
    if _is_bot(seat):
        if scope_from_row(row).is_rub:
            await _house_release(conn, stake, consume=False)
        return
    uid = _seat_user(seat)
    if uid:
        await _credit(conn, room_id=str(row["room_id"]), user_id=uid, amount=stake, kind="refund")


async def _refund(conn, *, row: Mapping[str, Any], seats: Sequence[Mapping[str, Any]]) -> None:
    for seat in seats:
        await _refund_seat(conn, row=row, seat=seat)
    await conn.execute(
        """
        /* room:refund */
        UPDATE casino_fixed_room_rounds
        SET status = 'refunded', settled_at = now()
        WHERE id = $1
        """,
        int(row["id"]),
    )
    publish({"type": "refund", "room_id": str(row["room_id"])})


def _spin_event(snap: Mapping[str, Any]) -> dict[str, object]:
    return {
        "type": "spin",
        "room_id": snap["room_id"],
        "winner_id": snap.get("winner_id"),
        "winner_index": snap.get("winner_index"),
        "commit_hash": snap.get("commit_hash"),
        "server_seed": snap.get("server_seed"),
        "hmac_message": snap.get("hmac_message"),
        "pot_rub": snap.get("pot_rub"),
        "rake_rub": snap.get("rake_rub"),
        "payout_rub": snap.get("payout_rub"),
        "players": snap.get("players") or [],
        "seat_count": snap.get("seat_count"),
        "stake_rub": snap.get("stake_rub"),
        "rake_percent": snap.get("rake_percent"),
    }


async def _lock_and_settle(conn, *, room_pk: int, cfg: RoomConfig) -> None:
    row = await conn.fetchrow(
        "/* room:lock-pk */ SELECT * FROM casino_fixed_room_rounds WHERE id = $1 FOR UPDATE",
        room_pk,
    )
    if not row or str(row["status"]) not in {"open", "countdown"}:
        return
    seats = await _seats(conn, room_pk)
    if len(seats) < int(row["seat_count"]):
        return
    reel_ids = [_reel_id(seat) for seat in seats]
    message = fairness_message(str(row["room_id"]), reel_ids)
    seed = str(row["server_seed"])
    index = hmac_index(seed, message, len(reel_ids))
    winner_id = reel_ids[index]
    pot = money(money(row["stake_rub"]) * Decimal(len(seats)))
    rake, payout = rake_split(pot, cfg.rake_percent)
    stake = money(row["stake_rub"])
    wager = {str(uid): str(stake) for uid in (_seat_user(seat) for seat in seats) if uid}
    await conn.execute(
        """
        /* room:lock-set */
        UPDATE casino_fixed_room_rounds
        SET status = 'locked', locked_at = now(), winner_id = $2, winner_index = $3,
            pot_rub = $4, rake_rub = $5, payout_rub = $6, wager_json = $7::jsonb
        WHERE id = $1
        """,
        room_pk,
        winner_id,
        index,
        pot,
        rake,
        payout,
        json.dumps(wager),
    )
    locked = await conn.fetchrow("/* room:get-pk */ SELECT * FROM casino_fixed_room_rounds WHERE id = $1", room_pk)
    spin_view = await _named_public(conn, locked, cfg, None)
    publish({"type": "lock", "room_id": str(row["room_id"]), "winner_id": winner_id, "winner_index": index})
    publish(_spin_event(spin_view))
    bot_total = _bot_stakes(seats, stake)
    room_id = str(row["room_id"])
    room_scope = scope_from_row(row)
    if room_scope.is_rub:
        await _house_release(conn, bot_total, consume=True, room_id=room_id)
    winner_human = next((seat for seat in seats if not _is_bot(seat) and _reel_id(seat) == winner_id), None)
    if winner_human is not None:
        await _credit(conn, room_id=room_id, user_id=winner_id, amount=payout, kind="payout")
    elif room_scope.is_rub:
        await _credit_house(
            conn,
            amount=payout,
            entry_key=f"room-bot-payout-{room_id}",
            reason=f"Fixed room bot win {room_id}",
        )
    if room_scope.is_rub:
        await _credit_house(
            conn,
            amount=rake,
            entry_key=f"room-rake-{room_id}",
            reason=f"Fixed room rake {room_id}",
            allow_zero=True,
        )
    await conn.execute(
        "/* room:settle */ UPDATE casino_fixed_room_rounds SET status = 'settled', settled_at = now() WHERE id = $1",
        room_pk,
    )
    publish({"type": "settled", "room_id": str(row["room_id"]), "winner_id": winner_id})
    from casino_level_bonus import maybe_grant_reached_level_bonuses

    humans = [int(uid) for uid in (_seat_user(seat) for seat in seats) if uid]
    if humans:
        await maybe_grant_reached_level_bonuses(conn, *humans)


async def _begin_countdown(conn, *, room_pk: int, room_id: str) -> None:
    ends = countdown_deadline()
    await conn.execute(
        """
        /* room:countdown */
        UPDATE casino_fixed_room_rounds
        SET status = 'countdown', countdown_ends_at = $2
        WHERE id = $1 AND status = 'open'
        """,
        room_pk,
        ends,
    )
    publish({"type": "countdown", "room_id": room_id, "countdown_ends_at": _iso(ends)})


async def maybe_close_due(conn) -> None:
    rows = await conn.fetch(
        """
        /* room:due */
        SELECT id FROM casino_fixed_room_rounds
        WHERE status = 'open' AND closes_at IS NOT NULL AND closes_at <= now()
        ORDER BY id
        LIMIT 20
        """
    )
    for item in rows:
        row = await conn.fetchrow(
            "/* room:lock-pk */ SELECT * FROM casino_fixed_room_rounds WHERE id = $1 FOR UPDATE",
            int(item["id"]),
        )
        if not row or str(row["status"]) != "open":
            continue
        seats = await _seats(conn, int(row["id"]))
        await _refund(conn, row=row, seats=seats)
    due_start = await conn.fetch(
        """
        /* room:due-countdown */
        SELECT id FROM casino_fixed_room_rounds
        WHERE status = 'countdown' AND countdown_ends_at IS NOT NULL AND countdown_ends_at <= now()
        ORDER BY id
        LIMIT 20
        """
    )
    if due_start:
        cfg = await load_room_config(conn)
        for item in due_start:
            await _lock_and_settle(conn, room_pk=int(item["id"]), cfg=cfg)
