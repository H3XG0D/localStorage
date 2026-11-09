"""Web NLHE cash tables: sit/leave escrow, one shared shoe per hand, versioned actions."""
from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping
from uuid import uuid4

from fastapi import HTTPException

from casino_cards import DEFAULT_CLIENT_SEED, game_commit, holdem_shuffled_deck
from casino_finance import (
    casino_ledger_order_ref,
    casino_operation_ref,
    confirm_unified_hold,
    load_casino_settings,
    money,
    reserve_unified_funds,
)
from casino_holdem import (
    MAX_SEATS,
    MIN_SEATS,
    HandState,
    HoldemError,
    apply_action,
    apply_mid_hand_fold,
    apply_rake,
    apply_timeout,
    next_button,
    hand_seed_public,
    public_view,
    start_hand,
)
from casino_settings_registry import default_numeric, REGISTRY

GAME_TYPE = "holdem"
_subscribers: dict[str, set[asyncio.Queue]] = {}


@dataclass(frozen=True)
class HoldemConfig:
    enabled: bool
    small_blind: Decimal
    big_blind: Decimal
    rake_percent: Decimal
    rake_cap: Decimal
    timeout_seconds: int
    min_buyin: Decimal
    max_buyin: Decimal


def _setting_amount(values: Mapping[str, object], key: str) -> Decimal:
    raw = values.get(key)
    if isinstance(raw, Mapping) and raw.get("amount") is not None:
        return money(raw["amount"])
    if key in REGISTRY:
        return money(default_numeric(key))
    return money(0)


def _setting_percent(values: Mapping[str, object], key: str) -> Decimal:
    raw = values.get(key)
    if isinstance(raw, Mapping) and raw.get("percent") is not None:
        return money(raw["percent"])
    if key in REGISTRY:
        return money(REGISTRY[key].default)  # type: ignore[arg-type]
    return money(0)


def _setting_int(values: Mapping[str, object], key: str) -> int:
    raw = values.get(key)
    if isinstance(raw, Mapping) and raw.get("value") is not None:
        return int(raw["value"])
    spec = REGISTRY.get(key)
    if spec is not None:
        return int(spec.default)  # type: ignore[arg-type]
    return 0


def buyin_bounds(big_blind: Decimal, min_bb: int, max_bb: int) -> tuple[Decimal, Decimal]:
    bb = money(big_blind)
    lo_bb = max(2, min(int(min_bb), int(max_bb)))
    hi_bb = max(2, max(int(min_bb), int(max_bb)))
    return money(bb * lo_bb), money(bb * hi_bb)


def escrow_total(stacks: Mapping[int, Decimal], pot: Decimal) -> Decimal:
    return money(sum((money(v) for v in stacks.values()), Decimal("0")) + money(pot))


def holdem_config_from_rows(rows: Mapping[str, object], enabled: bool) -> HoldemConfig:
    sb = _setting_amount(rows, "holdem_small_blind_rub")
    bb = _setting_amount(rows, "holdem_big_blind_rub")
    if bb < sb:
        bb = sb
    min_bb = _setting_int(rows, "holdem_min_buyin_bb")
    max_bb = _setting_int(rows, "holdem_max_buyin_bb")
    lo, hi = buyin_bounds(bb, min_bb, max_bb)
    timeout = _setting_int(rows, "holdem_action_timeout_seconds")
    return HoldemConfig(
        enabled=bool(enabled),
        small_blind=sb,
        big_blind=bb,
        rake_percent=_setting_percent(rows, "holdem_rake_percent"),
        rake_cap=_setting_amount(rows, "holdem_rake_cap_rub"),
        timeout_seconds=max(5, min(300, timeout or 30)),
        min_buyin=lo,
        max_buyin=hi,
    )


async def load_holdem_config(conn) -> HoldemConfig:
    settings = await load_casino_settings(conn)
    rows = {str(row["key"]): row["value"] for row in await conn.fetch("SELECT key, value FROM casino_settings")}
    limits = settings.per_game_limits.get(GAME_TYPE) or {}
    cfg = holdem_config_from_rows(rows, bool(settings.enabled_games.get(GAME_TYPE, False)))
    min_buy = money(limits["min"]) if "min" in limits else cfg.min_buyin
    max_buy = money(limits["max"]) if "max" in limits else cfg.max_buyin
    if min_buy > max_buy:
        min_buy, max_buy = cfg.min_buyin, cfg.max_buyin
    return HoldemConfig(
        enabled=cfg.enabled,
        small_blind=cfg.small_blind,
        big_blind=cfg.big_blind,
        rake_percent=cfg.rake_percent,
        rake_cap=cfg.rake_cap,
        timeout_seconds=cfg.timeout_seconds,
        min_buyin=min_buy,
        max_buyin=max_buy,
    )


def publish_table(table_id: str, version: int) -> None:
    payload = {"type": "table", "table_id": table_id, "state_version": version}
    dead: list[asyncio.Queue] = []
    for queue in list(_subscribers.get(table_id, ())):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(queue)
    for queue in dead:
        _subscribers.get(table_id, set()).discard(queue)


def subscribe_table(table_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=32)
    _subscribers.setdefault(table_id, set()).add(queue)
    return queue


def unsubscribe_table(table_id: str, queue: asyncio.Queue) -> None:
    group = _subscribers.get(table_id)
    if not group:
        return
    group.discard(queue)
    if not group:
        _subscribers.pop(table_id, None)


async def _credit_stack(conn, *, user_id: int, table_id: str, amount: Decimal, note: str) -> None:
    payout = money(amount)
    if payout <= 0:
        return
    order_id = casino_operation_ref("poker-leave", table_id, str(user_id))
    inserted = await conn.fetchrow(
        """
        INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
        VALUES ($1, 'accrual', $2, $3, $4)
        ON CONFLICT (order_id) DO NOTHING
        RETURNING user_id, amount_rub
        """,
        user_id,
        payout,
        order_id,
        note,
    )
    existing = inserted or await conn.fetchrow(
        "SELECT user_id, amount_rub FROM user_cashback_ledger WHERE order_id = $1",
        order_id,
    )
    if not existing or int(existing["user_id"]) != user_id or money(existing["amount_rub"]) != payout:
        raise HTTPException(status_code=409, detail="Poker cash-out conflicts")


async def _lock_table(conn, table_id: str):
    row = await conn.fetchrow(
        "SELECT * FROM casino_poker_tables WHERE table_id = $1 FOR UPDATE",
        table_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Стол не найден")
    return dict(row)


async def _seats(conn, table_pk: int) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT seat_no, user_id, stack_rub, buy_in_rub, status
        FROM casino_poker_seats
        WHERE table_pk = $1
        ORDER BY seat_no
        """,
        table_pk,
    )
    return [dict(row) for row in rows]


def _deadline(seconds: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=int(seconds))


async def create_table(
    conn,
    *,
    creator_id: int,
    max_seats: int,
    config: HoldemConfig | None = None,
) -> dict[str, Any]:
    cfg = config or await load_holdem_config(conn)
    if not cfg.enabled:
        raise HTTPException(status_code=409, detail="Покер выключен")
    seats = int(max_seats)
    if seats < MIN_SEATS or seats > MAX_SEATS:
        raise HTTPException(status_code=400, detail="За столом 2–6 мест")
    table_id = f"pk-{uuid4().hex[:12]}"
    await conn.execute(
        """
        INSERT INTO casino_poker_tables (
            table_id, creator_id, max_seats, small_blind_rub, big_blind_rub, status
        ) VALUES ($1, $2, $3, $4, $5, 'open')
        """,
        table_id,
        creator_id,
        seats,
        cfg.small_blind,
        cfg.big_blind,
    )
    publish_table(table_id, 0)
    return await snapshot(conn, table_id=table_id, viewer_id=creator_id, config=cfg)


async def sit(
    conn,
    *,
    table_id: str,
    user_id: int,
    seat_no: int,
    buy_in_rub: Decimal,
    config: HoldemConfig | None = None,
) -> dict[str, Any]:
    cfg = config or await load_holdem_config(conn)
    if not cfg.enabled:
        raise HTTPException(status_code=409, detail="Покер выключен")
    table = await _lock_table(conn, table_id)
    if table["status"] == "closed":
        raise HTTPException(status_code=409, detail="Стол закрыт")
    seat = int(seat_no)
    if seat < 1 or seat > int(table["max_seats"]):
        raise HTTPException(status_code=400, detail="Нет такого места")
    buy_in = money(buy_in_rub)
    if buy_in < cfg.min_buyin or buy_in > cfg.max_buyin:
        raise HTTPException(
            status_code=400,
            detail=f"Бай-ин {cfg.min_buyin}–{cfg.max_buyin} ₽",
        )
    occupied = await _seats(conn, int(table["id"]))
    if any(int(row["user_id"]) == user_id for row in occupied):
        raise HTTPException(status_code=409, detail="Вы уже за этим столом")
    if any(int(row["seat_no"]) == seat for row in occupied):
        raise HTTPException(status_code=409, detail="Место занято")
    elsewhere = await conn.fetchval(
        "SELECT COUNT(*) FROM casino_poker_seats WHERE user_id = $1 AND status = 'sitting'",
        user_id,
    )
    if int(elsewhere or 0) > 0:
        raise HTTPException(status_code=409, detail="Сначала встаньте с другого стола")
    hold_id = f"poker-{table_id}-s{seat}-{user_id}"
    order_ref = casino_ledger_order_ref(hold_id)
    try:
        await reserve_unified_funds(conn, user_id=user_id, order_ref=order_ref, amount_rub=buy_in)
        await confirm_unified_hold(
            conn,
            user_id=user_id,
            order_ref=order_ref,
            amount_rub=buy_in,
            note=f"Poker buy-in {table_id}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Недостаточно средств") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="Не удалось списать бай-ин") from exc
    await conn.execute(
        """
        INSERT INTO casino_poker_seats (table_pk, seat_no, user_id, stack_rub, buy_in_rub, status)
        VALUES ($1, $2, $3, $4, $4, 'sitting')
        """,
        int(table["id"]),
        seat,
        user_id,
        buy_in,
    )
    escrow = money(table["escrow_rub"]) + buy_in
    await conn.execute(
        """
        UPDATE casino_poker_tables
        SET escrow_rub = $2, state_version = state_version + 1, updated_at = now(), status = 'open'
        WHERE id = $1
        """,
        int(table["id"]),
        escrow,
    )
    await _maybe_start_hand(conn, table_id=table_id, config=cfg)
    from casino_inbox import notify_player_joined

    other_ids = [int(row["user_id"]) for row in occupied]
    creator = int(table["creator_id"])
    if creator not in other_ids and creator != int(user_id):
        other_ids.append(creator)
    await notify_player_joined(
        conn,
        joiner_id=int(user_id),
        other_ids=other_ids,
        kind="poker",
        game_id=str(table_id),
        game_type="holdem",
        stake_rub=buy_in,
    )
    snap = await snapshot(conn, table_id=table_id, viewer_id=user_id, config=cfg)
    publish_table(table_id, int(snap["state_version"]))
    return snap


async def leave(conn, *, table_id: str, user_id: int, config: HoldemConfig | None = None) -> dict[str, Any]:
    cfg = config or await load_holdem_config(conn)
    table = await _lock_table(conn, table_id)
    seats = await _seats(conn, int(table["id"]))
    mine = next((row for row in seats if int(row["user_id"]) == user_id), None)
    if not mine:
        raise HTTPException(status_code=409, detail="Вы не за столом")
    hand = await _current_hand(conn, table)
    if hand and str(hand["status"]) == "running":
        state = HandState.from_dict(hand["game_state"])
        if int(mine["seat_no"]) in state.seats and not state.seats[int(mine["seat_no"])].folded:
            apply_mid_hand_fold(state, int(mine["seat_no"]))
            await _persist_hand(conn, table=table, hand=hand, state=state, config=cfg)
        await conn.execute(
            "UPDATE casino_poker_seats SET status = 'leaving' WHERE table_pk = $1 AND user_id = $2",
            int(table["id"]),
            user_id,
        )
        if state.street == "complete":
            await _finish_hand(conn, table_id=table_id, config=cfg)
        snap = await snapshot(conn, table_id=table_id, viewer_id=user_id, config=cfg)
        publish_table(table_id, int(snap["state_version"]))
        return snap
    await _cash_out_seat(conn, table=table, seat=mine)
    await _maybe_close_table(conn, int(table["id"]))
    snap = await snapshot(conn, table_id=table_id, viewer_id=user_id, config=cfg)
    publish_table(table_id, int(snap["state_version"]))
    return snap


async def _cash_out_seat(conn, *, table: Mapping[str, Any], seat: Mapping[str, Any]) -> None:
    stack = money(seat["stack_rub"])
    table_id = str(table["table_id"])
    user_id = int(seat["user_id"])
    order_suffix = f"{int(seat['seat_no'])}-{user_id}-{int(table['state_version'])}"
    await _credit_stack(
        conn,
        user_id=user_id,
        table_id=f"{table_id}-{order_suffix}",
        amount=stack,
        note=f"Poker leave {table_id}",
    )
    await conn.execute(
        "DELETE FROM casino_poker_seats WHERE table_pk = $1 AND user_id = $2",
        int(table["id"]),
        user_id,
    )
    escrow = money(max(Decimal("0"), money(table["escrow_rub"]) - stack))
    await conn.execute(
        """
        UPDATE casino_poker_tables
        SET escrow_rub = $2, state_version = state_version + 1, updated_at = now()
        WHERE id = $1
        """,
        int(table["id"]),
        escrow,
    )
    table["escrow_rub"] = escrow
    table["state_version"] = int(table["state_version"]) + 1


async def _maybe_close_table(conn, table_pk: int) -> None:
    remaining = await conn.fetchval(
        "SELECT COUNT(*) FROM casino_poker_seats WHERE table_pk = $1",
        table_pk,
    )
    if int(remaining or 0) == 0:
        await conn.execute(
            "UPDATE casino_poker_tables SET status = 'closed', current_hand_id = NULL, updated_at = now() WHERE id = $1",
            table_pk,
        )


async def _current_hand(conn, table: Mapping[str, Any]) -> dict[str, Any] | None:
    hand_id = table.get("current_hand_id")
    if not hand_id:
        return None
    row = await conn.fetchrow("SELECT * FROM casino_poker_hands WHERE id = $1 FOR UPDATE", int(hand_id))
    return dict(row) if row else None


async def _maybe_start_hand(conn, *, table_id: str, config: HoldemConfig) -> None:
    table = await _lock_table(conn, table_id)
    if table.get("current_hand_id"):
        hand = await _current_hand(conn, table)
        if hand and str(hand["status"]) == "running":
            return
    seats = [row for row in await _seats(conn, int(table["id"])) if str(row["status"]) == "sitting" and money(row["stack_rub"]) > 0]
    if len(seats) < MIN_SEATS:
        await conn.execute(
            "UPDATE casino_poker_tables SET status = 'open', current_hand_id = NULL, updated_at = now() WHERE id = $1",
            int(table["id"]),
        )
        return
        await conn.execute(
            "UPDATE casino_poker_tables SET status = 'open', current_hand_id = NULL, updated_at = now() WHERE id = $1",
            int(table["id"]),
        )
        return
    stacks = {int(row["seat_no"]): money(row["stack_rub"]) for row in seats}
    seated_nos = sorted(stacks)
    previous = table.get("button_seat")
    button = int(previous) if previous in seated_nos else seated_nos[0]
    if previous in seated_nos:
        button = next_button(seated_nos, int(previous))
    last_no = await conn.fetchval(
        "SELECT COALESCE(MAX(hand_no), 0) FROM casino_poker_hands WHERE table_pk = $1",
        int(table["id"]),
    )
    hand_no = int(last_no or 0) + 1
    hand_key = f"{table_id}-h{hand_no}"
    server_seed = secrets.token_hex(32)
    commit = game_commit(server_seed, hand_key)
    deck = holdem_shuffled_deck(server_seed, client_seed=DEFAULT_CLIENT_SEED, nonce=hand_no, hand_id=hand_key)
    state = start_hand(
        hand_id=hand_key,
        stacks=stacks,
        button=button,
        small_blind=config.small_blind,
        big_blind=config.big_blind,
        deck=deck,
    )
    deadline = _deadline(config.timeout_seconds) if state.to_act is not None else None
    row = await conn.fetchrow(
        """
        INSERT INTO casino_poker_hands (
            table_pk, hand_key, hand_no, status, commit_hash, server_seed, client_seed,
            nonce, game_state, action_deadline_at
        ) VALUES ($1, $2, $3, 'running', $4, $5, $6, $7, $8::jsonb, $9)
        RETURNING id
        """,
        int(table["id"]),
        hand_key,
        hand_no,
        commit,
        server_seed,
        DEFAULT_CLIENT_SEED,
        hand_no,
        json.dumps(state.to_dict()),
        deadline,
    )
    await conn.execute(
        """
        UPDATE casino_poker_tables
        SET status = 'running', button_seat = $2, current_hand_id = $3,
            state_version = state_version + 1, updated_at = now()
        WHERE id = $1
        """,
        int(table["id"]),
        button,
        int(row["id"]),
    )
    if state.street == "complete":
        await _finish_hand(conn, table_id=table_id, config=config, chain=False)


async def _persist_hand(
    conn,
    *,
    table: Mapping[str, Any],
    hand: Mapping[str, Any],
    state: HandState,
    config: HoldemConfig,
) -> None:
    deadline = _deadline(config.timeout_seconds) if state.to_act is not None and state.street not in {"complete", "showdown"} else None
    await conn.execute(
        """
        UPDATE casino_poker_hands
        SET game_state = $2::jsonb, action_deadline_at = $3, status = $4
        WHERE id = $1
        """,
        int(hand["id"]),
        json.dumps(state.to_dict()),
        deadline,
        "complete" if state.street == "complete" else "running",
    )
    await conn.execute(
        "UPDATE casino_poker_tables SET state_version = state_version + 1, updated_at = now() WHERE id = $1",
        int(table["id"]),
    )


async def _finish_hand(conn, *, table_id: str, config: HoldemConfig, chain: bool = True) -> None:
    table = await _lock_table(conn, table_id)
    hand = await _current_hand(conn, table)
    if not hand:
        return
    state = HandState.from_dict(hand["game_state"])
    if state.street != "complete":
        return
    apply_rake(state, config.rake_percent, config.rake_cap)
    seats = await _seats(conn, int(table["id"]))
    by_no = {int(row["seat_no"]): row for row in seats}
    for num, seat_state in state.seats.items():
        if num not in by_no:
            continue
        await conn.execute(
            "UPDATE casino_poker_seats SET stack_rub = $3 WHERE table_pk = $1 AND seat_no = $2",
            int(table["id"]),
            num,
            money(seat_state.stack),
        )
        by_no[num]["stack_rub"] = money(seat_state.stack)
    wager: dict[str, str] = {}
    for num, amount in state.wagers.items():
        row = by_no.get(int(num))
        if row:
            wager[str(int(row["user_id"]))] = str(money(amount))
    rake = money(state.rake)
    stacks = {int(row["seat_no"]): money(row["stack_rub"]) for row in by_no.values()}
    escrow = escrow_total(stacks, Decimal("0"))
    await conn.execute(
        """
        UPDATE casino_poker_hands
        SET status = 'complete', game_state = $2::jsonb, rake_rub = $3, wager_json = $4::jsonb,
            seed_revealed_at = CASE WHEN $5::bool THEN now() ELSE NULL END,
            settled_at = now(), action_deadline_at = NULL
        WHERE id = $1
        """,
        int(hand["id"]),
        json.dumps(state.to_dict()),
        rake,
        json.dumps(wager),
        bool(state.cards_shown),
    )
    from casino_level_bonus import maybe_grant_reached_level_bonuses

    await maybe_grant_reached_level_bonuses(conn, *[int(uid) for uid in wager])
    await conn.execute(
        """
        UPDATE casino_poker_tables
        SET escrow_rub = $2, house_rake_rub = house_rake_rub + $3, current_hand_id = NULL,
            status = 'open', state_version = state_version + 1, updated_at = now()
        WHERE id = $1
        """,
        int(table["id"]),
        escrow,
        rake,
    )
    table["escrow_rub"] = escrow
    table["current_hand_id"] = None
    refreshed = await _seats(conn, int(table["id"]))
    for row in refreshed:
        busted = money(row["stack_rub"]) <= 0
        leaving = str(row["status"]) == "leaving"
        if busted or leaving:
            await _cash_out_seat(conn, table=table, seat=row)
    if chain:
        await _maybe_start_hand(conn, table_id=table_id, config=config)


async def _apply_due_timeout(conn, *, table: Mapping[str, Any], hand: Mapping[str, Any], config: HoldemConfig) -> HandState:
    state = HandState.from_dict(hand["game_state"])
    deadline = hand.get("action_deadline_at")
    if state.to_act is None or not deadline:
        return state
    now = datetime.now(timezone.utc)
    due = deadline if getattr(deadline, "tzinfo", None) else deadline.replace(tzinfo=timezone.utc)
    if due > now:
        return state
    apply_timeout(state)
    await _persist_hand(conn, table=table, hand=hand, state=state, config=config)
    if state.street == "complete":
        await _finish_hand(conn, table_id=str(table["table_id"]), config=config)
        table = await _lock_table(conn, str(table["table_id"]))
        hand = await _current_hand(conn, table) or hand
        if hand and str(hand["status"]) == "running":
            return HandState.from_dict(hand["game_state"])
    return state


async def act(
    conn,
    *,
    table_id: str,
    user_id: int,
    action: str,
    amount_rub: Decimal | None,
    expected_version: int,
    config: HoldemConfig | None = None,
) -> dict[str, Any]:
    cfg = config or await load_holdem_config(conn)
    table = await _lock_table(conn, table_id)
    if int(table["state_version"]) != int(expected_version):
        raise HTTPException(status_code=409, detail="Стол обновился, повторите ход")
    hand = await _current_hand(conn, table)
    if not hand or str(hand["status"]) != "running":
        raise HTTPException(status_code=409, detail="Сейчас нет руки")
    state = await _apply_due_timeout(conn, table=table, hand=hand, config=cfg)
    table = await _lock_table(conn, table_id)
    hand = await _current_hand(conn, table)
    if not hand or str(hand["status"]) != "running":
        snap = await snapshot(conn, table_id=table_id, viewer_id=user_id, config=cfg)
        publish_table(table_id, int(snap["state_version"]))
        return snap
    state = HandState.from_dict(hand["game_state"])
    seats = await _seats(conn, int(table["id"]))
    mine = next((row for row in seats if int(row["user_id"]) == user_id), None)
    if not mine:
        raise HTTPException(status_code=403, detail="Вы не за столом")
    try:
        apply_action(state, int(mine["seat_no"]), action, amount_rub)
    except HoldemError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _persist_hand(conn, table=table, hand=hand, state=state, config=cfg)
    if state.street == "complete":
        await _finish_hand(conn, table_id=table_id, config=cfg)
    snap = await snapshot(conn, table_id=table_id, viewer_id=user_id, config=cfg)
    publish_table(table_id, int(snap["state_version"]))
    return snap


def _seat_payload(row: Mapping[str, Any], *, viewer_id: int | None) -> dict[str, Any]:
    user_id = int(row["user_id"])
    return {
        "seat_no": int(row["seat_no"]),
        "occupied": True,
        "is_you": viewer_id is not None and user_id == viewer_id,
        "stack_rub": float(money(row["stack_rub"])),
        "status": str(row["status"]),
        "label": "Вы" if viewer_id is not None and user_id == viewer_id else f"Место {int(row['seat_no'])}",
    }


async def snapshot(
    conn,
    *,
    table_id: str,
    viewer_id: int | None,
    config: HoldemConfig | None = None,
) -> dict[str, Any]:
    cfg = config or await load_holdem_config(conn)
    table = await conn.fetchrow("SELECT * FROM casino_poker_tables WHERE table_id = $1", table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Стол не найден")
    table = dict(table)
    seated_alive = await conn.fetchval(
        """
        SELECT COUNT(*) FROM casino_poker_seats
        WHERE table_pk = $1 AND status = 'sitting' AND stack_rub > 0
        """,
        int(table["id"]),
    )
    if not table.get("current_hand_id") and int(seated_alive or 0) >= MIN_SEATS and str(table["status"]) != "closed":
        await _maybe_start_hand(conn, table_id=table_id, config=cfg)
        table = dict(await conn.fetchrow("SELECT * FROM casino_poker_tables WHERE table_id = $1", table_id))
    if table.get("current_hand_id"):
        hand_row = await conn.fetchrow("SELECT * FROM casino_poker_hands WHERE id = $1", int(table["current_hand_id"]))
        if hand_row and str(hand_row["status"]) == "running":
            due = hand_row.get("action_deadline_at")
            if due:
                now = datetime.now(timezone.utc)
                stamp = due if getattr(due, "tzinfo", None) else due.replace(tzinfo=timezone.utc)
                if stamp <= now:
                    locked = await _lock_table(conn, table_id)
                    hand = await _current_hand(conn, locked)
                    if hand:
                        await _apply_due_timeout(conn, table=locked, hand=hand, config=cfg)
                    table = dict(await conn.fetchrow("SELECT * FROM casino_poker_tables WHERE table_id = $1", table_id))
    seats = await _seats(conn, int(table["id"]))
    by_no = {int(row["seat_no"]): row for row in seats}
    viewer_seat = next((int(row["seat_no"]) for row in seats if viewer_id is not None and int(row["user_id"]) == viewer_id), None)
    max_seats = int(table["max_seats"])
    seat_views = []
    for num in range(1, max_seats + 1):
        if num in by_no:
            seat_views.append(_seat_payload(by_no[num], viewer_id=viewer_id))
        else:
            seat_views.append({"seat_no": num, "occupied": False, "is_you": False, "stack_rub": 0, "status": "empty", "label": "свободно"})
    hand_view = None
    fairness = None
    hand_row = None
    if table.get("current_hand_id"):
        hand_row = await conn.fetchrow("SELECT * FROM casino_poker_hands WHERE id = $1", int(table["current_hand_id"]))
    elif seats:
        hand_row = await conn.fetchrow(
            """
            SELECT * FROM casino_poker_hands
            WHERE table_pk = $1 AND status = 'complete'
            ORDER BY hand_no DESC LIMIT 1
            """,
            int(table["id"]),
        )
    if hand_row:
        state = HandState.from_dict(hand_row["game_state"])
        hand_view = public_view(state, viewer_seat)
        revealed = hand_seed_public(state.cards_shown, hand_row.get("seed_revealed_at"))
        fairness = {
            "game_type": GAME_TYPE,
            "hand_id": str(hand_row["hand_key"]),
            "commit": str(hand_row["commit_hash"]),
            "client_seed": str(hand_row["client_seed"]),
            "nonce": int(hand_row["nonce"]),
            "algorithm": "HMAC-SHA256-fisher-yates-v2",
            "server_seed": str(hand_row["server_seed"]) if revealed else None,
            "board": list(state.board_full) if revealed else None,
        }
        deadline = hand_row.get("action_deadline_at")
        if deadline and hand_view:
            stamp = deadline if getattr(deadline, "tzinfo", None) else deadline.replace(tzinfo=timezone.utc)
            hand_view["action_deadline_at"] = stamp.isoformat()
    return {
        "success": True,
        "table_id": str(table["table_id"]),
        "status": str(table["status"]),
        "max_seats": max_seats,
        "small_blind_rub": float(money(table["small_blind_rub"])),
        "big_blind_rub": float(money(table["big_blind_rub"])),
        "min_buyin_rub": float(cfg.min_buyin),
        "max_buyin_rub": float(cfg.max_buyin),
        "rake_percent": float(cfg.rake_percent),
        "rake_cap_rub": float(cfg.rake_cap),
        "timeout_seconds": cfg.timeout_seconds,
        "button_seat": table.get("button_seat"),
        "escrow_rub": float(money(table["escrow_rub"])),
        "state_version": int(table["state_version"]),
        "seats": seat_views,
        "you_seat": viewer_seat,
        "hand": hand_view,
        "fairness": fairness,
        "legal": hand_view["legal"] if hand_view and viewer_seat is not None else {"actions": []},
    }


async def list_open_tables(conn, *, config: HoldemConfig | None = None) -> dict[str, Any]:
    cfg = config or await load_holdem_config(conn)
    rows = await conn.fetch(
        """
        SELECT t.table_id, t.max_seats, t.small_blind_rub, t.big_blind_rub, t.status, t.created_at,
               COUNT(s.id)::int AS seated
        FROM casino_poker_tables t
        LEFT JOIN casino_poker_seats s ON s.table_pk = t.id
        WHERE t.status IN ('open', 'running')
        GROUP BY t.id
        ORDER BY t.created_at DESC
        LIMIT 50
        """
    )
    tables = []
    for row in rows:
        tables.append(
            {
                "table_id": str(row["table_id"]),
                "max_seats": int(row["max_seats"]),
                "seated": int(row["seated"]),
                "small_blind_rub": float(money(row["small_blind_rub"])),
                "big_blind_rub": float(money(row["big_blind_rub"])),
                "min_buyin_rub": float(cfg.min_buyin),
                "max_buyin_rub": float(cfg.max_buyin),
                "status": str(row["status"]),
                "opened_at": row["created_at"].isoformat() if row["created_at"] else "",
            }
        )
    return {
        "enabled": cfg.enabled,
        "small_blind_rub": float(cfg.small_blind),
        "big_blind_rub": float(cfg.big_blind),
        "min_buyin_rub": float(cfg.min_buyin),
        "max_buyin_rub": float(cfg.max_buyin),
        "rake_percent": float(cfg.rake_percent),
        "timeout_seconds": cfg.timeout_seconds,
        "tables": tables,
    }
