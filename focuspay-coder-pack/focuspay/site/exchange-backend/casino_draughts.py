"""Стол русских шашек: двое, одна ставка, рейк холдема с банка.

Холд как бай-ин покера: сел — reserve и сразу confirm. Ничья возвращает обе ставки.
Победа, сдача и таймаут хода отдают банк минус rake_amount холдема. Бота нет.
Легальность хода решает только casino_draughts_rules.
"""
from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping

from fastapi import HTTPException

from casino_draughts_rules import (
    BLACK,
    WHITE,
    DraughtsRulesError,
    MatchState,
    assess,
    push_notation,
)
from casino_finance import (
    casino_operation_ref,
    confirm_unified_hold,
    credit_house_game_settlement,
    game_stake_bounds,
    load_casino_settings,
    money,
    reserve_unified_funds,
)
from casino_holdem import rake_amount
from casino_settings_registry import REGISTRY

GAME_TYPE = "russian_draughts"
ALLOWS_BOT = False
# ledger.order_id is VARCHAR(64). confirm_unified_hold always binds
# spend-{ref}:partner, so this kind has to stay short. "draughts-lock" is 67.
LOCK_REF_KIND = "drft-lock"
_subscribers: dict[str, set[asyncio.Queue]] = {}


@dataclass(frozen=True)
class DraughtsConfig:
    enabled: bool
    min_stake: Decimal
    max_stake: Decimal
    rake_percent: Decimal
    rake_cap: Decimal
    timeout_seconds: int


def _setting_amount(values: Mapping[str, object], key: str) -> Decimal:
    raw = values.get(key)
    if isinstance(raw, Mapping) and raw.get("amount") is not None:
        return money(raw["amount"])
    spec = REGISTRY.get(key)
    if spec is not None:
        return money(spec.default)  # type: ignore[arg-type]
    return money(0)


def _setting_percent(values: Mapping[str, object], key: str) -> Decimal:
    raw = values.get(key)
    if isinstance(raw, Mapping) and raw.get("percent") is not None:
        return money(raw["percent"])
    spec = REGISTRY.get(key)
    if spec is not None:
        return money(spec.default)  # type: ignore[arg-type]
    return money(0)


def _setting_int(values: Mapping[str, object], key: str) -> int:
    raw = values.get(key)
    if isinstance(raw, Mapping) and raw.get("value") is not None:
        return int(raw["value"])
    spec = REGISTRY.get(key)
    if spec is not None:
        return int(spec.default)  # type: ignore[arg-type]
    return 0


def config_from_rows(rows: Mapping[str, object], settings) -> DraughtsConfig:
    lo, hi = game_stake_bounds(settings, GAME_TYPE)
    if lo > hi:
        lo, hi = settings.min_bet_rub, settings.max_bet_rub
    timeout = _setting_int(rows, "draughts_move_timeout_seconds")
    return DraughtsConfig(
        enabled=bool(settings.enabled_games.get(GAME_TYPE, False)),
        min_stake=money(lo),
        max_stake=money(hi),
        rake_percent=_setting_percent(rows, "holdem_rake_percent"),
        rake_cap=_setting_amount(rows, "holdem_rake_cap_rub"),
        timeout_seconds=max(5, min(300, timeout or 30)),
    )


async def load_config(conn) -> DraughtsConfig:
    settings = await load_casino_settings(conn)
    rows = {str(row["key"]): row["value"] for row in await conn.fetch("SELECT key, value FROM casino_settings")}
    return config_from_rows(rows, settings)


def settlement(stake: Decimal, outcome: str, rake_percent: Decimal, rake_cap: Decimal) -> dict[str, Decimal]:
    """draw возвращает обе ставки. white/black — победитель получает банк минус рейк холдема."""
    posted = money(stake)
    if outcome == "draw":
        return {"rake": money(0), "white": posted, "black": posted}
    if outcome not in {WHITE, BLACK}:
        raise DraughtsRulesError("Неизвестный итог")
    pot = money(posted * 2)
    rake = rake_amount(pot, rake_percent, rake_cap)
    payout = money(pot - rake)
    if outcome == WHITE:
        return {"rake": rake, "white": payout, "black": money(0)}
    return {"rake": rake, "white": money(0), "black": payout}


def timeout_winner(side_to_move: str) -> str:
    """Просрочка — сдача ставки, не случайный ход."""
    if side_to_move == WHITE:
        return BLACK
    if side_to_move == BLACK:
        return WHITE
    raise DraughtsRulesError("Некого штрафовать")


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


def _loads(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, str) and raw.strip():
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return []


def _state_of(table: Mapping[str, Any]) -> MatchState:
    return assess(_loads(table.get("moves")))


async def _credit(conn, *, user_id: int, table_id: str, amount: Decimal, note: str, suffix: str) -> None:
    payout = money(amount)
    if payout <= 0:
        return
    order_id = casino_operation_ref("draughts-pay", table_id, f"{user_id}:{suffix}")
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
        raise HTTPException(status_code=409, detail="Выплата за шашки не сошлась")


async def _take_stake(conn, *, user_id: int, table_id: str, amount: Decimal) -> None:
    order_ref = casino_operation_ref(LOCK_REF_KIND, table_id, str(user_id))
    try:
        await reserve_unified_funds(conn, user_id=user_id, order_ref=order_ref, amount_rub=amount)
        await confirm_unified_hold(
            conn,
            user_id=user_id,
            order_ref=order_ref,
            amount_rub=amount,
            note=f"Шашки {table_id}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Недостаточно средств") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="Не удалось списать ставку") from exc


async def _lock_table(conn, table_id: str) -> dict[str, Any]:
    row = await conn.fetchrow(
        "SELECT * FROM casino_draughts_tables WHERE table_id = $1 FOR UPDATE",
        table_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Стол не найден")
    return dict(row)


async def _busy_elsewhere(conn, user_id: int, except_id: str | None = None) -> None:
    other = await conn.fetchval(
        """
        SELECT table_id FROM casino_draughts_tables
        WHERE status IN ('waiting', 'running')
          AND (white_user_id = $1 OR black_user_id = $1)
          AND ($2::text IS NULL OR table_id <> $2)
        LIMIT 1
        """,
        user_id,
        except_id,
    )
    if other:
        raise HTTPException(status_code=409, detail="Сначала закончите другую партию")


def _deadline(seconds: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _side_of(table: Mapping[str, Any], user_id: int) -> str | None:
    white_id = table.get("white_user_id")
    black_id = table.get("black_user_id")
    if white_id is not None and int(white_id) == int(user_id):
        return WHITE
    if black_id is not None and int(black_id) == int(user_id):
        return BLACK
    return None


def _user_of(table: Mapping[str, Any], side: str) -> int:
    if side == WHITE:
        return int(table["white_user_id"])
    return int(table["black_user_id"])


async def _pay(conn, table: Mapping[str, Any], outcome: str, reason: str, config: DraughtsConfig) -> None:
    stake = money(table["stake_rub"])
    pay = settlement(stake, outcome, config.rake_percent, config.rake_cap)
    escrow = money(table["escrow_rub"])
    if escrow != money(pay["white"] + pay["black"] + pay["rake"]):
        raise HTTPException(status_code=409, detail="Банк стола не сходится с выплатой")
    table_id = str(table["table_id"])
    await _credit(
        conn,
        user_id=_user_of(table, WHITE),
        table_id=table_id,
        amount=pay["white"],
        note=f"Шашки {table_id}",
        suffix=f"settle-{outcome}-w",
    )
    await _credit(
        conn,
        user_id=_user_of(table, BLACK),
        table_id=table_id,
        amount=pay["black"],
        note=f"Шашки {table_id}",
        suffix=f"settle-{outcome}-b",
    )
    if pay["rake"] > 0:
        await credit_house_game_settlement(
            conn,
            amount_rub=pay["rake"],
            entry_key=f"draughts-rake:{table_id}",
            reason=f"Шашки рейк {table_id}",
        )
    await conn.execute(
        """
        UPDATE casino_draughts_tables
        SET status = 'done',
            escrow_rub = 0,
            house_rake_rub = house_rake_rub + $2,
            rake_rub = $2,
            result = $3,
            result_reason = $4,
            draw_offer_user_id = NULL,
            action_deadline_at = NULL,
            state_version = state_version + 1,
            updated_at = now()
        WHERE id = $1
        """,
        int(table["id"]),
        pay["rake"],
        outcome,
        reason,
    )


async def _save_running(conn, table: Mapping[str, Any], moves: list[str], *, offer: int | None, config: DraughtsConfig) -> None:
    await conn.execute(
        """
        UPDATE casino_draughts_tables
        SET moves = $2::jsonb,
            draw_offer_user_id = $3,
            action_deadline_at = $4,
            state_version = state_version + 1,
            updated_at = now()
        WHERE id = $1 AND status = 'running'
        """,
        int(table["id"]),
        json.dumps(moves, ensure_ascii=False),
        offer,
        _deadline(config.timeout_seconds),
    )


async def _apply_timeout(conn, table: dict[str, Any], config: DraughtsConfig) -> dict[str, Any]:
    if str(table["status"]) != "running":
        return table
    due = table.get("action_deadline_at")
    if not due:
        return table
    stamp = due if getattr(due, "tzinfo", None) else due.replace(tzinfo=timezone.utc)
    if stamp > datetime.now(timezone.utc):
        return table
    state = _state_of(table)
    if state.status != "ongoing":
        return table
    await _pay(conn, table, timeout_winner(state.turn), "timeout", config)
    return await _lock_table(conn, str(table["table_id"]))


def _view(table: Mapping[str, Any], viewer_id: int | None, config: DraughtsConfig) -> dict[str, Any]:
    stake = money(table["stake_rub"])
    your = _side_of(table, viewer_id) if viewer_id is not None else None
    status = str(table["status"])
    state = _state_of(table) if status in {"running", "done"} else assess([])
    show_moves = status == "running" and your is not None and your == state.turn and state.status == "ongoing"
    due = table.get("action_deadline_at")
    deadline = None
    if due is not None and status == "running":
        stamp = due if getattr(due, "tzinfo", None) else due.replace(tzinfo=timezone.utc)
        deadline = stamp.isoformat()
    offer = table.get("draw_offer_user_id")
    result = table.get("result")
    your_payout = None
    if status == "done" and your in {WHITE, BLACK} and result:
        pay = settlement(stake, str(result), config.rake_percent, config.rake_cap)
        your_payout = float(pay[your])
    return {
        "table_id": str(table["table_id"]),
        "status": status,
        "enabled": config.enabled,
        "stake_rub": float(stake),
        "min_stake_rub": float(config.min_stake),
        "max_stake_rub": float(config.max_stake),
        "rake_percent": float(config.rake_percent),
        "rake_cap_rub": float(config.rake_cap),
        "rake_rub": float(money(table.get("rake_rub") or 0)),
        "state_version": int(table["state_version"]),
        "your_side": your,
        "your_turn": bool(show_moves),
        "turn": state.turn if status == "running" and state.status == "ongoing" else None,
        "white_seated": table.get("white_user_id") is not None,
        "black_seated": table.get("black_user_id") is not None,
        "pieces": [piece.as_dict() for piece in state.pieces] if status in {"running", "done"} else [piece.as_dict() for piece in assess([]).pieces],
        "legal_moves": [move.as_dict() for move in state.legal] if show_moves else [],
        "moves": list(state.moves) if status in {"running", "done"} else [],
        "can_offer_draw": bool(
            status == "running" and your is not None and state.status == "ongoing" and state.can_offer_draw
        ),
        "draw_offer": offer is not None and your is not None and int(offer) != int(viewer_id or 0),
        "result": str(result) if result else None,
        "reason": str(table.get("result_reason") or state.reason or ""),
        "your_payout_rub": your_payout,
        "deadline_at": deadline,
        "timeout_seconds": config.timeout_seconds,
    }


async def create_table(conn, *, creator_id: int, stake_rub: Decimal, config: DraughtsConfig | None = None) -> dict[str, Any]:
    cfg = config or await load_config(conn)
    if not cfg.enabled:
        raise HTTPException(status_code=409, detail="Шашки выключены")
    stake = money(stake_rub)
    if stake < cfg.min_stake or stake > cfg.max_stake:
        raise HTTPException(status_code=400, detail=f"Ставка {cfg.min_stake}–{cfg.max_stake} ₽")
    await _busy_elsewhere(conn, creator_id)
    table_id = "d" + secrets.token_hex(8)
    await _take_stake(conn, user_id=creator_id, table_id=table_id, amount=stake)
    await conn.execute(
        """
        INSERT INTO casino_draughts_tables (
            table_id, creator_id, white_user_id, stake_rub, status, escrow_rub
        ) VALUES ($1, $2, $2, $3, 'waiting', $3)
        """,
        table_id,
        creator_id,
        stake,
    )
    table = await _lock_table(conn, table_id)
    snap = _view(table, creator_id, cfg)
    publish_table(table_id, int(snap["state_version"]))
    return snap


async def join_table(conn, *, table_id: str, user_id: int, config: DraughtsConfig | None = None) -> dict[str, Any]:
    cfg = config or await load_config(conn)
    if not cfg.enabled:
        raise HTTPException(status_code=409, detail="Шашки выключены")
    table = await _lock_table(conn, table_id)
    if str(table["status"]) != "waiting":
        raise HTTPException(status_code=409, detail="За стол уже не сесть")
    if int(table["white_user_id"]) == user_id:
        raise HTTPException(status_code=409, detail="Вы уже за белых")
    await _busy_elsewhere(conn, user_id, except_id=table_id)
    stake = money(table["stake_rub"])
    await _take_stake(conn, user_id=user_id, table_id=table_id, amount=stake)
    escrow = money(table["escrow_rub"]) + stake
    await conn.execute(
        """
        UPDATE casino_draughts_tables
        SET black_user_id = $2,
            status = 'running',
            escrow_rub = $3,
            moves = '[]'::jsonb,
            action_deadline_at = $4,
            state_version = state_version + 1,
            updated_at = now()
        WHERE id = $1
        """,
        int(table["id"]),
        user_id,
        escrow,
        _deadline(cfg.timeout_seconds),
    )
    fresh = await _lock_table(conn, table_id)
    snap = _view(fresh, user_id, cfg)
    publish_table(table_id, int(snap["state_version"]))
    return snap


async def leave_table(conn, *, table_id: str, user_id: int, config: DraughtsConfig | None = None) -> dict[str, Any]:
    cfg = config or await load_config(conn)
    table = await _lock_table(conn, table_id)
    table = await _apply_timeout(conn, table, cfg)
    side = _side_of(table, user_id)
    if side is None:
        raise HTTPException(status_code=409, detail="Вы не за этим столом")
    status = str(table["status"])
    if status == "waiting" and side == WHITE:
        await _credit(
            conn,
            user_id=user_id,
            table_id=table_id,
            amount=money(table["escrow_rub"]),
            note=f"Шашки отмена {table_id}",
            suffix="cancel",
        )
        await conn.execute(
            """
            UPDATE casino_draughts_tables
            SET status = 'closed', escrow_rub = 0, white_user_id = NULL,
                state_version = state_version + 1, updated_at = now()
            WHERE id = $1
            """,
            int(table["id"]),
        )
        fresh = await _lock_table(conn, table_id)
        snap = _view(fresh, None, cfg)
        publish_table(table_id, int(snap["state_version"]))
        return snap
    if status != "running":
        raise HTTPException(status_code=409, detail="Партия уже закрыта")
    await _pay(conn, table, _other(side), "resign", cfg)
    fresh = await _lock_table(conn, table_id)
    snap = _view(fresh, user_id, cfg)
    publish_table(table_id, int(snap["state_version"]))
    return snap


def _other(side: str) -> str:
    return BLACK if side == WHITE else WHITE


async def act(conn, *, table_id: str, user_id: int, notation: str, expected_version: int, config: DraughtsConfig | None = None) -> dict[str, Any]:
    cfg = config or await load_config(conn)
    table = await _lock_table(conn, table_id)
    table = await _apply_timeout(conn, table, cfg)
    if str(table["status"]) != "running":
        fresh = await _lock_table(conn, table_id)
        snap = _view(fresh, user_id, cfg)
        publish_table(table_id, int(snap["state_version"]))
        return snap
    if int(table["state_version"]) != int(expected_version):
        raise HTTPException(status_code=409, detail="Стол обновился, повторите ход")
    side = _side_of(table, user_id)
    if side is None:
        raise HTTPException(status_code=403, detail="Вы не за этим столом")
    state = _state_of(table)
    if state.turn != side:
        raise HTTPException(status_code=409, detail="Сейчас ход соперника")
    try:
        nxt = push_notation(list(state.moves), notation)
    except DraughtsRulesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if nxt.status == "ongoing":
        await _save_running(conn, table, list(nxt.moves), offer=table.get("draw_offer_user_id"), config=cfg)
    else:
        table = dict(table)
        table["moves"] = json.dumps(list(nxt.moves))
        await conn.execute(
            "UPDATE casino_draughts_tables SET moves = $2::jsonb WHERE id = $1",
            int(table["id"]),
            json.dumps(list(nxt.moves), ensure_ascii=False),
        )
        await _pay(conn, table, nxt.status, nxt.reason, cfg)
    fresh = await _lock_table(conn, table_id)
    snap = _view(fresh, user_id, cfg)
    publish_table(table_id, int(snap["state_version"]))
    return snap


async def offer_draw(conn, *, table_id: str, user_id: int, config: DraughtsConfig | None = None) -> dict[str, Any]:
    cfg = config or await load_config(conn)
    table = await _lock_table(conn, table_id)
    table = await _apply_timeout(conn, table, cfg)
    if str(table["status"]) != "running":
        raise HTTPException(status_code=409, detail="Партия уже не идёт")
    side = _side_of(table, user_id)
    if side is None:
        raise HTTPException(status_code=403, detail="Вы не за этим столом")
    state = _state_of(table)
    if not state.can_offer_draw:
        raise HTTPException(status_code=409, detail="Ничью можно предложить после 20 ходов каждого")
    await conn.execute(
        """
        UPDATE casino_draughts_tables
        SET draw_offer_user_id = $2, state_version = state_version + 1, updated_at = now()
        WHERE id = $1
        """,
        int(table["id"]),
        user_id,
    )
    fresh = await _lock_table(conn, table_id)
    snap = _view(fresh, user_id, cfg)
    publish_table(table_id, int(snap["state_version"]))
    return snap


async def answer_draw(conn, *, table_id: str, user_id: int, accept: bool, config: DraughtsConfig | None = None) -> dict[str, Any]:
    cfg = config or await load_config(conn)
    table = await _lock_table(conn, table_id)
    table = await _apply_timeout(conn, table, cfg)
    if str(table["status"]) != "running":
        fresh = await _lock_table(conn, table_id)
        return _view(fresh, user_id, cfg)
    offer = table.get("draw_offer_user_id")
    if offer is None or int(offer) == int(user_id) or _side_of(table, user_id) is None:
        raise HTTPException(status_code=409, detail="Вам не предлагали ничью")
    if accept:
        await _pay(conn, table, "draw", "6.1.8.1", cfg)
    else:
        await conn.execute(
            """
            UPDATE casino_draughts_tables
            SET draw_offer_user_id = NULL, state_version = state_version + 1, updated_at = now()
            WHERE id = $1
            """,
            int(table["id"]),
        )
    fresh = await _lock_table(conn, table_id)
    snap = _view(fresh, user_id, cfg)
    publish_table(table_id, int(snap["state_version"]))
    return snap


async def snapshot(conn, *, table_id: str, viewer_id: int | None, config: DraughtsConfig | None = None) -> dict[str, Any]:
    cfg = config or await load_config(conn)
    table = await _lock_table(conn, table_id)
    table = await _apply_timeout(conn, table, cfg)
    return _view(table, viewer_id, cfg)


async def list_open_tables(conn, config: DraughtsConfig | None = None) -> dict[str, Any]:
    cfg = config or await load_config(conn)
    rows = await conn.fetch(
        """
        SELECT table_id, stake_rub, status, white_user_id, black_user_id
        FROM casino_draughts_tables
        WHERE status IN ('waiting', 'running')
        ORDER BY created_at DESC
        LIMIT 30
        """
    )
    return {
        "enabled": cfg.enabled,
        "min_stake_rub": float(cfg.min_stake),
        "max_stake_rub": float(cfg.max_stake),
        "rake_percent": float(cfg.rake_percent),
        "rake_cap_rub": float(cfg.rake_cap),
        "timeout_seconds": cfg.timeout_seconds,
        "tables": [
            {
                "table_id": str(row["table_id"]),
                "stake_rub": float(money(row["stake_rub"])),
                "status": str(row["status"]),
                "seated": int(row["white_user_id"] is not None) + int(row["black_user_id"] is not None),
            }
            for row in rows
        ],
    }


async def sweep_due_timeouts() -> int:
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        cfg = await load_config(conn)
        rows = await conn.fetch(
            """
            SELECT table_id FROM casino_draughts_tables
            WHERE status = 'running'
              AND action_deadline_at IS NOT NULL
              AND action_deadline_at <= now()
            """
        )
    settled = 0
    for row in rows:
        table_id = str(row["table_id"])
        async with pool.acquire() as conn:
            async with conn.transaction():
                table = await _lock_table(conn, table_id)
                before = str(table["status"])
                table = await _apply_timeout(conn, table, cfg)
                if before == "running" and str(table["status"]) == "done":
                    settled += 1
                    publish_table(table_id, int(table["state_version"]))
    return settled


async def timeout_loop() -> None:
    await asyncio.sleep(15)
    while True:
        try:
            await sweep_due_timeouts()
        except Exception:
            import logging

            logging.getLogger(__name__).exception("draughts timeout sweep failed")
        await asyncio.sleep(5)
