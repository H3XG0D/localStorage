"""Стол длинных нард: двое, холд на марс, рейк с проигранной ставки.

Деньги как у холдема: сел — сразу confirm, встал или партия кончилась — кредит.
Куба нет. Сдача и таймаут — ойн, не марс.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping

from fastapi import HTTPException

from casino_finance import casino_operation_ref, confirm_unified_hold, money, reserve_unified_funds
from casino_nardy import (
    BLACK,
    NardyError,
    WHITE,
    Match,
    commit_of,
    format_move,
    index_of_point,
    initial_position,
    settlement,
)

MIN_STAKE = Decimal("100")
MAX_STAKE = Decimal("50000")
RAKE_PERCENT = Decimal("5")
RAKE_CAP = Decimal("500")
TURN_SECONDS = 45
CLIENT_SEED = "focuspay-nardy"


def _loads(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _lock_amount(stake: Decimal) -> Decimal:
    return money(stake * 2)


def _check_stake(stake_rub: Decimal) -> Decimal:
    stake = money(stake_rub)
    if stake != stake.to_integral_value() or stake < MIN_STAKE or stake > MAX_STAKE:
        raise HTTPException(status_code=400, detail=f"Ставка {MIN_STAKE:.0f}–{MAX_STAKE:.0f} ₽, целыми рублями")
    return stake


async def _credit(conn, *, user_id: int, table_id: str, amount: Decimal, note: str, suffix: str) -> None:
    payout = money(amount)
    if payout <= 0:
        return
    order_id = casino_operation_ref("nardy-pay", table_id, f"{user_id}:{suffix}")
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
        raise HTTPException(status_code=409, detail="Выплата за нарды не сошлась")


async def _take_lock(conn, *, user_id: int, table_id: str, amount: Decimal) -> None:
    order_ref = casino_operation_ref("nardy-lock", table_id, str(user_id))
    try:
        await reserve_unified_funds(conn, user_id=user_id, order_ref=order_ref, amount_rub=amount)
        await confirm_unified_hold(
            conn,
            user_id=user_id,
            order_ref=order_ref,
            amount_rub=amount,
            note=f"Нарды {table_id}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Недостаточно средств") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="Не удалось списать ставку") from exc


async def _lock_table(conn, table_id: str) -> dict[str, Any]:
    row = await conn.fetchrow(
        "SELECT * FROM casino_nardy_tables WHERE table_id = $1 FOR UPDATE",
        table_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Стол не найден")
    return dict(row)


async def _busy_elsewhere(conn, user_id: int, except_id: str | None = None) -> None:
    other = await conn.fetchval(
        """
        SELECT table_id FROM casino_nardy_tables
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


def _match_of(table: Mapping[str, Any]) -> Match | None:
    if str(table["status"]) not in {"running", "done"}:
        return None
    raw = _loads(table.get("game_state"))
    if not raw:
        return None
    return Match.from_dict(
        raw,
        seed=str(table["server_seed"]),
        table_id=str(table["table_id"]),
        client_seed=str(table["client_seed"]),
    )


def _deadline() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=TURN_SECONDS)


async def _save_match(conn, table: dict[str, Any], match: Match, *, status: str, escrow: Decimal, rake_add: Decimal = Decimal("0")) -> None:
    revealed = match.phase == "done"
    await conn.execute(
        """
        UPDATE casino_nardy_tables
        SET status = $2,
            game_state = $3::jsonb,
            escrow_rub = $4,
            house_rake_rub = house_rake_rub + $5,
            state_version = state_version + 1,
            action_deadline_at = $6,
            seed_revealed_at = CASE WHEN $7 THEN now() ELSE seed_revealed_at END,
            updated_at = now()
        WHERE id = $1
        """,
        int(table["id"]),
        status,
        json.dumps(match.to_dict(), ensure_ascii=False),
        money(escrow),
        money(rake_add),
        _deadline() if status == "running" else None,
        revealed,
    )


async def _settle(conn, table: dict[str, Any], match: Match) -> None:
    if match.result is None:
        raise HTTPException(status_code=409, detail="Партия ещё идёт")
    winner_side = int(match.result["winner"])
    kind = str(match.result["kind"])
    if kind not in {"oin", "mars"}:
        raise HTTPException(status_code=409, detail="Неизвестный итог")
    pay = settlement(money(table["stake_rub"]), kind, RAKE_PERCENT, RAKE_CAP)
    escrow = money(table["escrow_rub"])
    if escrow != money(pay["winner"] + pay["loser"] + pay["rake"]):
        raise HTTPException(status_code=409, detail="Банк стола не сходится с выплатой")
    users = {WHITE: int(table["white_user_id"]), BLACK: int(table["black_user_id"])}
    winner_id = users[winner_side]
    loser_id = users[BLACK if winner_side == WHITE else WHITE]
    table_id = str(table["table_id"])
    await _credit(conn, user_id=winner_id, table_id=table_id, amount=pay["winner"], note=f"Нарды выигрыш {table_id}", suffix="settle-win")
    await _credit(conn, user_id=loser_id, table_id=table_id, amount=pay["loser"], note=f"Нарды возврат {table_id}", suffix="settle-back")
    await _save_match(conn, table, match, status="done", escrow=Decimal("0"), rake_add=pay["rake"])


async def _apply_timeout(conn, table: dict[str, Any]) -> dict[str, Any]:
    if str(table["status"]) != "running":
        return table
    due = table.get("action_deadline_at")
    if not due:
        return table
    stamp = due if getattr(due, "tzinfo", None) else due.replace(tzinfo=timezone.utc)
    if stamp > datetime.now(timezone.utc):
        return table
    match = _match_of(table)
    if match is None or match.phase != "move":
        return table
    match.resign(match.turn)
    await _settle(conn, table, match)
    fresh = await _lock_table(conn, str(table["table_id"]))
    return fresh


def _view(table: Mapping[str, Any], viewer_id: int | None) -> dict[str, Any]:
    stake = money(table["stake_rub"])
    white_id = table.get("white_user_id")
    black_id = table.get("black_user_id")
    your = None
    if viewer_id is not None and white_id is not None and int(white_id) == int(viewer_id):
        your = "white"
    elif viewer_id is not None and black_id is not None and int(black_id) == int(viewer_id):
        your = "black"
    revealed = table.get("seed_revealed_at") is not None or str(table["status"]) == "done"
    payload: dict[str, Any] = {
        "table_id": str(table["table_id"]),
        "status": str(table["status"]),
        "stake_rub": float(stake),
        "lock_rub": float(_lock_amount(stake)),
        "rake_percent": float(RAKE_PERCENT),
        "state_version": int(table["state_version"]),
        "your_side": your,
        "white_seated": white_id is not None,
        "black_seated": black_id is not None,
        "commit": str(table["commit_hash"]),
        "client_seed": str(table["client_seed"]),
        "server_seed": str(table["server_seed"]) if revealed else None,
        "turn": None,
        "dice": None,
        "start_white": None,
        "start_black": None,
        "legal": [],
        "points": [],
        "white_off": 0,
        "black_off": 0,
        "result": None,
        "deadline_at": None,
    }
    due = table.get("action_deadline_at")
    if due is not None and str(table["status"]) == "running":
        stamp = due if getattr(due, "tzinfo", None) else due.replace(tzinfo=timezone.utc)
        payload["deadline_at"] = stamp.isoformat()
    match = _match_of(table)
    pos = match.pos if match is not None else initial_position()
    payload["white_off"] = pos.white_off
    payload["black_off"] = pos.black_off
    payload["points"] = [
        {
            "point": point,
            "white": int(pos.white[index_of_point(point)]),
            "black": int(pos.black[index_of_point(point)]),
        }
        for point in range(1, 25)
    ]
    if match is None:
        return payload
    payload["turn"] = "white" if match.turn == WHITE else "black"
    payload["dice"] = list(match.dice) if match.dice else None
    payload["start_white"] = match.start_white or None
    payload["start_black"] = match.start_black or None
    if match.phase == "move" and your is not None and ((your == "white") == (match.turn == WHITE)):
        payload["legal"] = [{"index": index, "label": format_move(move)} for index, move in enumerate(match.moves())]
    if match.result:
        winner = int(match.result["winner"])
        payload["result"] = {
            "winner": "white" if winner == WHITE else "black",
            "kind": str(match.result["kind"]),
            "you_won": your is not None and ((your == "white") == (winner == WHITE)),
        }
        payload["turn"] = None
    return payload


async def create_table(conn, *, creator_id: int, stake_rub: Decimal) -> dict[str, Any]:
    stake = _check_stake(stake_rub)
    await _busy_elsewhere(conn, creator_id)
    table_id = "n" + secrets.token_hex(8)
    seed = secrets.token_hex(32)
    lock = _lock_amount(stake)
    await _take_lock(conn, user_id=creator_id, table_id=table_id, amount=lock)
    await conn.execute(
        """
        INSERT INTO casino_nardy_tables (
            table_id, creator_id, white_user_id, stake_rub, status, escrow_rub,
            server_seed, client_seed, commit_hash
        ) VALUES ($1, $2, $2, $3, 'waiting', $4, $5, $6, $7)
        """,
        table_id,
        creator_id,
        stake,
        lock,
        seed,
        CLIENT_SEED,
        commit_of(seed, table_id),
    )
    table = await _lock_table(conn, table_id)
    return _view(table, creator_id)


async def join_table(conn, *, table_id: str, user_id: int) -> dict[str, Any]:
    table = await _lock_table(conn, table_id)
    table = await _apply_timeout(conn, table)
    if str(table["status"]) != "waiting":
        raise HTTPException(status_code=409, detail="За стол уже не сесть")
    if int(table["white_user_id"]) == user_id:
        raise HTTPException(status_code=409, detail="Вы уже за белых")
    await _busy_elsewhere(conn, user_id, except_id=table_id)
    stake = money(table["stake_rub"])
    lock = _lock_amount(stake)
    await _take_lock(conn, user_id=user_id, table_id=table_id, amount=lock)
    match = Match.start(seed=str(table["server_seed"]), table_id=table_id, client_seed=CLIENT_SEED)
    escrow = money(table["escrow_rub"]) + lock
    await conn.execute(
        """
        UPDATE casino_nardy_tables
        SET black_user_id = $2, status = 'running', escrow_rub = $3, updated_at = now()
        WHERE id = $1
        """,
        int(table["id"]),
        user_id,
        escrow,
    )
    table["black_user_id"] = user_id
    table["status"] = "running"
    table["escrow_rub"] = escrow
    await _save_match(conn, table, match, status="running", escrow=escrow)
    fresh = await _lock_table(conn, table_id)
    return _view(fresh, user_id)


async def leave_table(conn, *, table_id: str, user_id: int) -> dict[str, Any]:
    table = await _lock_table(conn, table_id)
    table = await _apply_timeout(conn, table)
    status = str(table["status"])
    white_id = int(table["white_user_id"]) if table.get("white_user_id") is not None else None
    black_id = int(table["black_user_id"]) if table.get("black_user_id") is not None else None
    if user_id not in {white_id, black_id}:
        raise HTTPException(status_code=409, detail="Вы не за этим столом")
    if status == "waiting" and user_id == white_id:
        await _credit(
            conn,
            user_id=user_id,
            table_id=table_id,
            amount=money(table["escrow_rub"]),
            note=f"Нарды отмена {table_id}",
            suffix="cancel",
        )
        await conn.execute(
            """
            UPDATE casino_nardy_tables
            SET status = 'closed', escrow_rub = 0, state_version = state_version + 1,
                white_user_id = NULL, updated_at = now()
            WHERE id = $1
            """,
            int(table["id"]),
        )
        fresh = await _lock_table(conn, table_id)
        return _view(fresh, None)
    if status != "running":
        raise HTTPException(status_code=409, detail="Партия уже закрыта")
    match = _match_of(table)
    if match is None:
        raise HTTPException(status_code=409, detail="Партия не началась")
    side = WHITE if user_id == white_id else BLACK
    match.resign(side)
    await _settle(conn, table, match)
    fresh = await _lock_table(conn, table_id)
    return _view(fresh, user_id)


async def act(conn, *, table_id: str, user_id: int, move_index: int, expected_version: int) -> dict[str, Any]:
    table = await _lock_table(conn, table_id)
    table = await _apply_timeout(conn, table)
    if int(table["state_version"]) != int(expected_version):
        raise HTTPException(status_code=409, detail="Стол обновился, повторите ход")
    if str(table["status"]) != "running":
        raise HTTPException(status_code=409, detail="Партия уже не идёт")
    match = _match_of(table)
    if match is None or match.phase != "move":
        raise HTTPException(status_code=409, detail="Сейчас не ваш ход")
    white_id = int(table["white_user_id"])
    black_id = int(table["black_user_id"])
    side = WHITE if user_id == white_id else BLACK if user_id == black_id else None
    if side is None:
        raise HTTPException(status_code=403, detail="Вы не за этим столом")
    if side != match.turn:
        raise HTTPException(status_code=409, detail="Сейчас ход соперника")
    try:
        match.play(int(move_index))
    except NardyError as exc:
        raise HTTPException(status_code=400, detail="Такого хода нет") from exc
    if match.phase == "done":
        await _settle(conn, table, match)
    else:
        await _save_match(conn, table, match, status="running", escrow=money(table["escrow_rub"]))
    fresh = await _lock_table(conn, table_id)
    return _view(fresh, user_id)


async def snapshot(conn, *, table_id: str, viewer_id: int | None) -> dict[str, Any]:
    table = await _lock_table(conn, table_id)
    table = await _apply_timeout(conn, table)
    return _view(table, viewer_id)


async def list_open_tables(conn) -> dict[str, Any]:
    rows = await conn.fetch(
        """
        SELECT table_id, stake_rub, status, white_user_id, black_user_id, created_at
        FROM casino_nardy_tables
        WHERE status IN ('waiting', 'running')
        ORDER BY created_at DESC
        LIMIT 30
        """
    )
    return {
        "enabled": True,
        "min_stake_rub": float(MIN_STAKE),
        "max_stake_rub": float(MAX_STAKE),
        "rake_percent": float(RAKE_PERCENT),
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
