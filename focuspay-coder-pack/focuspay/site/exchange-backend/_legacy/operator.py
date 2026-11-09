"""
Кабинет оператора: управление сменами, создание и подтверждение ручных заявок.
"""

import logging
import secrets
from datetime import datetime, timezone
from typing import Literal, Optional

import asyncpg
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field, field_validator, model_validator

import runtime_settings
from auth import get_current_operator, operator_public_dict
from commission import commission_percent
from config import settings
from db import get_pool
from operator_earnings import utc_aware
from payroll_base import order_completed_in_shift, order_in_shift, stats_from_orders_conn
from finance_access import strip_operator_profit_fields
from order_service import _validate_amounts
from routers.public import get_rates_cached
from user_cashback_db import (
    apply_cashback_with_conn,
    hold_cashback_for_order,
    should_use_cashback,
)

router = APIRouter()
logger = logging.getLogger("operator")

SUPPORTED_CRYPTOS = ("btc", "usdt", "trx", "ltc")

_ORDERS_WITH_BUYER_SQL = """
    SELECT o.*, bu.username AS buyer_username, bu.first_name AS buyer_first_name,
           oa.username AS operator_username, oa.display_name AS operator_display_name
    FROM orders o
    LEFT JOIN bot_users bu ON bu.user_id = o.user_id
    LEFT JOIN operator_accounts oa ON oa.id = o.operator_id
"""

_WITHDRAWALS_WITH_OPERATOR_SQL = """
    SELECT w.*, oa.username AS operator_username, oa.display_name AS operator_display_name
    FROM user_referral_withdrawals w
    LEFT JOIN operator_accounts oa ON oa.id = w.operator_id
"""

_STATUS_LABELS = {
    "CREATED": "Создана",
    "AWAITING_CHECK": "Ожидает чек",
    "PENDING": "На проверке",
    "COMPLETED": "Мерчант подтвердил оплату",
    "PAID": "Выплачена",
    "FAILED": "Ошибка",
    "CANCELED": "Отменена",
    "EXPIRED": "Истекла",
    "DISPUTE": "Спор",
    "OPERATOR_PENDING": "Ожидает оператора",
}

_SUB_TOKEN_LABELS = {
    "CARDRUB": "Карта",
    "SBPRUB": "СБП",
}


def _payment_summary(row: dict) -> dict | None:
    snap = row.get("payment_snapshot")
    if not snap:
        return None
    if isinstance(snap, str):
        import json

        try:
            snap = json.loads(snap)
        except (TypeError, ValueError):
            return None
    if not isinstance(snap, dict):
        return None
    bill = snap.get("bill") if isinstance(snap.get("bill"), dict) else {}
    merchant_uuid = (
        snap.get("merchant_uuid")
        or snap.get("uuid_system")
        or row.get("merchant_order_id")
    )
    parts: list[str] = []
    bank = bill.get("bank")
    reciver = bill.get("reciver") or bill.get("receiver")
    fio = bill.get("fio")
    if bank:
        parts.append(str(bank))
    if fio:
        parts.append(str(fio))
    if reciver:
        parts.append(str(reciver))
    return {
        "merchant_uuid": str(merchant_uuid) if merchant_uuid else None,
        "pay_link": snap.get("pay_link"),
        "summary": " · ".join(parts) if parts else None,
    }


def _origin_hint(row: dict) -> str | None:
    status = str(row.get("status") or "").upper()
    direction = str(row.get("direction") or "").lower()
    merchant_id = (row.get("merchant_order_id") or "").strip()

    if status == "OPERATOR_PENDING" and direction == "buy":
        if merchant_id:
            return "Создана оператором или переведена в ручную обработку"
        return "Автоматические реквизиты не выдались — ручная обработка"
    if status == "PENDING" and direction == "buy":
        return "Чек отправлен — ожидает проверки мерчантом"
    if status == "COMPLETED" and direction == "buy":
        return "Мерчант подтвердил оплату — отправьте крипту клиенту"
    if status == "PENDING" and direction == "sell":
        return "Клиент отметил отправку крипты — нужен отчёт по сделке"
    if status == "OPERATOR_PENDING" and direction == "sell":
        return "Продажа ожидает оператора"
    return None


def _assigned_operator_from_row(row: dict) -> dict | None:
    oid = row.get("operator_id")
    if oid is None:
        return None
    username = row.get("operator_username")
    display_name = row.get("operator_display_name")
    if username is None and display_name is None:
        return None
    return {
        "id": int(oid),
        "display_name": display_name or username,
        "username": username,
    }


def _order_out(row: dict, *, current_operator_id: int | None = None) -> dict:
    from bot_user_avatars import bot_user_avatar_public_url

    r = dict(row)
    for key in ("created_at", "updated_at", "expires_at"):
        val = r.get(key)
        if val and hasattr(val, "isoformat"):
            r[key] = val.isoformat()
    if r.get("buyer_username") and not str(r["buyer_username"]).startswith("@"):
        r["buyer_username"] = f"@{r['buyer_username']}"
    if r.get("user_id"):
        r["buyer_avatar_url"] = bot_user_avatar_public_url(int(r["user_id"]))

    status = str(r.get("status") or "")
    sub = str(r.get("sub_token") or "").upper()
    cb = float(r.get("cashback_applied_rub") or 0)
    disc = float(r.get("exchange_discount_applied_rub") or 0)
    balance_applied = round(cb + disc, 2)

    r["status_label"] = _STATUS_LABELS.get(status, status)
    r["sub_token_label"] = _SUB_TOKEN_LABELS.get(sub, sub or None)
    r["balance_applied_rub"] = balance_applied if balance_applied > 0 else 0.0
    r["origin_hint"] = _origin_hint(r)
    r["payment_summary"] = _payment_summary(r)
    r["has_receipt"] = bool(r.get("receipt_file"))
    if r.get("rate") is not None:
        r["rate"] = float(r["rate"])
    if r.get("cashback_applied_rub") is not None:
        r["cashback_applied_rub"] = float(r["cashback_applied_rub"])
    if r.get("exchange_discount_applied_rub") is not None:
        r["exchange_discount_applied_rub"] = float(r["exchange_discount_applied_rub"])
    r["assigned_operator"] = _assigned_operator_from_row(r)
    if current_operator_id is not None and r.get("operator_id") is not None:
        r["assigned_to_me"] = int(r["operator_id"]) == current_operator_id
    r.pop("operator_username", None)
    r.pop("operator_display_name", None)
    return r


def _withdrawal_out(row: dict, *, current_operator_id: int | None = None) -> dict:
    from user_referral_withdraw import withdrawal_out

    r = withdrawal_out(dict(row))
    r["assigned_operator"] = _assigned_operator_from_row(row)
    if current_operator_id is not None and row.get("operator_id") is not None:
        r["assigned_to_me"] = int(row["operator_id"]) == current_operator_id
    return r


async def _resolve_buyer_user_id(conn, buyer_user_id: int) -> dict:
    row = await conn.fetchrow(
        "SELECT user_id, username, first_name FROM bot_users WHERE user_id = $1",
        buyer_user_id,
    )
    if not row:
        raise HTTPException(
            status_code=400,
            detail="Клиент должен быть в боте — попросите написать /start",
        )
    return dict(row)


def _require_order_buyer(row) -> int:
    uid = row.get("user_id")
    if uid is None:
        raise HTTPException(status_code=400, detail="Не указан покупатель (Telegram)")
    return int(uid)


def _shift_out(row: dict) -> dict:
    r = dict(row)
    for key in ("started_at", "ended_at"):
        val = r.get(key)
        if val and hasattr(val, "isoformat"):
            r[key] = val.isoformat()
    r.pop("usdt_issued", None)
    return r


async def _shift_orders(conn, operator_id: int, started_at, ended_at) -> list[dict]:
    from payroll_base import fetch_shift_orders

    return await fetch_shift_orders(conn, operator_id, started_at, ended_at)


# BUY: в «Заявки» после чека (PENDING+) или ручная OPERATOR_PENDING
# SELL: сразу на оператора (OPERATOR_PENDING) или после «Я отправил» (PENDING)
BUY_INCOMING_STATUSES = ("PENDING", "COMPLETED", "OPERATOR_PENDING")
SELL_INCOMING_STATUSES = ("PENDING", "OPERATOR_PENDING")

_IN_PROGRESS_ORDER_WHERE = """
    o.operator_id IS NOT NULL
    AND o.status NOT IN ('PAID', 'CANCELED', 'EXPIRED', 'FAILED')
"""


async def _queue_stats(conn) -> dict:
    """Счётчики для вкладки «Очередь» (без списка заявок)."""
    ready = int(
        await conn.fetchval(
            """
            SELECT COUNT(*) FROM orders
            WHERE operator_id IS NULL
              AND (
                (direction = 'buy' AND status = ANY($1::text[]))
                OR (direction = 'sell' AND status = ANY($2::text[]))
              )
            """,
            list(BUY_INCOMING_STATUSES),
            list(SELL_INCOMING_STATUSES),
        )
        or 0
    )
    awaiting_receipt = int(
        await conn.fetchval(
            """
            SELECT COUNT(*) FROM orders
            WHERE operator_id IS NULL
              AND direction = 'buy'
              AND status = 'AWAITING_CHECK'
            """
        )
        or 0
    )
    wd_incoming = int(
        await conn.fetchval(
            """
            SELECT COUNT(*) FROM user_referral_withdrawals
            WHERE status = 'pending' AND operator_id IS NULL
            """
        )
        or 0
    )
    total_ready = ready + wd_incoming
    return {
        "queue_count": total_ready,
        "ready_to_accept_count": total_ready,
        "awaiting_receipt_count": awaiting_receipt,
        "withdrawal_incoming_count": wd_incoming,
        "exchange_incoming_count": ready,
    }


async def _queue_count(conn) -> int:
    return (await _queue_stats(conn))["queue_count"]


def _claimed_by(op: dict) -> dict:
    return {
        "id": op["id"],
        "display_name": op.get("display_name") or op["username"],
        "username": op["username"],
    }


async def _operator_display_name(conn, operator_id: int) -> str:
    row = await conn.fetchrow(
        "SELECT display_name, username FROM operator_accounts WHERE id = $1",
        operator_id,
    )
    if not row:
        return f"id {operator_id}"
    return row["display_name"] or row["username"] or f"id {operator_id}"


async def _require_active_shift(conn, operator_id: int):
    row = await conn.fetchrow(
        """
        SELECT * FROM operator_shifts
        WHERE operator_id = $1 AND ended_at IS NULL
        ORDER BY started_at DESC
        LIMIT 1
        """,
        operator_id,
    )
    if not row:
        raise HTTPException(
            status_code=403,
            detail="Откройте смену на вкладке «Смена»",
        )
    return row


async def _active_work_count(conn, operator_id: int) -> int:
    orders = await conn.fetchval(
        """
        SELECT COUNT(*)::int FROM orders
        WHERE operator_id = $1
          AND status NOT IN ('PAID', 'CANCELED', 'EXPIRED', 'FAILED')
        """,
        operator_id,
    )
    withdrawals = await conn.fetchval(
        """
        SELECT COUNT(*)::int FROM user_referral_withdrawals
        WHERE operator_id = $1 AND status = 'pending'
        """,
        operator_id,
    )
    return int(orders or 0) + int(withdrawals or 0)


async def _team_snapshot(conn) -> dict:
    from operator_avatars import operator_avatar_public_url

    rows = await conn.fetch(
        """
        SELECT oa.id, oa.username, oa.display_name, oa.avatar_file_id,
               os.id AS shift_id,
               os.started_at AS shift_started_at,
               (
                   SELECT COUNT(*)::int FROM orders o
                   WHERE o.operator_id = oa.id
                     AND o.status NOT IN ('PAID', 'CANCELED', 'EXPIRED', 'FAILED')
               ) AS orders_in_progress,
               (
                   SELECT COUNT(*)::int FROM user_referral_withdrawals w
                   WHERE w.operator_id = oa.id AND w.status = 'pending'
               ) AS withdrawals_in_progress
        FROM operator_accounts oa
        LEFT JOIN operator_shifts os
            ON os.operator_id = oa.id AND os.ended_at IS NULL
        WHERE oa.is_active
        ORDER BY (os.started_at IS NULL), os.started_at DESC, oa.username
        """
    )
    operators = []
    on_shift = []
    for r in rows:
        started = r["shift_started_at"]
        item = {
            "id": r["id"],
            "username": r["username"],
            "display_name": r.get("display_name"),
            "avatar_url": operator_avatar_public_url(r.get("avatar_file_id")),
            "on_shift": r["shift_id"] is not None,
            "shift_id": r["shift_id"],
            "shift_started_at": started.isoformat() if started else None,
            "orders_in_progress": int(r["orders_in_progress"] or 0),
            "withdrawals_in_progress": int(r["withdrawals_in_progress"] or 0),
        }
        item["workload"] = item["orders_in_progress"] + item["withdrawals_in_progress"]
        operators.append(item)
        if item["on_shift"]:
            on_shift.append(item)
    return {
        "operators": operators,
        "on_shift": on_shift,
        "on_shift_count": len(on_shift),
    }


# ---------------------------------------------------------------------------
# GET /api/operator/me — профиль + активная смена + статистика за текущую смену
# ---------------------------------------------------------------------------

@router.get("/me")
async def operator_me(op: dict = Depends(get_current_operator)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        shift_row = await conn.fetchrow(
            "SELECT * FROM operator_shifts WHERE operator_id = $1 AND ended_at IS NULL "
            "ORDER BY started_at DESC LIMIT 1",
            op["id"],
        )
        shift = _shift_out(dict(shift_row)) if shift_row else None
        team = await _team_snapshot(conn)

        stats = await conn.fetchrow(
            """
            SELECT COUNT(*) AS orders_count,
                   COALESCE(SUM(fiat_amount), 0) AS fiat_total
            FROM orders
            WHERE operator_id = $1
              AND status IN ('PAID', 'COMPLETED')
              AND created_at::date = now()::date
            """,
            op["id"],
        )
        q_count = await _queue_count(conn)
        active_work = await _active_work_count(conn, op["id"])

        current_shift = None
        shift_balances = []
        if shift_row:
            orders = await _shift_orders(
                conn, op["id"], shift_row["started_at"], None
            )
            current_shift = await stats_from_orders_conn(
                conn, orders, float(op.get("percent") or 0)
            )
            current_shift = strip_operator_profit_fields(current_shift)
            shift_balances = await _load_shift_balances(conn, shift_row["id"])

    return {
        "operator": operator_public_dict(op),
        "active_shift": shift,
        "shift_balances": shift_balances,
        "queue_count": q_count,
        "active_work_count": active_work,
        "current_shift": current_shift,
        "team_on_shift": team["on_shift"],
        "on_shift_count": team["on_shift_count"],
        "today": {
            "orders_count": stats["orders_count"] if stats else 0,
            "fiat_total": float(stats["fiat_total"]) if stats else 0.0,
        },
    }


# ---------------------------------------------------------------------------
# GET /api/operator/team — операторы и активные смены
# ---------------------------------------------------------------------------

@router.get("/team")
async def operator_team(
    op: dict = Depends(get_current_operator),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _team_snapshot(conn)


# ---------------------------------------------------------------------------
# Helpers: wallet balances stored in operator_shift_balances
# ---------------------------------------------------------------------------

from operator_shift_wallets import ShiftBalanceEntry, validate_shift_balances

BalanceEntry = ShiftBalanceEntry


async def _save_start_balances(conn, shift_id: int, balances: list[BalanceEntry]) -> None:
    for b in balances:
        crypto = b.crypto.lower().strip()
        if not crypto:
            continue
        await conn.execute(
            """
            INSERT INTO operator_shift_balances (shift_id, crypto, balance_start)
            VALUES ($1, $2, $3)
            ON CONFLICT (shift_id, crypto)
            DO UPDATE SET balance_start = EXCLUDED.balance_start
            """,
            shift_id,
            crypto,
            b.amount,
        )


async def _save_end_balances(conn, shift_id: int, balances: list[BalanceEntry]) -> None:
    for b in balances:
        crypto = b.crypto.lower().strip()
        if not crypto:
            continue
        await conn.execute(
            """
            INSERT INTO operator_shift_balances (shift_id, crypto, balance_end)
            VALUES ($1, $2, $3)
            ON CONFLICT (shift_id, crypto)
            DO UPDATE SET balance_end = EXCLUDED.balance_end
            """,
            shift_id,
            crypto,
            b.amount,
        )


async def _compute_network_fees(
    conn, shift_id: int, operator_id: int, started_at, ended_at
) -> list[dict]:
    """
    Для каждой крипты с записью в operator_shift_balances вычисляет:
      expected_end = balance_start − sent_in_buy + recv_in_sell
      network_fees = expected_end − balance_end
    """
    bal_rows = await conn.fetch(
        "SELECT crypto, balance_start, balance_end FROM operator_shift_balances WHERE shift_id = $1",
        shift_id,
    )
    if not bal_rows:
        return []

    cryptos = [r["crypto"] for r in bal_rows]
    started = utc_aware(started_at)
    ended = utc_aware(ended_at)

    order_rows = await conn.fetch(
        """
        SELECT direction, crypto, COALESCE(crypto_amount, 0) AS crypto_amount
        FROM orders
        WHERE operator_id = $1
          AND status IN ('PAID', 'COMPLETED')
          AND created_at >= $2::timestamptz
          AND ($3::timestamptz IS NULL OR created_at <= $3::timestamptz)
          AND LOWER(SPLIT_PART(crypto, '_', 1)) = ANY($4::text[])
        """,
        operator_id,
        started,
        ended,
        cryptos,
    )

    flow: dict[str, dict[str, float]] = {c: {"sent": 0.0, "recv": 0.0} for c in cryptos}
    for o in order_rows:
        base = (o["crypto"] or "").split("_")[0].lower()
        if base not in flow:
            continue
        if (o["direction"] or "").lower() == "buy":
            flow[base]["sent"] += float(o["crypto_amount"] or 0)
        else:
            flow[base]["recv"] += float(o["crypto_amount"] or 0)

    result = []
    for r in bal_rows:
        c = r["crypto"]
        bs = float(r["balance_start"]) if r["balance_start"] is not None else None
        be = float(r["balance_end"]) if r["balance_end"] is not None else None
        sent = flow.get(c, {}).get("sent", 0.0)
        recv = flow.get(c, {}).get("recv", 0.0)
        expected = None
        fees = None
        if bs is not None:
            expected = round(bs - sent + recv, 8)
            if be is not None:
                fees = round(expected - be, 8)
        result.append({
            "crypto": c,
            "balance_start": bs,
            "balance_end": be,
            "sent_in_buy": round(sent, 8),
            "recv_in_sell": round(recv, 8),
            "expected_end": expected,
            "network_fees": fees,
        })
    from operator_balance_fiat import enrich_balance_summary, market_prices_rub

    market = await market_prices_rub()
    return enrich_balance_summary(result, market)


async def _load_shift_balances(conn, shift_id: int) -> list[dict]:
    rows = await conn.fetch(
        "SELECT crypto, balance_start, balance_end FROM operator_shift_balances WHERE shift_id = $1 ORDER BY crypto",
        shift_id,
    )
    return [
        {
            "crypto": r["crypto"],
            "balance_start": float(r["balance_start"]) if r["balance_start"] is not None else None,
            "balance_end": float(r["balance_end"]) if r["balance_end"] is not None else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# POST /api/operator/shift/start — начать смену
# ---------------------------------------------------------------------------

class ShiftStartRequest(BaseModel):
    balances: list[BalanceEntry] = []


@router.post("/shift/start", status_code=201)
async def shift_start(
    body: ShiftStartRequest = ShiftStartRequest(),
    op: dict = Depends(get_current_operator),
):
    try:
        validated = validate_shift_balances(body.balances)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM operator_shifts WHERE operator_id = $1 AND ended_at IS NULL",
            op["id"],
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Смена уже открыта. Сначала завершите текущую.",
            )
        row = await conn.fetchrow(
            "INSERT INTO operator_shifts (operator_id) VALUES ($1) RETURNING *",
            op["id"],
        )
        await _save_start_balances(conn, row["id"], validated)
        op_name = op.get("display_name") or op["username"]
        from operator_shift_notify import notify_operator_shift

        await notify_operator_shift(conn, operator_name=op_name, action="open")
    return {"shift": _shift_out(dict(row))}


# ---------------------------------------------------------------------------
# POST /api/operator/shift/end — завершить смену
# ---------------------------------------------------------------------------

class ShiftEndRequest(BaseModel):
    note: Optional[str] = None
    balances: list[BalanceEntry] = []


@router.post("/shift/end")
async def shift_end(
    body: ShiftEndRequest = ShiftEndRequest(),
    op: dict = Depends(get_current_operator),
):
    try:
        validated = validate_shift_balances(body.balances)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    pool = await get_pool()
    async with pool.acquire() as conn:
        active_work = await _active_work_count(conn, op["id"])
        if active_work > 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Завершите или передайте активные заявки ({active_work}) "
                    "перед окончанием смены"
                ),
            )
        row = await conn.fetchrow(
            """
            UPDATE operator_shifts
            SET ended_at = now(),
                note = COALESCE($2, note)
            WHERE operator_id = $1 AND ended_at IS NULL
            RETURNING *
            """,
            op["id"],
            body.note,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Активная смена не найдена")
        await _save_end_balances(conn, row["id"], validated)
        orders = await _shift_orders(
            conn, op["id"], row["started_at"], row["ended_at"]
        )
        summary = await stats_from_orders_conn(
            conn, orders, float(op.get("percent") or 0)
        )
        summary = strip_operator_profit_fields(summary)
        balance_summary = await _compute_network_fees(
            conn, row["id"], op["id"], row["started_at"], row["ended_at"]
        )
        from operator_payroll_pool import accrue_shift

        await accrue_shift(conn, int(row["id"]), op["id"])
        op_name = op.get("display_name") or op["username"]
        from operator_shift_notify import notify_operator_shift

        await notify_operator_shift(conn, operator_name=op_name, action="close")
    return {
        "shift": _shift_out(dict(row)),
        "summary": {**summary, "balance_summary": balance_summary},
    }


# ---------------------------------------------------------------------------
# GET /api/operator/shifts — история смен
# ---------------------------------------------------------------------------

@router.get("/shifts")
async def get_shifts(
    limit: int = 20,
    offset: int = 0,
    op: dict = Depends(get_current_operator),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        shift_rows = await conn.fetch(
            """
            SELECT * FROM operator_shifts
            WHERE operator_id = $1
            ORDER BY started_at DESC
            LIMIT $2 OFFSET $3
            """,
            op["id"],
            limit,
            offset,
        )
        order_rows = await conn.fetch(
            """
            SELECT order_id, crypto, direction, fiat_amount, crypto_amount, rate,
                   cashback_applied_rub, card_fee_pct, created_at,
                   updated_at, payout_confirmed_at
            FROM orders
            WHERE operator_id = $1
              AND status IN ('PAID', 'COMPLETED')
            ORDER BY created_at DESC
            LIMIT 5000
            """,
            op["id"],
        )

        percent = float(op.get("percent") or 0)
        shifts_out = []
        for s in shift_rows:
            matched = [
                dict(o)
                for o in order_rows
                if order_completed_in_shift(
                    dict(o), s["started_at"], s["ended_at"]
                )
            ]
            st = await stats_from_orders_conn(conn, matched, percent)
            st = strip_operator_profit_fields(st)
            bal_summary = await _compute_network_fees(
                conn, s["id"], op["id"], s["started_at"], s["ended_at"]
            )
            shifts_out.append({**_shift_out(dict(s)), **st, "balance_summary": bal_summary})

    return {"shifts": shifts_out}


# ---------------------------------------------------------------------------
# GET /api/operator/orders — заявки оператора
# ---------------------------------------------------------------------------

@router.get("/orders")
async def get_operator_orders(
    limit: int = 50,
    offset: int = 0,
    op: dict = Depends(get_current_operator),
):
    """incoming — без оператора; orders — ваши; team_orders — у коллег (только просмотр)."""
    pool = await get_pool()
    op_id = op["id"]
    async with pool.acquire() as conn:
        incoming_rows = await conn.fetch(
            f"""
            {_ORDERS_WITH_BUYER_SQL}
            WHERE o.operator_id IS NULL
              AND (
                (o.direction = 'buy' AND o.status = ANY($1::text[]))
                OR (o.direction = 'sell' AND o.status = ANY($3::text[]))
              )
            ORDER BY o.created_at ASC
            LIMIT $2
            """,
            list(BUY_INCOMING_STATUSES),
            limit,
            list(SELL_INCOMING_STATUSES),
        )
        mine_rows = await conn.fetch(
            f"""
            {_ORDERS_WITH_BUYER_SQL}
            WHERE o.operator_id = $1
              AND o.status NOT IN ('PAID', 'CANCELED', 'EXPIRED', 'FAILED')
            ORDER BY o.created_at DESC
            LIMIT $2 OFFSET $3
            """,
            op_id,
            limit,
            offset,
        )
        team_rows = await conn.fetch(
            f"""
            {_ORDERS_WITH_BUYER_SQL}
            WHERE {_IN_PROGRESS_ORDER_WHERE}
              AND o.operator_id != $1
            ORDER BY o.updated_at DESC
            LIMIT $2
            """,
            op_id,
            limit,
        )

        wd_incoming_rows = await conn.fetch(
            f"""
            {_WITHDRAWALS_WITH_OPERATOR_SQL}
            WHERE w.status = 'pending' AND w.operator_id IS NULL
            ORDER BY w.created_at ASC
            LIMIT $1
            """,
            limit,
        )
        wd_mine_rows = await conn.fetch(
            f"""
            {_WITHDRAWALS_WITH_OPERATOR_SQL}
            WHERE w.status = 'pending' AND w.operator_id = $1
            ORDER BY w.created_at DESC
            LIMIT $2
            """,
            op_id,
            limit,
        )
        wd_team_rows = await conn.fetch(
            f"""
            {_WITHDRAWALS_WITH_OPERATOR_SQL}
            WHERE w.status = 'pending'
              AND w.operator_id IS NOT NULL
              AND w.operator_id != $1
            ORDER BY w.created_at DESC
            LIMIT $2
            """,
            op_id,
            limit,
        )
        stats = await _queue_stats(conn)
    cur = op_id
    return {
        **stats,
        "incoming": [_order_out(dict(r), current_operator_id=cur) for r in incoming_rows],
        "orders": [_order_out(dict(r), current_operator_id=cur) for r in mine_rows],
        "team_orders": [_order_out(dict(r), current_operator_id=cur) for r in team_rows],
        "withdrawals_incoming": [
            _withdrawal_out(dict(r), current_operator_id=cur) for r in wd_incoming_rows
        ],
        "withdrawals": [
            _withdrawal_out(dict(r), current_operator_id=cur) for r in wd_mine_rows
        ],
        "team_withdrawals": [
            _withdrawal_out(dict(r), current_operator_id=cur) for r in wd_team_rows
        ],
    }


@router.get("/orders/lookup")
async def lookup_operator_order(
    order_id: str = Query(..., min_length=4),
    op: dict = Depends(get_current_operator),
):
    """Поиск заявки по ID (из TG-уведомления)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            {_ORDERS_WITH_BUYER_SQL}
            WHERE o.order_id = $1
            """,
            order_id.strip().upper(),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    r = dict(row)
    st = str(r.get("status") or "")
    in_incoming = r.get("operator_id") is None and (
        (r["direction"] == "buy" and st in BUY_INCOMING_STATUSES)
        or (r["direction"] == "sell" and st in SELL_INCOMING_STATUSES)
    )
    op_id = op["id"]
    assigned_oid = r.get("operator_id")
    assigned_to_me = assigned_oid == op_id
    assigned_to_other = assigned_oid is not None and assigned_oid != op_id
    return {
        "order": _order_out(r, current_operator_id=op_id),
        "in_queue": in_incoming,
        "in_incoming": in_incoming,
        "assigned_to_me": assigned_to_me,
        "assigned_to_other": assigned_to_other,
        "assigned_operator": _assigned_operator_from_row(r),
    }


@router.get("/orders/{order_id}/receipt")
async def get_operator_order_receipt(
    order_id: str,
    _op: dict = Depends(get_current_operator),
):
    """Файл чека/видео клиента для просмотра оператором."""
    from receipt_serve import receipt_file_response

    pool = await get_pool()
    async with pool.acquire() as conn:
        receipt_file = await conn.fetchval(
            "SELECT receipt_file FROM orders WHERE order_id = $1",
            order_id.strip().upper(),
        )
    return receipt_file_response(receipt_file)


# ---------------------------------------------------------------------------
# GET /api/operator/queue — входящие заявки (сайт/бот)
# ---------------------------------------------------------------------------

@router.get("/queue")
async def get_operator_queue(
    limit: int = 50,
    op: dict = Depends(get_current_operator),
):
    """Сводка очереди + все заявки «в работе» (read-only на этой вкладке)."""
    pool = await get_pool()
    op_id = op["id"]
    async with pool.acquire() as conn:
        stats = await _queue_stats(conn)
        in_progress_rows = await conn.fetch(
            f"""
            {_ORDERS_WITH_BUYER_SQL}
            WHERE {_IN_PROGRESS_ORDER_WHERE}
            ORDER BY o.updated_at DESC
            LIMIT $1
            """,
            limit,
        )
        wd_in_progress_rows = await conn.fetch(
            f"""
            {_WITHDRAWALS_WITH_OPERATOR_SQL}
            WHERE w.status = 'pending' AND w.operator_id IS NOT NULL
            ORDER BY w.created_at DESC
            LIMIT $1
            """,
            limit,
        )
        in_progress_count = int(
            await conn.fetchval(
                f"SELECT COUNT(*) FROM orders o WHERE {_IN_PROGRESS_ORDER_WHERE}"
            )
            or 0
        )
        wd_in_progress_count = int(
            await conn.fetchval(
                """
                SELECT COUNT(*) FROM user_referral_withdrawals
                WHERE status = 'pending' AND operator_id IS NOT NULL
                """
            )
            or 0
        )
    cur = op_id
    in_progress_orders = [
        _order_out(dict(r), current_operator_id=cur) for r in in_progress_rows
    ]
    in_progress_withdrawals = [
        _withdrawal_out(dict(r), current_operator_id=cur) for r in wd_in_progress_rows
    ]
    return {
        **stats,
        "in_progress_count": in_progress_count + wd_in_progress_count,
        "in_progress_orders": in_progress_orders,
        "in_progress_withdrawals": in_progress_withdrawals,
    }


# ---------------------------------------------------------------------------
# POST /api/operator/orders/{order_id}/claim — взять BUY заявку
# ---------------------------------------------------------------------------

@router.post("/orders/{order_id}/claim")
async def claim_order(
    order_id: str,
    op: dict = Depends(get_current_operator),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_active_shift(conn, op["id"])
            existing = await conn.fetchrow(
                "SELECT * FROM orders WHERE order_id = $1 FOR UPDATE",
                order_id,
            )
            if not existing:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            if existing["operator_id"] is not None:
                if existing["operator_id"] == op["id"]:
                    return {
                        "order": _order_out(dict(existing)),
                        "claimed_by": _claimed_by(op),
                    }
                name = await _operator_display_name(conn, int(existing["operator_id"]))
                raise HTTPException(
                    status_code=409,
                    detail=f"Заявка уже у {name}",
                )
            direction = (existing["direction"] or "").lower()
            status = existing["status"]
            claimable = (
                direction == "buy" and status in BUY_INCOMING_STATUSES
            ) or (direction == "sell" and status in SELL_INCOMING_STATUSES)
            if not claimable:
                raise HTTPException(
                    status_code=404,
                    detail="Заявка ещё без чека или недоступна для принятия",
                )
            row = await conn.fetchrow(
                """
                UPDATE orders
                SET operator_id = $1, updated_at = now()
                WHERE order_id = $2
                  AND operator_id IS NULL
                RETURNING *
                """,
                op["id"],
                order_id,
            )
    if not row:
        raise HTTPException(status_code=409, detail="Не удалось принять заявку")
    return {"order": _order_out(dict(row)), "claimed_by": _claimed_by(op)}


class SellPaidRequest(BaseModel):
    """Отчёт оператора по SELL: фактически получено крипты и выдано рублей."""
    crypto_received: float
    fiat_paid_out: float

    @field_validator("crypto_received", "fiat_paid_out")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        return v


# ---------------------------------------------------------------------------
# POST /api/operator/orders/{order_id}/sell_paid — SELL: выплата по QR завершена
# ---------------------------------------------------------------------------

@router.post("/orders/{order_id}/sell_paid")
async def confirm_sell_paid(
    order_id: str,
    body: SellPaidRequest,
    op: dict = Depends(get_current_operator),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM orders WHERE order_id = $1 FOR UPDATE",
                order_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            if (row["direction"] or "").lower() != "sell":
                raise HTTPException(status_code=400, detail="Только для SELL-заявок")
            if row["status"] not in ("PENDING", "AWAITING_CHECK", "COMPLETED"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Нельзя завершить: статус «{row['status']}»",
                )
            if row["operator_id"] is not None and row["operator_id"] != op["id"]:
                raise HTTPException(status_code=403, detail="Заявка у другого оператора")

    from bot_status_bridge import update_order_status as bot_set_status

    if not await bot_set_status(order_id, "PAID"):
        raise HTTPException(status_code=409, detail="Недопустимый переход статуса")

    pool = await get_pool()
    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            """
            UPDATE orders
            SET operator_id = COALESCE(operator_id, $1),
                operator_crypto_received = $2,
                operator_fiat_paid_out = $3,
                updated_at = now()
            WHERE order_id = $4
              AND (operator_id IS NULL OR operator_id = $1)
            RETURNING *
            """,
            op["id"],
            body.crypto_received,
            body.fiat_paid_out,
            order_id,
        )
        if not updated:
            raise HTTPException(status_code=403, detail="Заявка у другого оператора")
    order_dict = dict(updated)
    try:
        from bot_status_bridge import notify_order_completed_for_user

        await notify_order_completed_for_user(order_dict)
    except Exception as e:
        logger.warning("notify sell_paid order=%s: %s", order_id, e)
    return {"order": _order_out(order_dict)}


# ---------------------------------------------------------------------------
# GET /api/operator/users/search — поиск покупателя в боте (до /users/{user_id})
# ---------------------------------------------------------------------------

@router.get("/users/search")
async def search_bot_users(
    q: str = Query(..., min_length=1, max_length=64),
    limit: int = Query(20, ge=1, le=50),
    op: dict = Depends(get_current_operator),
):
    del op
    from telegram_user_lookup import normalize_search_term, search_client_by_telegram

    term = normalize_search_term(q)
    if not term:
        raise HTTPException(
            status_code=400,
            detail="Укажите Telegram ID или @username клиента",
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        users = await search_client_by_telegram(conn, term, limit=limit)
    return {"users": users}


# ---------------------------------------------------------------------------
# GET /api/operator/users/{user_id} — профиль покупателя (операторский срез)
# ---------------------------------------------------------------------------

@router.get("/users/{user_id}")
async def get_operator_client_profile(
    user_id: int,
    op: dict = Depends(get_current_operator),
):
    del op
    from bot_user_avatars import fetch_and_cache_bot_user_avatar
    from buyer_profile_service import build_buyer_profile

    pool = await get_pool()
    async with pool.acquire() as conn:
        profile = await build_buyer_profile(conn, user_id, mode="operator", include_finance=False)
    if not profile:
        raise HTTPException(status_code=404, detail="Клиент не найден в боте")
    try:
        await fetch_and_cache_bot_user_avatar(user_id)
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)
    return profile


# ---------------------------------------------------------------------------
# GET /api/operator/users/{user_id}/discounts — активные купоны клиента
# ---------------------------------------------------------------------------

@router.get("/users/{user_id}/discounts")
async def get_buyer_active_discounts(
    user_id: int,
    fiat_amount: Optional[float] = Query(None, gt=0),
    op: dict = Depends(get_current_operator),
):
    del op
    from exchange_discount_db import get_active_discounts, preview_discount_amount

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM bot_users WHERE user_id = $1",
            user_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Клиент не найден в боте")

    discounts = await get_active_discounts(
        user_id, fiat_amount=fiat_amount if fiat_amount else None
    )
    out = []
    for d in discounts:
        applied = 0.0
        if fiat_amount:
            applied = preview_discount_amount(
                float(fiat_amount),
                float(d["amount_rub"]),
                float(d.get("min_order_rub") or 0),
            )
        out.append(
            {
                **d,
                "preview_applied_rub": round(applied, 2),
                "preview_fiat_to_pay": round(max(1.0, float(fiat_amount) - applied), 2)
                if fiat_amount and applied > 0
                else None,
            }
        )
    return {"discounts": out}


# ---------------------------------------------------------------------------
# POST /api/operator/orders — создать ручную заявку
# ---------------------------------------------------------------------------

def _normalize_operator_tx(tx_hash_raw: str) -> str:
    try:
        from services.buy_payout import normalize_tx_hash
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail="Сервис бота недоступен для проверки tx",
        ) from e
    normalized = normalize_tx_hash(tx_hash_raw)
    if not normalized:
        raise HTTPException(status_code=400, detail="Некорректный hash транзакции")
    return normalized


def _raise_manual_payout_error(err: str | None) -> None:
    if err == "not_found":
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if err == "already_paid":
        raise HTTPException(status_code=409, detail="Уже подтверждено в другом месте")
    if err == "invalid_tx":
        raise HTTPException(status_code=400, detail="Некорректный hash транзакции")
    if err == "wrong_status":
        raise HTTPException(status_code=409, detail="Недопустимый переход статуса")
    if err == "not_buy":
        raise HTTPException(status_code=400, detail="Только для BUY-заявок")
    if err == "crypto_exceeds_paid":
        raise HTTPException(
            status_code=400,
            detail=(
                "Сумма крипты в заявке больше оплаченной части. "
                "Исправьте заявку в админке или создайте новую — выплата заблокирована."
            ),
        )
    if err == "bridge_unavailable":
        raise HTTPException(status_code=503, detail="Сервис бота недоступен")
    if err and str(err).startswith("duplicate_tx_hash"):
        other = str(err).split(":", 1)[-1].strip() or "?"
        raise HTTPException(
            status_code=409,
            detail=(
                f"Этот hash транзакции уже указан в заявке {other}. "
                "Вставьте hash именно этой выплаты."
            ),
        )
    raise HTTPException(status_code=409, detail=err or "Не удалось подтвердить")


def _operator_order_exception_detail(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, asyncpg.UniqueViolationError):
        if "payout_tx_hash" in str(exc):
            return (
                409,
                "Этот hash транзакции уже используется в другой заявке.",
            )
        return 409, "Конфликт данных при создании заявки. Проверьте hash и покупателя."
    if isinstance(exc, asyncpg.CheckViolationError):
        if "partner_ledger_type_check" in str(exc):
            return (
                503,
                "Схема БД устарела (partner_ledger). "
                "Нужна миграция add_partner_ledger_hold_spend — сообщите администратору.",
            )
        return 400, "Нарушение ограничений БД при создании заявки."
    return 500, "Не удалось создать заявку. Повторите или сообщите администратору."


async def _rollback_orphan_manual_buy(pool, order_id: str) -> None:
    """Отмена OPERATOR_PENDING после сбоя финализации (не оставлять мусор в очереди)."""
    from bot_status_bridge import update_order_status as bot_set_status

    try:
        if await bot_set_status(order_id, "CANCELED"):
            return
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET status = 'CANCELED', updated_at = now()
                WHERE order_id = $1 AND status = 'OPERATOR_PENDING'
                """,
                order_id,
            )
    except Exception as e:
        logger.warning("rollback orphan manual buy order=%s: %s", order_id, e)


async def _finalize_manual_buy_paid(
    pool,
    order_id: str,
    operator_id: int,
    tx_hash_raw: str,
) -> dict:
    """OPERATOR_PENDING → PAID + payout fields + финансовые хуки + уведомление."""
    from bot_status_bridge import confirm_manual_buy_payout

    ok, err, order_out = await confirm_manual_buy_payout(
        order_id,
        tx_hash=tx_hash_raw,
        actor=f"operator:{operator_id}",
        operator_id=operator_id,
    )
    if not ok:
        _raise_manual_payout_error(err)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            order_id,
        )
    if row:
        return dict(row)
    return order_out or {}


class CreateOrderRequest(BaseModel):
    order_type: Literal["buy", "sell", "sell_qr"] = "buy"
    buyer_user_id: int = Field(..., gt=0, description="Telegram user_id покупателя")
    fiat_amount: Optional[float] = None
    crypto_amount: Optional[float] = None
    crypto: str
    wallet_address: Optional[str] = None
    tx_hash: Optional[str] = None
    network: Optional[str] = None
    requisites: Optional[str] = None
    client_name: Optional[str] = None
    crypto_received: Optional[float] = None
    fiat_paid_out: Optional[float] = None
    note: Optional[str] = None
    exchange_discount_id: Optional[int] = None

    @field_validator("crypto")
    @classmethod
    def _validate_crypto(cls, v: str) -> str:
        v = v.lower()
        if v not in SUPPORTED_CRYPTOS:
            raise ValueError(f"Unsupported crypto: {v}. Supported: {SUPPORTED_CRYPTOS}")
        return v

    @field_validator("fiat_amount")
    @classmethod
    def _validate_fiat(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("Сумма в рублях должна быть больше нуля")
        return v

    @field_validator("crypto_amount")
    @classmethod
    def _validate_crypto_amount(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("Сумма в крипте должна быть больше нуля")
        return v

    @field_validator("tx_hash")
    @classmethod
    def _strip_create_tx(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        t = v.strip()
        return t or None

    @model_validator(mode="after")
    def _validate_by_type(self) -> "CreateOrderRequest":
        if self.order_type == "buy":
            if not (self.tx_hash or "").strip():
                raise ValueError("Укажите hash транзакции")
            if self.fiat_amount is None and self.crypto_amount is None:
                raise ValueError("Укажите сумму в рублях или в крипте")
        elif self.order_type == "sell":
            if not (self.requisites or "").strip():
                raise ValueError("Укажите реквизиты для выплаты (карта / СБП)")
            if self.fiat_amount is None and self.crypto_amount is None:
                raise ValueError("Укажите сумму в рублях или в крипте")
        else:
            if self.crypto_received is None or self.crypto_received <= 0:
                raise ValueError("Укажите полученную сумму крипты")
            payout = self.fiat_paid_out if self.fiat_paid_out is not None else self.fiat_amount
            if payout is None or payout <= 0:
                raise ValueError("Укажите сумму выплаты в рублях")
        return self


@router.post("/orders", status_code=201)
async def create_operator_order(
    body: CreateOrderRequest,
    op: dict = Depends(get_current_operator),
):
    shift = None
    pool = await get_pool()
    async with pool.acquire() as conn:
        shift = await conn.fetchrow(
            "SELECT id FROM operator_shifts WHERE operator_id = $1 AND ended_at IS NULL",
            op["id"],
        )

    if not shift:
        raise HTTPException(
            status_code=400,
            detail="Нет активной смены. Начните смену перед созданием заявки.",
        )

    try:
        return await _create_operator_order_impl(body, op, pool)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "create_operator_order failed operator=%s type=%s",
            op["id"],
            body.order_type,
        )
        status_code, detail = _operator_order_exception_detail(exc)
        raise HTTPException(status_code=status_code, detail=detail) from exc


async def _create_operator_order_impl(
    body: CreateOrderRequest,
    op: dict,
    pool,
):
    try:
        market = await get_rates_cached()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Не удалось получить курс: {e}")

    base_rate = market.get(body.crypto)
    if not base_rate:
        raise HTTPException(status_code=400, detail=f"Курс для {body.crypto} недоступен")

    order_id = "OP" + secrets.token_hex(8).upper()
    buyer_id = body.buyer_user_id

    if body.order_type == "buy":
        crypto_dec, fiat_dec, rate_dec = _validate_amounts(
            body.crypto,
            "buy",
            body.fiat_amount,
            body.crypto_amount,
            market,
            manual_buy=True,
            operator_manual=True,
        )
        fiat_amount = float(fiat_dec)
        crypto_amount = float(crypto_dec)
        rate_used = float(rate_dec)
        cb_applied = 0.0
        disc_applied = 0.0
        disc_id = body.exchange_discount_id
        from buy_crypto_amount import clamp_buy_crypto_amount
        from exchange_discount_db import apply_discount_with_conn, hold_discount_for_order

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Лок на покупателя: исключаем гонку cashback-холдов при
                # параллельном создании заявок (сайт/панель/бот).
                await conn.execute("SELECT pg_advisory_xact_lock($1)", buyer_id)
                buyer = await _resolve_buyer_user_id(conn, buyer_id)
                use_cb = await should_use_cashback(buyer_id)
                fiat_base, crypto_base = fiat_amount, crypto_amount
                if disc_id:
                    fiat_base, crypto_base, disc_applied, disc_id = await apply_discount_with_conn(
                        conn,
                        int(disc_id),
                        buyer_id,
                        fiat_amount,
                        crypto_amount,
                        rate_used,
                        body.crypto,
                    )
                    if disc_applied > 0 and not await hold_discount_for_order(
                        conn, buyer_id, order_id, disc_id
                    ):
                        disc_applied = 0.0
                        disc_id = None
                        fiat_base, crypto_base = fiat_amount, crypto_amount
                fiat_amount, crypto_amount, cb_applied = await apply_cashback_with_conn(
                    conn,
                    buyer_id,
                    fiat_base,
                    crypto_base,
                    rate_used,
                    body.crypto,
                    use_cashback=use_cb,
                )
                crypto_amount = clamp_buy_crypto_amount(
                    crypto_amount,
                    fiat_amount=fiat_amount,
                    rate=rate_used,
                    crypto=body.crypto,
                    cashback_applied_rub=float(cb_applied or 0),
                    exchange_discount_applied_rub=float(disc_applied or 0),
                    lock_crypto=body.crypto_amount is not None,
                )
                await conn.fetchrow(
                    """
                    INSERT INTO orders (
                        order_id, user_id, direction, crypto, fiat_amount, crypto_amount,
                        rate, wallet_address, network, requisites, status, operator_id,
                        card_fee_pct, cashback_applied_rub,
                        exchange_discount_applied_rub, exchange_discount_id,
                        created_at, expires_at, updated_at
                    ) VALUES (
                        $1, $2, 'buy', $3, $4, $5, $6, $7::text, $8, $7::varchar,
                        'OPERATOR_PENDING', $9, $10, $11, $12, $13,
                        now(), now() + interval '24 hours', now()
                    )
                    RETURNING order_id
                    """,
                    order_id,
                    buyer_id,
                    body.crypto,
                    fiat_amount,
                    crypto_amount,
                    rate_used,
                    "",
                    body.network,
                    op["id"],
                    runtime_settings.card_fee_pct(manual=True),
                    float(cb_applied or 0),
                    float(disc_applied or 0),
                    disc_id,
                )
                if cb_applied and cb_applied > 0:
                    await hold_cashback_for_order(conn, buyer_id, order_id, cb_applied)

        try:
            order_dict = await _finalize_manual_buy_paid(
                pool, order_id, op["id"], body.tx_hash or ""
            )
        except HTTPException:
            await _rollback_orphan_manual_buy(pool, order_id)
            raise
        except Exception as exc:
            await _rollback_orphan_manual_buy(pool, order_id)
            logger.exception("finalize manual buy failed order=%s", order_id)
            status_code, detail = _operator_order_exception_detail(exc)
            raise HTTPException(status_code=status_code, detail=detail) from exc
        out = _order_out(order_dict)
        out["buyer_username"] = buyer.get("username")
        out["buyer_first_name"] = buyer.get("first_name")
        return {
            "order": out,
            "rate_used": round(rate_used, 2),
            "market_rate": round(base_rate, 2),
            "cashback_applied": float(cb_applied or 0),
            "exchange_discount_applied": float(disc_applied or 0),
        }

    if body.order_type == "sell":
        crypto_dec, fiat_dec, rate_dec = _validate_amounts(
            body.crypto,
            "sell",
            body.fiat_amount,
            body.crypto_amount,
            market,
            operator_manual=True,
        )
        fiat_amount = float(fiat_dec)
        crypto_amount = float(crypto_dec)
        rate_used = float(rate_dec)
        requisites = body.requisites.strip()
        if body.client_name:
            requisites = f"{body.client_name.strip()}\n{requisites}"
        if body.note:
            requisites = f"{requisites}\n{body.note.strip()}"
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _resolve_buyer_user_id(conn, buyer_id)
                row = await conn.fetchrow(
                    """
                    INSERT INTO orders (
                        order_id, user_id, direction, crypto, fiat_amount, crypto_amount,
                        rate, requisites, status, operator_id,
                        created_at, expires_at, updated_at
                    ) VALUES (
                        $1, $2, 'sell', $3, $4, $5, $6, $7, 'PENDING', $8,
                        now(), now() + interval '24 hours', now()
                    )
                    RETURNING *
                    """,
                    order_id,
                    buyer_id,
                    body.crypto,
                    fiat_amount,
                    crypto_amount,
                    rate_used,
                    requisites,
                    op["id"],
                )
            row = await conn.fetchrow(
                f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
                order_id,
            )
            if not row:
                raise HTTPException(status_code=500, detail="Заявка создана, но не найдена в БД")
        return {
            "order": _order_out(dict(row)),
            "rate_used": round(rate_used, 2),
            "market_rate": round(base_rate, 2),
        }

    # sell_qr — выплата по QR, сразу закрываем с отчётом
    fiat_paid = body.fiat_paid_out if body.fiat_paid_out is not None else body.fiat_amount
    if fiat_paid is None:
        raise HTTPException(status_code=400, detail="Укажите сумму выплаты в рублях")
    crypto_received = body.crypto_received
    sell_m = runtime_settings.sell_discount()
    fallback_rate = base_rate * sell_m
    rate_used = fiat_paid / crypto_received if crypto_received else fallback_rate
    requisites = (body.note or "Выплата через QR (СБП)").strip()
    if body.client_name:
        requisites = f"{body.client_name.strip()}\n{requisites}"
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _resolve_buyer_user_id(conn, buyer_id)
            await conn.fetchrow(
                """
                INSERT INTO orders (
                    order_id, user_id, direction, crypto, fiat_amount, crypto_amount,
                    rate, requisites, status, operator_id,
                    operator_crypto_received, operator_fiat_paid_out,
                    created_at, expires_at, updated_at
                ) VALUES (
                    $1, $2, 'sell', $3, $4, $5, $6, $7, 'CREATED', $8, $9, $10,
                    now(), now() + interval '24 hours', now()
                )
                RETURNING order_id
                """,
                order_id,
                buyer_id,
                body.crypto,
                fiat_paid,
                crypto_received,
                rate_used,
                requisites,
                op["id"],
                crypto_received,
                fiat_paid,
            )

    from bot_status_bridge import (
        notify_order_completed_for_user,
        update_order_status as bot_set_status,
    )

    if not await bot_set_status(order_id, "PAID"):
        raise HTTPException(status_code=500, detail="Не удалось закрыть заявку")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            order_id,
        )
    order_dict = dict(row) if row else {}
    try:
        await notify_order_completed_for_user(order_dict)
    except Exception as e:
        logger.warning("notify sell_qr paid order=%s: %s", order_id, e)
    return {
        "order": _order_out(order_dict),
        "rate_used": round(rate_used, 2),
        "market_rate": round(base_rate, 2),
    }


class BuyPayoutRequest(BaseModel):
    tx_hash: str
    force: bool = False

    @field_validator("tx_hash")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Укажите hash транзакции")
        return v.strip()


# ---------------------------------------------------------------------------
# Вывод баланса (user_referral_withdrawals)
# ---------------------------------------------------------------------------

@router.post("/withdrawals/{withdrawal_id}/claim")
async def claim_balance_withdrawal(
    withdrawal_id: int,
    op: dict = Depends(get_current_operator),
):
    from user_referral_withdraw import withdrawal_out

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_active_shift(conn, op["id"])
            existing = await conn.fetchrow(
                """
                SELECT * FROM user_referral_withdrawals
                WHERE id = $1 FOR UPDATE
                """,
                withdrawal_id,
            )
            if not existing:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            if existing["status"] != "pending":
                raise HTTPException(
                    status_code=404,
                    detail="Заявка уже обработана",
                )
            if existing["operator_id"] is not None:
                if existing["operator_id"] == op["id"]:
                    return {
                        "withdrawal": withdrawal_out(dict(existing)),
                        "claimed_by": _claimed_by(op),
                    }
                name = await _operator_display_name(
                    conn, int(existing["operator_id"])
                )
                raise HTTPException(
                    status_code=409,
                    detail=f"Заявка уже у {name}",
                )
            row = await conn.fetchrow(
                """
                UPDATE user_referral_withdrawals
                SET operator_id = $2
                WHERE id = $1
                  AND status = 'pending'
                  AND operator_id IS NULL
                RETURNING *
                """,
                withdrawal_id,
                op["id"],
            )
    if not row:
        raise HTTPException(status_code=409, detail="Не удалось принять заявку")
    return {"withdrawal": withdrawal_out(dict(row)), "claimed_by": _claimed_by(op)}


@router.post("/withdrawals/{withdrawal_id}/payout")
async def confirm_balance_withdrawal_crypto(
    withdrawal_id: int,
    body: BuyPayoutRequest,
    op: dict = Depends(get_current_operator),
):
    from user_referral_withdraw import (
        confirm_withdrawal_crypto_payout,
        get_withdrawal,
        notify_withdrawal_completed,
        withdrawal_out,
    )

    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])

    wd_row = await get_withdrawal(withdrawal_id)
    if not wd_row:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if wd_row["operator_id"] != op["id"]:
        raise HTTPException(status_code=403, detail="Сначала примите заявку")
    if (wd_row["method"] or "").lower() != "crypto":
        raise HTTPException(status_code=400, detail="Только для крипто-вывода")

    ok, err, wd = await confirm_withdrawal_crypto_payout(withdrawal_id, body.tx_hash)
    if err == "invalid_tx":
        raise HTTPException(status_code=400, detail="Некорректный hash транзакции")
    if err == "already_processed":
        raise HTTPException(status_code=409, detail="Заявка уже обработана")
    if err == "insufficient_balance":
        raise HTTPException(status_code=409, detail="Недостаточно средств на балансе клиента")
    if not ok or not wd:
        raise HTTPException(status_code=409, detail="Не удалось подтвердить выплату")

    await notify_withdrawal_completed(wd, tx_hash=body.tx_hash)
    return {"withdrawal": withdrawal_out(wd)}


@router.post("/withdrawals/{withdrawal_id}/paid")
async def confirm_balance_withdrawal_card(
    withdrawal_id: int,
    op: dict = Depends(get_current_operator),
):
    from user_referral_withdraw import (
        get_withdrawal,
        notify_withdrawal_completed,
        process_withdrawal_paid,
        withdrawal_out,
    )

    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])

    wd_row = await get_withdrawal(withdrawal_id)
    if not wd_row:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if wd_row["operator_id"] != op["id"]:
        raise HTTPException(status_code=403, detail="Сначала примите заявку")
    if (wd_row["method"] or "").lower() != "card":
        raise HTTPException(status_code=400, detail="Только для вывода на карту")

    wd, err = await process_withdrawal_paid(withdrawal_id)
    if err == "insufficient_balance":
        raise HTTPException(status_code=409, detail="Недостаточно средств на балансе клиента")
    if not wd:
        raise HTTPException(status_code=409, detail="Заявка уже обработана или недостаточно средств")
    await notify_withdrawal_completed(wd)
    return {"withdrawal": withdrawal_out(wd)}


# ---------------------------------------------------------------------------
# POST /api/operator/orders/{order_id}/payout — BUY: крипта отправлена (COMPLETED → PAID)
# ---------------------------------------------------------------------------

@router.post("/orders/{order_id}/payout")
async def confirm_buy_crypto_payout(
    order_id: str,
    body: BuyPayoutRequest,
    op: dict = Depends(get_current_operator),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])

    from bot_status_bridge import confirm_buy_payout

    if body.force:
        import logging as _logging
        _logging.getLogger("operator").warning(
            "FORCE payout requested order=%s operator=%s", order_id.strip(), op["id"]
        )

    ok, err, order = await confirm_buy_payout(
        order_id.strip(),
        tx_hash=body.tx_hash,
        actor=f"operator:{op['id']}",
        operator_id=op["id"],
        force=body.force,
    )
    if err and str(err).startswith("payfast_"):
        from services.payfast_payin_guard import payfast_block_message

        raise HTTPException(status_code=409, detail=payfast_block_message(err))
    if err == "wrong_status":
        raise HTTPException(
            status_code=400,
            detail="Подтверждение выплаты доступно только для заявок со статусом COMPLETED",
        )
    if not ok:
        _raise_manual_payout_error(err)
    return {"order": _order_out(order) if order else {}}


# ---------------------------------------------------------------------------
# PATCH /api/operator/orders/{order_id}/paid — OPERATOR_PENDING → PAID (ручные заявки)
# ---------------------------------------------------------------------------

class ManualPaidRequest(BaseModel):
    tx_hash: str

    @field_validator("tx_hash")
    @classmethod
    def _strip_tx(cls, v: str) -> str:
        t = (v or "").strip()
        if not t:
            raise ValueError("Укажите hash транзакции")
        return t


@router.patch("/orders/{order_id}/paid")
async def confirm_order_paid(
    order_id: str,
    body: ManualPaidRequest,
    op: dict = Depends(get_current_operator),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        row = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            order_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if row["operator_id"] != op["id"]:
            raise HTTPException(
                status_code=403,
                detail="Сначала возьмите заявку в очереди",
            )
        if row["status"] != "OPERATOR_PENDING":
            raise HTTPException(
                status_code=400,
                detail=f"Нельзя подтвердить: статус заявки «{row['status']}»",
            )
        _require_order_buyer(row)

    order_dict = await _finalize_manual_buy_paid(
        pool, order_id, op["id"], body.tx_hash
    )
    return {"order": _order_out(order_dict)}


# ---------------------------------------------------------------------------
# POST /api/operator/orders/{order_id}/cancel — отмена заявки с причиной
# ---------------------------------------------------------------------------

_CANCELABLE_STATUSES = (
    "CREATED",
    "AWAITING_CHECK",
    "PENDING",
    "COMPLETED",
    "OPERATOR_PENDING",
    "DISPUTE",
)


class CancelOrderRequest(BaseModel):
    reason: str = Field(..., max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        t = (v or "").strip()
        if len(t) < 3:
            raise ValueError("Укажите причину отмены (минимум 3 символа)")
        return t


def _cancel_user_text(order_id: str, reason: str) -> str:
    import html

    oid = html.escape(str(order_id))
    rsn = html.escape(reason)
    return (
        "❌ <b>Заявка отменена</b>\n\n"
        f"🆔 Заявка: <code>{oid}</code>\n"
        f"📝 Причина: {rsn}\n\n"
        "Если остались вопросы — напишите в поддержку."
    )


@router.post("/orders/{order_id}/cancel")
async def cancel_order_by_operator(
    order_id: str,
    body: CancelOrderRequest,
    op: dict = Depends(get_current_operator),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        row = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            order_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if row["operator_id"] is not None and row["operator_id"] != op["id"]:
            name = await _operator_display_name(conn, int(row["operator_id"]))
            raise HTTPException(status_code=403, detail=f"Заявка у {name}")
        if row["status"] not in _CANCELABLE_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Заявку нельзя отменить: статус «{row['status']}»",
            )
        await conn.execute(
            """
            UPDATE orders
            SET cancel_reason = $1, canceled_by = $2, updated_at = now()
            WHERE order_id = $3
            """,
            body.reason,
            op["id"],
            order_id,
        )

    order_dict = dict(row)

    if (order_dict.get("direction") or "").lower() == "buy":
        try:
            from merchant_api_helpers import cancel_payin_for_order

            await cancel_payin_for_order(order_dict)
        except Exception as e:
            logger.warning("cancel payin order=%s: %s", order_id, e)

    from bot_status_bridge import update_order_status as bot_set_status

    if not await bot_set_status(order_id, "CANCELED"):
        raise HTTPException(status_code=409, detail="Недопустимый переход статуса")

    buyer = order_dict.get("user_id")
    if buyer and int(buyer) > 0:
        try:
            from telegram_notify import send_user_message

            await send_user_message(int(buyer), _cancel_user_text(order_id, body.reason))
        except Exception as e:
            logger.warning("notify cancel order=%s: %s", order_id, e)

    pool = await get_pool()
    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            order_id,
        )
    return {"order": _order_out(dict(updated)) if updated else {}}


# ---------------------------------------------------------------------------
# POST /api/operator/users/{user_id}/ban  — заблокировать клиента
# POST /api/operator/users/{user_id}/unban — разблокировать клиента
# ---------------------------------------------------------------------------

class BanUserRequest(BaseModel):
    reason: str = Field("", max_length=500)
    ban_type: str = Field("hard", pattern="^(hard|soft)$")


async def _notify_user_banned(user_id: int, ban_type: str) -> None:
    if ban_type == "soft":
        return
    try:
        from telegram_notify import send_user_message

        await send_user_message(
            user_id,
            "🚫 <b>Ваш аккаунт заблокирован</b>\n\n"
            "Вы не можете создавать новые заявки.\n"
            "Если считаете это ошибкой — обратитесь в поддержку.",
        )
    except Exception as e:
        logger.warning("notify banned user=%s: %s", user_id, e)


async def _cancel_active_order_for_ban(user_id: int, pool) -> str | None:
    """Найти и отменить активную заявку клиента при бане. Возвращает order_id или None."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT order_id, direction
            FROM orders
            WHERE user_id = $1
              AND status NOT IN ('PAID', 'FAILED', 'CANCELED', 'EXPIRED')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            user_id,
        )
    if not row:
        return None
    order_id = row["order_id"]
    direction = (row.get("direction") or "").lower()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE orders
            SET cancel_reason = 'Клиент заблокирован оператором', updated_at = now()
            WHERE order_id = $1
            """,
            order_id,
        )

    if direction == "buy":
        try:
            async with pool.acquire() as conn2:
                order_full = await conn2.fetchrow("SELECT * FROM orders WHERE order_id = $1", order_id)
            if order_full:
                from merchant_api_helpers import cancel_payin_for_order
                await cancel_payin_for_order(dict(order_full))
        except Exception as e:
            logger.warning("cancel payin on ban order=%s: %s", order_id, e)

    try:
        from bot_status_bridge import update_order_status as bot_set_status
        await bot_set_status(order_id, "CANCELED")
    except Exception as e:
        logger.warning("bot status cancel on ban order=%s: %s", order_id, e)

    return order_id


@router.post("/users/{user_id}/ban", status_code=200)
async def ban_client(
    user_id: int,
    body: BanUserRequest,
    op: dict = Depends(get_current_operator),
):
    pool = await get_pool()
    from bot_status_bridge import ban_user as db_ban_user

    ok = await db_ban_user(
        user_id,
        reason=body.reason.strip(),
        operator_id=op["id"],
        ban_type=body.ban_type,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Клиент не найден в системе")

    cancelled_order = await _cancel_active_order_for_ban(user_id, pool)
    await _notify_user_banned(user_id, body.ban_type)

    logger.info(
        "ban user=%s type=%s by_op=%s order_cancelled=%s",
        user_id, body.ban_type, op["id"], cancelled_order,
    )
    return {
        "banned": True,
        "ban_type": body.ban_type,
        "user_id": user_id,
        "cancelled_order_id": cancelled_order,
    }


@router.post("/users/{user_id}/unban", status_code=200)
async def unban_client(
    user_id: int,
    op: dict = Depends(get_current_operator),
):
    from bot_status_bridge import is_user_banned as db_is_banned
    from bot_status_bridge import unban_user as db_unban_user

    was_banned, _, prev_ban_type = await db_is_banned(user_id)
    ok = await db_unban_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Клиент не найден в системе")

    # Тихий блок не палим клиенту уведомлением о «разблокировке»
    if was_banned and (prev_ban_type or "hard") != "soft":
        try:
            from telegram_notify import send_user_message

            await send_user_message(
                user_id,
                "✅ <b>Ваш аккаунт разблокирован</b>\n\nВы снова можете совершать обмены.",
            )
        except Exception as e:
            logger.warning("notify unbanned user=%s: %s", user_id, e)

    logger.info(
        "unban user=%s by_op=%s was_type=%s",
        user_id,
        op["id"],
        prev_ban_type if was_banned else None,
    )
    return {
        "banned": False,
        "user_id": user_id,
        "was_ban_type": prev_ban_type if was_banned else None,
    }


# ---------------------------------------------------------------------------
# GET /api/operator/rate — текущий курс (для формы создания заявки)
# ---------------------------------------------------------------------------

@router.get("/rate")
async def get_rate_for_order(
    crypto: str = "usdt",
    op: dict = Depends(get_current_operator),
):
    crypto = crypto.lower()
    if crypto not in SUPPORTED_CRYPTOS:
        raise HTTPException(status_code=400, detail="Unsupported crypto")
    try:
        market = await get_rates_cached()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
    base = market.get(crypto)
    if not base:
        raise HTTPException(status_code=404, detail="Rate not available")
    import runtime_settings

    base = market.get(crypto)
    if not base:
        raise HTTPException(status_code=404, detail="Rate not available")
    manual_m = runtime_settings.buy_markup(manual=True)
    sell_d = runtime_settings.sell_discount()
    return {
        "crypto": crypto,
        "market_rate": round(base, 2),
        "buy_rate": round(base * manual_m, 2),
        "sell_rate": round(base * sell_d, 2),
        "buy_commission_pct": commission_percent(crypto, "buy", manual=True),
        "sell_commission_pct": commission_percent(crypto, "sell"),
        "buy_markup": manual_m,
        "sell_discount": sell_d,
    }


# ---------------------------------------------------------------------------
# Аватар оператора
# ---------------------------------------------------------------------------


@router.post("/avatar")
async def upload_operator_avatar(
    file: UploadFile = File(...),
    op: dict = Depends(get_current_operator),
):
    from operator_avatars import delete_operator_avatar_file, save_operator_avatar

    content = await file.read()
    file_id = save_operator_avatar(content, file.content_type, file.filename)

    pool = await get_pool()
    async with pool.acquire() as conn:
        old = await conn.fetchval(
            "SELECT avatar_file_id FROM operator_accounts WHERE id = $1",
            op["id"],
        )
        row = await conn.fetchrow(
            """
            UPDATE operator_accounts SET avatar_file_id = $2
            WHERE id = $1
            RETURNING *
            """,
            op["id"],
            file_id,
        )
    delete_operator_avatar_file(old)
    return {"operator": operator_public_dict(dict(row))}


@router.delete("/avatar")
async def delete_operator_avatar(op: dict = Depends(get_current_operator)):
    from operator_avatars import delete_operator_avatar_file

    pool = await get_pool()
    async with pool.acquire() as conn:
        old = await conn.fetchval(
            "SELECT avatar_file_id FROM operator_accounts WHERE id = $1",
            op["id"],
        )
        row = await conn.fetchrow(
            """
            UPDATE operator_accounts SET avatar_file_id = NULL
            WHERE id = $1
            RETURNING *
            """,
            op["id"],
        )
    delete_operator_avatar_file(old)
    return {"operator": operator_public_dict(dict(row))}


# ---------------------------------------------------------------------------
# Общий пул зарплаты — баланс и заявки на вывод
# ---------------------------------------------------------------------------


class OperatorPayoutRequestBody(BaseModel):
    amount_rub: float
    requisites: str

    @field_validator("amount_rub")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        return v

    @field_validator("requisites")
    @classmethod
    def _req(cls, v: str) -> str:
        if len((v or "").strip()) < 5:
            raise ValueError("Укажите реквизиты")
        return v.strip()


@router.get("/payroll/balance")
async def operator_payroll_balance(op: dict = Depends(get_current_operator)):
    from operator_payroll_pool import backfill_accruals, operator_balance

    pool = await get_pool()
    async with pool.acquire() as conn:
        await backfill_accruals(conn)
        bal = await operator_balance(conn, op["id"])
        my_pending = await conn.fetchrow(
            """
            SELECT id, amount_rub, requisites, status, created_at
            FROM operator_payout_requests
            WHERE operator_id = $1 AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            op["id"],
        )
    pending = None
    if my_pending:
        pending = dict(my_pending)
        if pending.get("created_at") and hasattr(pending["created_at"], "isoformat"):
            pending["created_at"] = pending["created_at"].isoformat()
    return {**bal, "my_pending_request": pending}


@router.post("/payroll/request", status_code=201)
async def operator_payroll_request(
    body: OperatorPayoutRequestBody,
    op: dict = Depends(get_current_operator),
):
    from operator_payroll_pool import (
        create_payout_request,
        format_payout_admin_message,
        payout_admin_keyboard,
    )
    from telegram_notify import send_finance_owner_message

    try:
        row = await create_payout_request(
            operator_id=op["id"],
            amount_rub=body.amount_rub,
            requisites=body.requisites,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    name = op.get("display_name") or op["username"]
    msg_id = await send_finance_owner_message(
        format_payout_admin_message(row, name),
        reply_markup=payout_admin_keyboard(row["id"]),
    )
    if msg_id:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE operator_payout_requests
                SET admin_message_id = $1 WHERE id = $2
                """,
                msg_id,
                row["id"],
            )
    return {
        "id": row["id"],
        "status": row["status"],
        "amount_rub": float(row["amount_rub"]),
    }
