"""Реквизиты выплат оператора: публикация, автоподбор чеков, доливы.

Оператор ставит чужую карту/СБП под выплату (сумма + стоимость в %), матчер
подбирает SELL-заявки за минимальное число чеков, оператор бронирует план и
закрывает чеки. Мелочь, в которую не попали клиентами, добивает доливом.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator

from auth import get_current_operator
from db import get_pool
from payin_requisite_rail import (
    complete_triangle_sell,
    complete_triangle_withdrawal,
    parse_sell_fiat_bill,
)
from payout_requisite_matcher import (
    ACTIVE_ALLOCATION_STATUSES,
    ACTIVE_REQUISITE_STATUSES,
    CANDIDATE_ORDER_STATUSES,
    DEFAULT_DOLIV_LIMIT_RUB,
    DEFAULT_MAX_CHECKS,
    DEFAULT_WINDOW_MINUTES,
    LIST_REQUISITE_STATUSES,
    METHOD_SUB_TOKENS,
    REQUISITE_COLUMNS,
    from_kop,
    is_triangle_row,
    latest_plan,
    load_pool_orders,
    payin_one_check_only,
    payin_stored_limits,
    plan_for_requisite,
    pool_order_payload,
    remaining_rub,
    reserved_kop,
    store_plan,
    to_kop,
)
from payout_requisite_cost import (
    DEFAULT_CRYPTO,
    DIRECTION_PAYIN,
    DIRECTION_PAYOUT,
    SUPPORTED_CRYPTO,
    cost_rub,
    payoff_crypto,
    payoff_rub,
    safe_post_requisite_cost,
)
from payout_requisite_receipts import doliv_receipt_response, save_doliv_receipt
from permissions import (
    PERM_PAYOUT_REQUISITES,
    PERM_PAYOUT_REQUISITES_CONFIRM,
    enrich_operator_permissions,
    has_permission,
    require_permission,
)
from routers.public import get_need_rates_cached

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_WINDOW_MINUTES = 24 * 60
MIN_WINDOW_MINUTES = 15

REQUISITE_COLUMNS_PREFIXED = ", ".join(
    f"r.{name}" for name in (col.strip() for col in REQUISITE_COLUMNS.split(",")) if name
)


async def _require_payout_requisites(op: dict) -> dict:
    enriched = await enrich_operator_permissions(op)
    return require_permission(enriched, PERM_PAYOUT_REQUISITES)


async def _require_payout_requisites_confirm(op: dict) -> dict:
    enriched = await enrich_operator_permissions(op)
    return require_permission(
        enriched, PERM_PAYOUT_REQUISITES, PERM_PAYOUT_REQUISITES_CONFIRM
    )


def _cached_plan_usable(plan: dict | None, row) -> bool:
    """Старый payin-прогноз без splits прячем — иначе остаётся «не закроется»."""
    if not plan:
        return False
    if str(row.get("direction") or DIRECTION_PAYOUT).lower() != DIRECTION_PAYIN:
        return True
    if is_triangle_row(row):
        return True
    return "splits" in plan


async def _plan_for_owned(conn, row, *, owned: bool) -> dict | None:
    if not owned:
        return None
    cached = await latest_plan(conn, int(row["id"]))
    if _cached_plan_usable(cached, row):
        return cached
    if row["status"] not in LIST_REQUISITE_STATUSES:
        return cached
    computed, free = await plan_for_requisite(conn, row)
    await store_plan(conn, int(row["id"]), computed, free)
    payload = computed.as_dict() if computed else {"orders": [], "closes": False}
    payload["free_rub"] = float(free)
    return payload


def mask_requisites(value: str | None) -> str | None:
    text = str(value or "").strip()
    if len(text) <= 4:
        return text or None
    return f"···{text[-4:]}"


def _cost_rub(row) -> Decimal:
    return cost_rub(row["paid_rub"], row["cost_pct"])


def _requisite_out(row, *, reveal: bool = False) -> dict:
    data = dict(row) if not isinstance(row, dict) else row
    max_checks = int(data.get("max_checks") or DEFAULT_MAX_CHECKS)
    used_n = data.get("used_checks")
    used_n = int(used_n) if used_n is not None else None
    checks_left = max(0, max_checks - used_n) if used_n is not None else None
    has_reserve = data.get("has_open_reserve")
    leftover = remaining_rub(data)
    reserved = Decimal(str(data.get("reserved_rub") or 0))
    free = (leftover - reserved).quantize(Decimal("0.01"))
    if free < 0:
        free = Decimal("0.00")
    return {
        "id": int(data["id"]),
        "operator_id": int(data["operator_id"]),
        "label": data.get("label"),
        "direction": str(data.get("direction") or DIRECTION_PAYOUT),
        "method": data["method"],
        "requisites": data["requisites"] if reveal else mask_requisites(data.get("requisites")),
        "requisites_masked": mask_requisites(data.get("requisites")),
        "bank": data.get("bank"),
        "holder_name": data.get("holder_name"),
        "amount_rub": float(data["amount_rub"]),
        "paid_rub": float(data.get("paid_rub") or 0),
        "remaining_rub": float(leftover),
        "reserved_rub": float(reserved),
        "free_rub": float(free),
        "cost_pct": float(data.get("cost_pct") or 0),
        "cost_rub": float(_cost_rub(data)),
        "crypto": data.get("crypto") or DEFAULT_CRYPTO,
        "payoff_rub": float(payoff_rub(data.get("paid_rub"), data.get("cost_pct"), data.get("direction"))),
        "max_checks": max_checks,
        "used_checks": used_n,
        "checks_left": checks_left,
        "has_open_reserve": bool(has_reserve) if has_reserve is not None else None,
        "doliv_limit_rub": int(data.get("doliv_limit_rub") or 0),
        "status": data["status"],
        "deadline_at": data["deadline_at"].isoformat() if data.get("deadline_at") else None,
        "closed_at": data["closed_at"].isoformat() if data.get("closed_at") else None,
        "close_note": data.get("close_note"),
        "confirmed_at": data["confirmed_at"].isoformat() if data.get("confirmed_at") else None,
        "confirmed_by": int(data["confirmed_by"]) if data.get("confirmed_by") is not None else None,
        "source_sell_order_id": (
            str(data["source_sell_order_id"]) if data.get("source_sell_order_id") else None
        ),
        "source_withdrawal_id": (
            int(data["source_withdrawal_id"])
            if data.get("source_withdrawal_id") not in (None, "")
            else None
        ),
        "created_at": data["created_at"].isoformat() if data.get("created_at") else None,
    }


async def _attach_check_stats(conn, data: dict) -> dict:
    rid = int(data["id"])
    used = await conn.fetchval(
        """
        SELECT COUNT(*)::int
        FROM payout_requisite_allocations
        WHERE requisite_id = $1 AND status = ANY($2::text[])
        """,
        rid,
        list(ACTIVE_ALLOCATION_STATUSES),
    )
    reserved_n = await conn.fetchval(
        """
        SELECT COUNT(*)::int
        FROM payout_requisite_allocations
        WHERE requisite_id = $1 AND status = 'RESERVED'
        """,
        rid,
    )
    reserved_sum = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)
        FROM payout_requisite_allocations
        WHERE requisite_id = $1 AND status IN ('RESERVED')
        """,
        rid,
    )
    out = dict(data)
    out["used_checks"] = int(used or 0)
    out["has_open_reserve"] = int(reserved_n or 0) > 0
    out["reserved_rub"] = from_kop(to_kop(reserved_sum or 0))
    max_checks = int(out.get("max_checks") or DEFAULT_MAX_CHECKS)
    out["checks_left"] = max(0, max_checks - int(used or 0))
    return out


def _row_get(row, key, default=None):
    getter = getattr(row, "get", None)
    if callable(getter):
        return getter(key, default)
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def _snapshot_dict(row) -> dict:
    snap = _row_get(row, "payment_snapshot")
    if isinstance(snap, str):
        try:
            snap = json.loads(snap)
        except Exception:
            return {}
    return snap if isinstance(snap, dict) else {}


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


async def _deliver_payout_receipt(order: dict, receipt_file: str | None, *, fallback_text: bool) -> None:
    from payout_client_receipt import deliver_payout_receipt_to_client

    sent = await deliver_payout_receipt_to_client(order, receipt_file)
    if sent or not fallback_text:
        return
    try:
        from payout_client_receipt import sell_payout_caption
        from telegram_notify import send_user_message

        uid = int(order.get("user_id") or 0)
        if uid > 0:
            await send_user_message(uid, sell_payout_caption(order))
    except Exception as exc:
        logger.warning("payout receipt notify fallback order=%s: %s", order.get("order_id"), exc)


def _allocation_out(row, *, reveal_order: bool = False) -> dict:
    paid_at = row["paid_at"]
    created_at = row["created_at"]
    order_receipt = _row_get(row, "order_receipt_file")
    fiat = _row_get(row, "order_fiat_amount")
    snap = _snapshot_dict(row)
    confirmed = _row_get(row, "client_confirmed_at")
    requisites = str(_row_get(row, "order_requisites") or "").strip()
    user_id = _row_get(row, "order_user_id")
    crypto_amt = _row_get(row, "order_crypto_amount")
    wallet = str(_row_get(row, "order_wallet") or "").strip()
    username = str(_row_get(row, "buyer_username") or "").strip() or None
    first_name = str(_row_get(row, "buyer_first_name") or "").strip() or None
    return {
        "id": int(row["id"]),
        "requisite_id": int(row["requisite_id"]),
        "order_id": row["order_id"],
        "kind": row["kind"],
        "amount_rub": float(row["amount_rub"]),
        "status": row["status"],
        "has_receipt": bool(row["receipt_file"]),
        "has_buyer_receipt": bool(order_receipt),
        "order_status": _row_get(row, "order_status"),
        "order_crypto": _row_get(row, "order_crypto"),
        "order_fiat_amount": float(fiat) if fiat is not None else None,
        "order_sub_token": _row_get(row, "order_sub_token"),
        "order_requisites": (requisites or None) if reveal_order else None,
        "user_id": int(user_id) if reveal_order and user_id is not None else None,
        "buyer_username": username if reveal_order else None,
        "buyer_first_name": first_name if reveal_order else None,
        "order_crypto_amount": float(crypto_amt) if reveal_order and crypto_amt is not None else None,
        "order_wallet": (wallet or None) if reveal_order else None,
        "receipt_ops_pending": bool(snap.get("receipt_ops_pending")),
        "client_confirmed": bool(confirmed),
        "client_confirmed_at": _iso(confirmed),
        "paid_at": paid_at.isoformat() if paid_at else None,
        "note": row["note"],
        "created_at": created_at.isoformat() if created_at else None,
    }


async def _load_requisite(conn, requisite_id: int, *, for_update: bool = False):
    row = await conn.fetchrow(
        f"""
        SELECT {REQUISITE_COLUMNS}
        FROM operator_payout_requisites
        WHERE id = $1
        {"FOR UPDATE" if for_update else ""}
        """,
        int(requisite_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Реквизит не найден")
    return row


def _require_owner(row, op: dict):
    if int(row["operator_id"]) != int(op["id"]):
        raise HTTPException(status_code=403, detail="Реквизит другого оператора")


def _require_active(row):
    if row["status"] not in ACTIVE_REQUISITE_STATUSES:
        raise HTTPException(status_code=409, detail=f"Реквизит уже «{row['status']}»")


async def _allocations(conn, requisite_id: int) -> list:
    return await conn.fetch(
        """
        SELECT a.id, a.requisite_id, a.order_id, a.kind, a.amount_rub, a.status,
               a.receipt_file, a.paid_at, a.note, a.created_at, a.client_confirmed_at,
               o.status AS order_status,
               o.receipt_file AS order_receipt_file,
               o.fiat_amount AS order_fiat_amount,
               o.crypto AS order_crypto,
               o.crypto_amount AS order_crypto_amount,
               o.requisites AS order_requisites,
               o.sub_token AS order_sub_token,
               o.user_id AS order_user_id,
               o.wallet_address AS order_wallet,
               o.payment_snapshot,
               bu.username AS buyer_username,
               bu.first_name AS buyer_first_name
        FROM payout_requisite_allocations a
        LEFT JOIN orders o ON o.order_id = a.order_id
        LEFT JOIN bot_users bu ON bu.user_id = o.user_id
        WHERE a.requisite_id = $1
        ORDER BY a.created_at ASC, a.id ASC
        """,
        int(requisite_id),
    )


async def _refresh_status(conn, requisite_id: int) -> None:
    """Статус выводим из фактов: сколько выплачено и что ещё забронировано."""
    row = await _load_requisite(conn, requisite_id)
    if row["status"] in ("CLOSED", "CANCELED", "EXPIRED", "QUEUED"):
        return
    paid_kop = to_kop(row["paid_rub"] or 0)
    amount_kop = to_kop(row["amount_rub"])
    if paid_kop >= amount_kop:
        closed = await conn.fetchrow(
            f"""
            UPDATE operator_payout_requisites
            SET status = 'CLOSED', closed_at = COALESCE(closed_at, now()), updated_at = now()
            WHERE id = $1
            RETURNING {REQUISITE_COLUMNS}
            """,
            int(requisite_id),
        )
        await safe_post_requisite_cost(conn, closed)
        return
    has_reserved = await reserved_kop(conn, requisite_id) > 0
    if has_reserved:
        status = "RESERVED"
    elif paid_kop > 0:
        status = "PARTIAL"
    else:
        status = "OPEN"
    await conn.execute(
        "UPDATE operator_payout_requisites SET status = $2, updated_at = now() WHERE id = $1",
        int(requisite_id),
        status,
    )


# ---------------------------------------------------------------------------
# Создание и просмотр
# ---------------------------------------------------------------------------


class RequisiteCreateBody(BaseModel):
    method: str
    requisites: str = Field(min_length=4, max_length=256)
    amount_rub: Decimal = Field(gt=0)
    cost_pct: Decimal = Decimal("0")
    crypto: str = DEFAULT_CRYPTO
    direction: str = DIRECTION_PAYOUT
    label: Optional[str] = Field(None, max_length=128)
    bank: str = Field(min_length=2, max_length=128)
    holder_name: str = Field(min_length=2, max_length=256)
    window_minutes: int = DEFAULT_WINDOW_MINUTES
    max_checks: int = DEFAULT_MAX_CHECKS
    doliv_limit_rub: int = DEFAULT_DOLIV_LIMIT_RUB

    @field_validator("method")
    @classmethod
    def _method(cls, v: str) -> str:
        m = (v or "").strip().lower()
        if m not in METHOD_SUB_TOKENS:
            raise ValueError("method must be card or sbp")
        return m

    @field_validator("cost_pct")
    @classmethod
    def _cost(cls, v: Decimal) -> Decimal:
        if v < -100 or v > 100:
            raise ValueError("cost_pct must be between -100 and 100")
        return v

    @field_validator("crypto")
    @classmethod
    def _crypto(cls, v: str) -> str:
        c = (v or "").strip().lower() or DEFAULT_CRYPTO
        if c not in SUPPORTED_CRYPTO:
            raise ValueError(f"crypto must be one of {', '.join(SUPPORTED_CRYPTO)}")
        return c

    @field_validator("direction")
    @classmethod
    def _direction(cls, v: str) -> str:
        d = (v or "").strip().lower() or DIRECTION_PAYOUT
        if d not in (DIRECTION_PAYOUT, DIRECTION_PAYIN):
            raise ValueError("direction must be payout or payin")
        return d

    @field_validator("bank", "holder_name")
    @classmethod
    def _required_text(cls, v: str) -> str:
        s = (v or "").strip()
        if len(s) < 2:
            raise ValueError("укажите банк и ФИО")
        return s

    @field_validator("window_minutes")
    @classmethod
    def _window(cls, v: int) -> int:
        if v < MIN_WINDOW_MINUTES or v > MAX_WINDOW_MINUTES:
            raise ValueError(f"window_minutes must be {MIN_WINDOW_MINUTES}..{MAX_WINDOW_MINUTES}")
        return v

    @field_validator("max_checks")
    @classmethod
    def _checks(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError("max_checks must be 1..5")
        return v

    @field_validator("doliv_limit_rub")
    @classmethod
    def _doliv(cls, v: int) -> int:
        if v < 0:
            raise ValueError("doliv_limit_rub must be >= 0")
        return min(int(v), DEFAULT_DOLIV_LIMIT_RUB)


def _payin_needs_queue_fix(row) -> bool:
    if str(row.get("direction") or DIRECTION_PAYOUT) != DIRECTION_PAYIN:
        return False
    if str(row.get("status") or "") != "QUEUED":
        return True
    return row.get("confirmed_at") is not None


class FromSellBody(BaseModel):
    method: Optional[str] = None
    requisites: Optional[str] = None
    bank: Optional[str] = None
    holder_name: Optional[str] = None

    @field_validator("method")
    @classmethod
    def _method(cls, v: str | None) -> str | None:
        if v is None or not str(v).strip():
            return None
        method = str(v).strip().lower()
        if method not in ("card", "sbp"):
            raise ValueError("method must be card or sbp")
        return method

    @field_validator("requisites", "bank", "holder_name")
    @classmethod
    def _optional_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        text = str(v).strip()
        return text or None


def _unparsed_requisites_error(
    order_id: str,
    *,
    requisites: str,
    sub_token: str,
    message: str,
) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "code": "unparsed_requisites",
            "message": message,
            "requisites": requisites,
            "sub_token": sub_token,
            "order_id": order_id,
        },
    )


def _resolve_from_sell_bill(sell, body: FromSellBody | None, *, order_id: str) -> dict:
    raw_order = str(sell["requisites"] or "")
    sub_order = str(sell["sub_token"] or "")
    override = body or FromSellBody()
    raw = override.requisites if override.requisites else raw_order
    sub = sub_order
    if override.method == "card":
        sub = "CARDRUB"
    elif override.method == "sbp":
        sub = "SBPRUB"
    try:
        bill = parse_sell_fiat_bill(raw, sub_token=sub)
    except ValueError as exc:
        raise _unparsed_requisites_error(
            order_id,
            requisites=raw,
            sub_token=sub,
            message=str(exc),
        ) from exc
    if override.bank:
        bill["bank"] = override.bank[:128]
    if override.holder_name:
        bill["holder_name"] = override.holder_name[:128]
    return bill


def _order_requisites_from_bill(bill: dict) -> str:
    parts = [str(bill.get("requisites") or "").strip()]
    bank = str(bill.get("bank") or "").strip()
    if bank and bank != "банк":
        parts.append(bank)
    return " ".join(p for p in parts if p)


async def ensure_triangle_from_sell(
    conn,
    order_id: str,
    op: dict,
    body: FromSellBody | None = None,
    *,
    idempotent: bool = False,
):
    """Создать payin-треугольник из SELL. При idempotent=True вернуть уже живой реквизит."""
    oid = str(order_id or "").strip()
    if not oid:
        raise HTTPException(status_code=400, detail="Нет заявки")
    deadline = datetime.now(timezone.utc) + timedelta(minutes=DEFAULT_WINDOW_MINUTES)
    sell = await conn.fetchrow(
        """
        SELECT order_id, direction, status, fiat_amount, crypto, sub_token,
               requisites, crypto_confirmed_at
        FROM orders WHERE order_id = $1 FOR UPDATE
        """,
        oid,
    )
    if not sell:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if str(sell["direction"] or "").lower() != "sell":
        raise HTTPException(status_code=400, detail="Только продажа")
    if sell["crypto_confirmed_at"] is None:
        raise HTTPException(
            status_code=409,
            detail="Сначала подтвердите приход крипты в Заявках",
        )
    if str(sell["status"] or "") not in CANDIDATE_ORDER_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Заявка уже «{sell['status']}»",
        )
    live_id = await conn.fetchval(
        """
        SELECT id FROM operator_payout_requisites
        WHERE source_sell_order_id = $1
          AND status = ANY($2::text[])
        LIMIT 1
        """,
        oid,
        list(LIST_REQUISITE_STATUSES),
    )
    if live_id:
        if idempotent:
            row = await conn.fetchrow(
                f"SELECT {REQUISITE_COLUMNS} FROM operator_payout_requisites WHERE id = $1",
                int(live_id),
            )
            plan, free = await plan_for_requisite(conn, row)
            return row, plan, free, False
        raise HTTPException(
            status_code=409,
            detail="Эта продажа уже стоит под оплату",
        )
    from runtime_settings import triangle_enabled, triangle_sell_bonus_pct

    if not triangle_enabled():
        raise HTTPException(status_code=409, detail="Треугольник выключен")
    bill = _resolve_from_sell_bill(sell, body, order_id=oid)
    crypto = str(sell["crypto"] or DEFAULT_CRYPTO).strip().lower() or DEFAULT_CRYPTO
    if crypto not in SUPPORTED_CRYPTO:
        crypto = DEFAULT_CRYPTO
    amount = Decimal(str(sell["fiat_amount"] or 0)).quantize(Decimal("0.01"))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма продажи должна быть больше нуля")
    client_due = amount
    bonus_pct = Decimal(str(triangle_sell_bonus_pct()))
    if bonus_pct > 0:
        amount = (amount * (Decimal("1") + bonus_pct / Decimal("100"))).quantize(Decimal("0.01"))
    from payin_requisite_rail import frozen_subsidy_cap_rub

    subsidy_cap = frozen_subsidy_cap_rub(amount)
    max_checks, doliv_limit = payin_stored_limits(amount)
    await conn.execute(
        """
        UPDATE orders
        SET requisites = $2,
            sub_token = COALESCE($3, sub_token),
            updated_at = now()
        WHERE order_id = $1
        """,
        oid,
        _order_requisites_from_bill(bill),
        METHOD_SUB_TOKENS.get(bill["method"]),
    )
    try:
        row = await conn.fetchrow(
            f"""
            INSERT INTO operator_payout_requisites (
                operator_id, label, direction, method, requisites, bank, holder_name,
                amount_rub, cost_pct, crypto, max_checks, doliv_limit_rub, status,
                deadline_at, confirmed_at, confirmed_by, client_due_rub, subsidy_cap_rub,
                source_sell_order_id
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, 0, $9, $10, $11, 'QUEUED',
                $12, NULL, NULL, $13, $14, $15
            )
            RETURNING {REQUISITE_COLUMNS}
            """,
            int(op["id"]),
            f"SELL {oid}",
            DIRECTION_PAYIN,
            bill["method"],
            bill["requisites"],
            bill["bank"],
            bill["holder_name"],
            amount,
            crypto,
            max_checks,
            doliv_limit,
            deadline,
            client_due,
            subsidy_cap,
            oid,
        )
    except Exception as exc:
        err = str(exc).lower()
        if "ux_payout_req_source_sell_live" in err or "unique" in err:
            if idempotent:
                row = await conn.fetchrow(
                    f"""
                    SELECT {REQUISITE_COLUMNS} FROM operator_payout_requisites
                    WHERE source_sell_order_id = $1
                      AND status = ANY($2::text[])
                    LIMIT 1
                    """,
                    oid,
                    list(LIST_REQUISITE_STATUSES),
                )
                if row:
                    plan, free = await plan_for_requisite(conn, row)
                    return row, plan, free, False
            raise HTTPException(
                status_code=409,
                detail="Эта продажа уже стоит под оплату",
            ) from exc
        raise
    if _payin_needs_queue_fix(row):
        row = await conn.fetchrow(
            f"""
            UPDATE operator_payout_requisites
            SET status = 'QUEUED',
                confirmed_at = NULL,
                confirmed_by = NULL,
                updated_at = now()
            WHERE id = $1
              AND COALESCE(direction, 'payout') = 'payin'
            RETURNING {REQUISITE_COLUMNS}
            """,
            int(row["id"]),
        )
    if has_permission(op, PERM_PAYOUT_REQUISITES_CONFIRM) and row is not None:
        opened = await conn.fetchrow(
            f"""
            UPDATE operator_payout_requisites
            SET status = 'OPEN',
                confirmed_at = now(),
                confirmed_by = $2,
                updated_at = now()
            WHERE id = $1 AND status = 'QUEUED'
            RETURNING {REQUISITE_COLUMNS}
            """,
            int(row["id"]),
            int(op["id"]),
        )
        if opened:
            row = opened
    plan, free = await plan_for_requisite(conn, row)
    await store_plan(conn, int(row["id"]), plan, free)
    return row, plan, free, True


@router.post("/payout-requisites")
async def create_payout_requisite(
    body: RequisiteCreateBody,
    op: dict = Depends(get_current_operator),
):
    op = await _require_payout_requisites(op)
    deadline = datetime.now(timezone.utc) + timedelta(minutes=body.window_minutes)
    # Payin never auto-opens — even if the operator has payout.requisites.confirm.
    initial_status = "QUEUED" if body.direction == DIRECTION_PAYIN else "OPEN"
    max_checks = int(body.max_checks)
    doliv_limit = int(body.doliv_limit_rub)
    if body.direction == DIRECTION_PAYIN:
        max_checks, doliv_limit = payin_stored_limits(
            body.amount_rub,
            max_checks=max_checks,
            doliv_limit_rub=doliv_limit,
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            INSERT INTO operator_payout_requisites (
                operator_id, label, direction, method, requisites, bank, holder_name,
                amount_rub, cost_pct, crypto, max_checks, doliv_limit_rub, status, deadline_at,
                confirmed_at, confirmed_by
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, NULL, NULL)
            RETURNING {REQUISITE_COLUMNS}
            """,
            int(op["id"]),
            (body.label or "").strip() or None,
            body.direction,
            body.method,
            body.requisites.strip(),
            (body.bank or "").strip() or None,
            (body.holder_name or "").strip() or None,
            body.amount_rub,
            body.cost_pct,
            body.crypto,
            max_checks,
            doliv_limit,
            initial_status,
            deadline,
        )
        if _payin_needs_queue_fix(row):
            row = await conn.fetchrow(
                f"""
                UPDATE operator_payout_requisites
                SET status = 'QUEUED',
                    confirmed_at = NULL,
                    confirmed_by = NULL,
                    updated_at = now()
                WHERE id = $1
                  AND COALESCE(direction, 'payout') = 'payin'
                RETURNING {REQUISITE_COLUMNS}
                """,
                int(row["id"]),
            )
        plan, free = await plan_for_requisite(conn, row)
        await store_plan(conn, int(row["id"]), plan, free)
    payload = _requisite_out(row, reveal=True)
    payload["plan"] = plan.as_dict() if plan else None
    return {"requisite": payload}


@router.post("/payout-requisites/from-sell/{order_id}")
async def create_payin_from_sell(
    order_id: str,
    op: dict = Depends(get_current_operator),
    body: FromSellBody | None = None,
):
    """Карта продавца под BUY. С правом confirm сразу в приём, иначе в очередь."""
    op = await _require_payout_requisites(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row, plan, free, _created = await ensure_triangle_from_sell(
                conn, order_id, op, body, idempotent=False
            )
    payload = _requisite_out(row, reveal=True)
    payload["plan"] = plan.as_dict() if plan else None
    if payload["plan"] is not None:
        payload["plan"]["free_rub"] = float(free)
    return {"requisite": payload}


@router.get("/payout-requisites/quote")
async def quote_payout_requisite_payoff(
    op: dict = Depends(get_current_operator),
    amount_rub: Annotated[Decimal, Query(gt=0, le=Decimal("100000000"))] = Decimal("0"),
    cost_pct: Annotated[Decimal, Query(ge=-100, le=100)] = Decimal("0"),
    crypto: Annotated[str, Query()] = DEFAULT_CRYPTO,
    direction: Annotated[str, Query()] = DIRECTION_PAYOUT,
):
    """Калькулятор оператора: рубли + процент → сколько крипты нам должны прислать (payin)."""
    await _require_payout_requisites(op)
    coin = (crypto or "").strip().lower() or DEFAULT_CRYPTO
    if coin not in SUPPORTED_CRYPTO:
        raise HTTPException(status_code=400, detail="Монета не поддерживается")
    rail = (direction or "").strip().lower() or DIRECTION_PAYOUT
    if rail not in (DIRECTION_PAYOUT, DIRECTION_PAYIN):
        raise HTTPException(status_code=400, detail="direction must be payout or payin")

    rates = await get_need_rates_cached()
    rate = float(rates.get(coin) or 0)
    if rate <= 0:
        raise HTTPException(status_code=503, detail="Курс CoinGecko недоступен, повторите позже")

    total_rub = payoff_rub(amount_rub, cost_pct, rail)
    return {
        "amount_rub": float(Decimal(str(amount_rub)).quantize(Decimal("0.01"))),
        "cost_pct": float(cost_pct),
        "cost_rub": float(cost_rub(amount_rub, cost_pct)),
        "payoff_rub": float(total_rub),
        "crypto": coin,
        "rate_rub": rate,
        "crypto_amount": float(payoff_crypto(total_rub, rate, coin)),
        "rate_source": "coingecko",
        "direction": rail,
    }


@router.get("/payout-requisites")
async def list_payout_requisites(
    op: dict = Depends(get_current_operator),
    include_closed: Annotated[bool, Query()] = False,
):
    op = await _require_payout_requisites(op)
    op_id = int(op["id"])
    status_filter = "" if include_closed else "WHERE r.status = ANY($1::text[])"
    args: list = [] if include_closed else [list(LIST_REQUISITE_STATUSES)]
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {REQUISITE_COLUMNS_PREFIXED},
                   oa.display_name AS operator_display_name,
                   oa.username AS operator_username
            FROM operator_payout_requisites r
            LEFT JOIN operator_accounts oa ON oa.id = r.operator_id
            {status_filter}
            ORDER BY r.deadline_at ASC, r.id DESC
            LIMIT 100
            """,
            *args,
        )
        mine, team = [], []
        for row in rows:
            data = await _attach_check_stats(conn, dict(row))
            owned = int(row["operator_id"]) == op_id
            payload = _requisite_out(data, reveal=owned)
            payload["operator_display_name"] = data.get("operator_display_name") or data.get(
                "operator_username"
            )
            payload["is_mine"] = owned
            payload["plan"] = await _plan_for_owned(conn, data, owned=owned)
            if owned and str(data.get("direction") or "") == DIRECTION_PAYIN:
                payload["allocations"] = [
                    _allocation_out(a, reveal_order=True)
                    for a in await _allocations(conn, int(data["id"]))
                ]
            (mine if owned else team).append(payload)
        pool_orders = [pool_order_payload(c) for c in await load_pool_orders(conn)]
        from payin_requisite_rail import missing_triangle_label

        waiting = await conn.fetch(
            """
            SELECT w.id, w.method, w.requisites,
                   EXISTS (
                       SELECT 1 FROM operator_payout_requisites gr
                       WHERE gr.source_withdrawal_id = w.id AND gr.close_note = 'выплатить вручную'
                   ) AS triangle_gave_up
            FROM user_referral_withdrawals w
            WHERE w.status = 'pending'
              AND lower(w.method) = 'card'
              AND NOT EXISTS (
                  SELECT 1 FROM operator_payout_requisites r
                  WHERE r.source_withdrawal_id = w.id
                    AND r.status = ANY($1::text[])
              )
            ORDER BY w.id
            LIMIT 20
            """,
            ["QUEUED", "OPEN", "RESERVED", "PARTIAL"],
        )
        unopened = []
        for row in waiting:
            label = missing_triangle_label(dict(row))
            if not label:
                continue
            unopened.append({"id": int(row["id"]), "triangle_label": label})
    return {
        "mine": mine,
        "team": team,
        "pool_orders": pool_orders,
        "unopened_withdrawals": unopened,
    }


@router.get("/payout-requisites/{requisite_id}")
async def get_payout_requisite(
    requisite_id: int,
    op: dict = Depends(get_current_operator),
):
    op = await _require_payout_requisites(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _load_requisite(conn, requisite_id)
        owned = int(row["operator_id"]) == int(op["id"])
        data = await _attach_check_stats(conn, dict(row))
        allocations = await _allocations(conn, requisite_id)
        plan = await _plan_for_owned(conn, data, owned=owned)
    payload = _requisite_out(data, reveal=owned)
    payload["is_mine"] = owned
    payload["allocations"] = [_allocation_out(a, reveal_order=owned) for a in allocations]
    payload["plan"] = plan
    if owned and data.get("direction") == "payin":
        from payin_diagnostics import diagnose

        try:
            async with pool.acquire() as conn:
                payload["diagnostics"] = await diagnose(conn, data)
        except Exception:
            logger.warning("Payin diagnostics unavailable requisite=%s", requisite_id, exc_info=True)
            payload["diagnostics"] = {"unavailable": True}
    return {"requisite": payload}


class MaxChecksBody(BaseModel):
    max_checks: int = Field(..., ge=1, le=5)


@router.post("/payout-requisites/{requisite_id}/max-checks")
async def update_payout_requisite_max_checks(
    requisite_id: int,
    body: MaxChecksBody,
    op: dict = Depends(get_current_operator),
):
    """Снизить/поднять max чеков на живой карте (не ниже уже использованных)."""
    op = await _require_payout_requisites(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await _load_requisite(conn, requisite_id, for_update=True)
            _require_owner(row, op)
            if row["status"] not in (*LIST_REQUISITE_STATUSES, "QUEUED"):
                raise HTTPException(
                    status_code=409,
                    detail=f"Реквизит уже «{row['status']}»",
                )
            used = int(
                await conn.fetchval(
                    """
                    SELECT COUNT(*)::int
                    FROM payout_requisite_allocations
                    WHERE requisite_id = $1 AND status = ANY($2::text[])
                    """,
                    int(requisite_id),
                    list(ACTIVE_ALLOCATION_STATUSES),
                )
                or 0
            )
            if int(body.max_checks) < used:
                raise HTTPException(
                    status_code=400,
                    detail=f"Уже использовано {used} чек(а), меньше нельзя",
                )
            updated = await conn.fetchrow(
                f"""
                UPDATE operator_payout_requisites
                SET max_checks = $2, updated_at = now()
                WHERE id = $1
                RETURNING {REQUISITE_COLUMNS}
                """,
                int(requisite_id),
                int(body.max_checks),
            )
            data = await _attach_check_stats(conn, dict(updated))
            plan, free = await plan_for_requisite(conn, updated)
            await store_plan(conn, int(updated["id"]), plan, free)
    payload = _requisite_out(data, reveal=True)
    payload["is_mine"] = True
    payload["plan"] = plan.as_dict() if plan else None
    if payload["plan"] is not None:
        payload["plan"]["free_rub"] = float(free)
    return {"requisite": payload}


@router.post("/payout-requisites/{requisite_id}/confirm")
async def confirm_payout_requisite(
    requisite_id: int,
    op: dict = Depends(get_current_operator),
):
    """Выпустить пейин-карту из очереди в пул (OPEN)."""
    op = await _require_payout_requisites_confirm(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await _load_requisite(conn, requisite_id, for_update=True)
            if str(row.get("direction") or DIRECTION_PAYOUT) != DIRECTION_PAYIN:
                raise HTTPException(
                    status_code=400,
                    detail="Подтверждение в пул только для реквизита на приём",
                )
            if row["status"] in ACTIVE_REQUISITE_STATUSES:
                payload = _requisite_out(row, reveal=True)
                payload["is_mine"] = int(row["operator_id"]) == int(op["id"])
                return {"requisite": payload, "already_confirmed": True}
            if row["status"] != "QUEUED":
                raise HTTPException(
                    status_code=409,
                    detail=f"Реквизит уже «{row['status']}»",
                )
            updated = await conn.fetchrow(
                f"""
                UPDATE operator_payout_requisites
                SET status = 'OPEN',
                    confirmed_at = now(),
                    confirmed_by = $2,
                    updated_at = now()
                WHERE id = $1 AND status = 'QUEUED'
                RETURNING {REQUISITE_COLUMNS}
                """,
                int(requisite_id),
                int(op["id"]),
            )
            if not updated:
                raise HTTPException(status_code=409, detail="Реквизит уже обработан")
            plan, free = await plan_for_requisite(conn, updated)
            await store_plan(conn, int(updated["id"]), plan, free)
    payload = _requisite_out(updated, reveal=True)
    payload["is_mine"] = int(updated["operator_id"]) == int(op["id"])
    payload["plan"] = plan.as_dict() if plan else None
    if payload["plan"] is not None:
        payload["plan"]["free_rub"] = float(free)
    return {"requisite": payload, "already_confirmed": False}


@router.get("/payout-requisites/{requisite_id}/plan")
async def get_payout_requisite_plan(
    requisite_id: int,
    op: dict = Depends(get_current_operator),
    refresh: Annotated[bool, Query()] = False,
):
    op = await _require_payout_requisites(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _load_requisite(conn, requisite_id)
        _require_owner(row, op)
        if row["direction"] == "payin":
            from payin_diagnostics import diagnose

            data = await _attach_check_stats(conn, dict(row))
            return {"plan": {"kind": "diagnostics", "diagnostics": await diagnose(conn, data)}}
        if not refresh:
            cached = await latest_plan(conn, requisite_id)
            if _cached_plan_usable(cached, row):
                return {"plan": cached}
        if row["status"] not in LIST_REQUISITE_STATUSES:
            raise HTTPException(status_code=409, detail=f"Реквизит уже «{row['status']}»")
        plan, free = await plan_for_requisite(conn, row)
        await store_plan(conn, requisite_id, plan, free)
    payload = plan.as_dict() if plan else {"orders": [], "closes": False}
    payload["free_rub"] = float(free)
    return {"plan": payload}


# ---------------------------------------------------------------------------
# Бронирование плана
# ---------------------------------------------------------------------------


class ReserveBody(BaseModel):
    order_ids: Optional[list[str]] = None


@router.post("/payout-requisites/{requisite_id}/reserve")
async def reserve_payout_requisite(
    requisite_id: int,
    body: ReserveBody,
    op: dict = Depends(get_current_operator),
):
    from routers.operator import _require_active_shift

    op = await _require_payout_requisites(op)
    op_id = int(op["id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_active_shift(conn, op_id)
            row = await _load_requisite(conn, requisite_id, for_update=True)
            _require_owner(row, op)
            _require_active(row)
            if str(row.get("direction") or DIRECTION_PAYOUT).lower() == DIRECTION_PAYIN:
                raise HTTPException(
                    status_code=400,
                    detail="Пейин-реквизит бронируется автоматически под BUY-заявку",
                )
            if row["deadline_at"] and row["deadline_at"] <= datetime.now(timezone.utc):
                raise HTTPException(status_code=409, detail="Окно анализа реквизита истекло")

            order_ids = [str(o).strip() for o in (body.order_ids or []) if str(o).strip()]
            if not order_ids:
                cached = await latest_plan(conn, requisite_id)
                order_ids = [
                    str(item["order_id"])
                    for item in ((cached or {}).get("orders") or [])
                    if item.get("order_id")
                ]
            if not order_ids:
                raise HTTPException(status_code=400, detail="Нет заявок для брони")
            if len(order_ids) != len(set(order_ids)):
                raise HTTPException(status_code=400, detail="Заявки в плане дублируются")
            if len(order_ids) > int(row["max_checks"] or DEFAULT_MAX_CHECKS):
                raise HTTPException(
                    status_code=400,
                    detail=f"Больше {row['max_checks']} чеков на этот реквизит нельзя",
                )

            free_kop = to_kop(remaining_rub(row)) - await reserved_kop(conn, requisite_id)
            sub_token = METHOD_SUB_TOKENS[str(row["method"]).lower()]
            created = []
            total_kop = 0
            for order_id in order_ids:
                order = await conn.fetchrow(
                    """
                    SELECT order_id, direction, status, fiat_amount, sub_token,
                           operator_id, finance_operator_id
                    FROM orders WHERE order_id = $1 FOR UPDATE
                    """,
                    order_id,
                )
                if not order:
                    raise HTTPException(status_code=404, detail=f"Заявка {order_id} не найдена")
                if str(order["direction"] or "").lower() != "sell":
                    raise HTTPException(
                        status_code=400, detail=f"Заявка {order_id} не SELL"
                    )
                if order["status"] not in CANDIDATE_ORDER_STATUSES:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Заявка {order_id}: статус «{order['status']}»",
                    )
                if order["sub_token"] and str(order["sub_token"]).upper() != sub_token:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Заявка {order_id} не под {row['method']}",
                    )
                amount_kop = to_kop(order["fiat_amount"])
                total_kop += amount_kop
                if total_kop > free_kop:
                    raise HTTPException(
                        status_code=409,
                        detail="Сумма плана больше свободного остатка реквизита",
                    )
                claimed = await conn.fetchrow(
                    """
                    UPDATE orders
                    SET operator_id = COALESCE(operator_id, $2),
                        finance_operator_id = COALESCE(finance_operator_id, $2),
                        updated_at = now()
                    WHERE order_id = $1
                      AND (operator_id IS NULL OR operator_id = $2)
                      AND (finance_operator_id IS NULL OR finance_operator_id = $2)
                    RETURNING order_id
                    """,
                    order_id,
                    op_id,
                )
                if not claimed:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Заявка {order_id} уже у другого оператора",
                    )
                alloc = await conn.fetchrow(
                    """
                    INSERT INTO payout_requisite_allocations
                        (requisite_id, order_id, kind, amount_rub, status, operator_id)
                    VALUES ($1, $2, 'order', $3, 'RESERVED', $4)
                    RETURNING id, requisite_id, order_id, kind, amount_rub, status,
                              receipt_file, paid_at, note, created_at, client_confirmed_at
                    """,
                    int(requisite_id),
                    order_id,
                    Decimal(str(order["fiat_amount"])),
                    op_id,
                )
                created.append(alloc)

            await conn.execute(
                """
                UPDATE payout_requisite_plans SET is_applied = TRUE
                WHERE id = (
                    SELECT id FROM payout_requisite_plans
                    WHERE requisite_id = $1
                    ORDER BY computed_at DESC, id DESC
                    LIMIT 1
                )
                """,
                int(requisite_id),
            )
            await _refresh_status(conn, requisite_id)
            fresh = await _load_requisite(conn, requisite_id)

    return {
        "requisite": _requisite_out(fresh, reveal=True),
        "allocations": [_allocation_out(a, reveal_order=True) for a in created],
    }


@router.post("/payout-requisites/{requisite_id}/allocations/{allocation_id}/cancel")
async def cancel_allocation(
    requisite_id: int,
    allocation_id: int,
    op: dict = Depends(get_current_operator),
):
    op = await _require_payout_requisites(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await _load_requisite(conn, requisite_id, for_update=True)
            _require_owner(row, op)
            alloc = await conn.fetchrow(
                """
                UPDATE payout_requisite_allocations
                SET status = 'CANCELED', updated_at = now()
                WHERE id = $1 AND requisite_id = $2 AND status = 'RESERVED'
                RETURNING id, requisite_id, order_id, kind, amount_rub, status,
                          receipt_file, paid_at, note, created_at, client_confirmed_at
                """,
                int(allocation_id),
                int(requisite_id),
            )
            if not alloc:
                raise HTTPException(status_code=409, detail="Бронь не найдена или уже закрыта")
            if alloc["order_id"]:
                await conn.execute(
                    """
                    UPDATE orders
                    SET operator_id = NULL, finance_operator_id = NULL, updated_at = now()
                    WHERE order_id = $1
                      AND status = ANY($2::text[])
                      AND operator_id = $3
                    """,
                    alloc["order_id"],
                    list(CANDIDATE_ORDER_STATUSES),
                    int(op["id"]),
                )
            await _refresh_status(conn, requisite_id)
            fresh = await _load_requisite(conn, requisite_id)
    return {
        "requisite": _requisite_out(fresh, reveal=True),
        "allocation": _allocation_out(alloc, reveal_order=True),
    }


# ---------------------------------------------------------------------------
# Закрытие чеков
# ---------------------------------------------------------------------------


class AllocationPaidBody(BaseModel):
    crypto_received: Optional[float] = None
    fiat_paid_out: Optional[float] = None


@router.post("/payout-requisites/{requisite_id}/allocations/{allocation_id}/paid")
async def mark_allocation_paid(
    requisite_id: int,
    allocation_id: int,
    op: dict = Depends(get_current_operator),
    file: Annotated[UploadFile | None, File()] = None,
    crypto_received: Annotated[Optional[float], Form()] = None,
    fiat_paid_out: Annotated[Optional[float], Form()] = None,
):
    op = await _require_payout_requisites(op)
    if file is None:
        raise HTTPException(status_code=400, detail="Приложите PDF или фото чека")
    receipt_name = save_doliv_receipt(await file.read(), file.content_type, file.filename)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _load_requisite(conn, requisite_id)
        _require_owner(row, op)
        alloc = await conn.fetchrow(
            """
            SELECT id, requisite_id, order_id, kind, amount_rub, status
            FROM payout_requisite_allocations
            WHERE id = $1 AND requisite_id = $2
            """,
            int(allocation_id),
            int(requisite_id),
        )
        if not alloc or alloc["status"] != "RESERVED" or alloc["kind"] != "order":
            raise HTTPException(status_code=409, detail="Бронь по заявке не найдена")
        order = await conn.fetchrow(
            """
            SELECT order_id, user_id, crypto, crypto_amount, fiat_amount, direction, status
            FROM orders WHERE order_id = $1
            """,
            alloc["order_id"],
        )
        if not order:
            raise HTTPException(status_code=404, detail="Заявка не найдена")

    received = crypto_received or float(order["crypto_amount"] or 0)
    if received <= 0:
        raise HTTPException(status_code=400, detail="Укажите полученную крипту")
    # fiat_paid_out / crypto_received больше не закрывают заявку — PAID после
    # подтверждения клиента. Суммы берутся с заявки и брони.

    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await conn.fetchrow(
                """
                UPDATE payout_requisite_allocations
                SET status = 'PAID',
                    paid_at = now(),
                    receipt_file = $2,
                    client_confirmed_at = NULL,
                    updated_at = now()
                WHERE id = $1 AND status = 'RESERVED'
                RETURNING id, requisite_id, order_id, kind, amount_rub, status,
                          receipt_file, paid_at, note, created_at, client_confirmed_at
                """,
                int(allocation_id),
                receipt_name,
            )
            if not updated:
                logger.error(
                    "payout requisite alloc=%s order=%s paid but reservation vanished",
                    allocation_id,
                    alloc["order_id"],
                )
                raise HTTPException(status_code=409, detail="Бронь изменилась, проверьте вручную")
            await conn.execute(
                """
                UPDATE operator_payout_requisites
                SET paid_rub = LEAST(paid_rub + $2, amount_rub), updated_at = now()
                WHERE id = $1
                """,
                int(requisite_id),
                Decimal(str(alloc["amount_rub"])),
            )
            await _refresh_status(conn, requisite_id)
            fresh = await _load_requisite(conn, requisite_id)
            plan, free = await plan_for_requisite(conn, fresh)
            await store_plan(conn, requisite_id, plan, free)

    notify_order = dict(order)
    notify_order.setdefault("user_id", order["user_id"])
    notify_order.setdefault("order_id", order["order_id"])
    notify_order.setdefault("crypto", order["crypto"])
    notify_order.setdefault("crypto_amount", order["crypto_amount"])
    notify_order.setdefault("fiat_amount", order["fiat_amount"])
    await _deliver_payout_receipt(notify_order, receipt_name, fallback_text=True)

    from routers.operator import _order_out

    order_out = dict(order)
    order_out["payout_alloc_status"] = "PAID"
    order_out["payout_receipt_file"] = receipt_name
    order_out["payout_client_confirmed_at"] = None
    order_out["payout_alloc_amount_rub"] = alloc["amount_rub"]
    order_out["payout_requisite_id"] = int(requisite_id)
    return {
        "requisite": _requisite_out(fresh, reveal=True),
        "allocation": _allocation_out(updated, reveal_order=True),
        "order": _order_out(order_out),
    }


@router.post("/payout-requisites/{requisite_id}/allocations/{allocation_id}/receipt")
async def attach_allocation_receipt(
    requisite_id: int,
    allocation_id: int,
    file: Annotated[UploadFile, File()],
    op: dict = Depends(get_current_operator),
):
    """Чек о выплате по чеку заявки — клиент увидит его на своей SELL-заявке."""
    op = await _require_payout_requisites(op)
    receipt_name = save_doliv_receipt(await file.read(), file.content_type, file.filename)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _load_requisite(conn, requisite_id)
        _require_owner(row, op)
        updated = await conn.fetchrow(
            """
            UPDATE payout_requisite_allocations
            SET receipt_file = $3, client_confirmed_at = NULL, updated_at = now()
            WHERE id = $1 AND requisite_id = $2 AND status = 'PAID' AND kind = 'order'
            RETURNING id, requisite_id, order_id, kind, amount_rub, status,
                      receipt_file, paid_at, note, created_at, client_confirmed_at
            """,
            int(allocation_id),
            int(requisite_id),
            receipt_name,
        )
        order = None
        if updated and updated["order_id"]:
            order = await conn.fetchrow(
                """
                SELECT order_id, user_id, crypto, crypto_amount, fiat_amount
                FROM orders WHERE order_id = $1
                """,
                updated["order_id"],
            )
    if not updated:
        raise HTTPException(status_code=409, detail="Оплаченный чек не найден")
    if order:
        await _deliver_payout_receipt(dict(order), receipt_name, fallback_text=False)
    return {"allocation": _allocation_out(updated, reveal_order=True)}


@router.post("/payout-requisites/{requisite_id}/doliv")
async def add_doliv(
    requisite_id: int,
    amount_rub: Annotated[Decimal, Form()],
    op: dict = Depends(get_current_operator),
    note: Annotated[Optional[str], Form()] = None,
    file: Annotated[Optional[UploadFile], File()] = None,
):
    from routers.operator import _require_active_shift

    op = await _require_payout_requisites(op)
    if amount_rub <= 0:
        raise HTTPException(status_code=400, detail="Сумма долива должна быть больше нуля")

    receipt_name: str | None = None
    if file is not None:
        receipt_name = save_doliv_receipt(await file.read(), file.content_type, file.filename)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_active_shift(conn, int(op["id"]))
            row = await _load_requisite(conn, requisite_id, for_update=True)
            _require_owner(row, op)
            _require_active(row)
            if str(row.get("direction") or DIRECTION_PAYOUT).lower() == DIRECTION_PAYIN:
                if not is_triangle_row(row):
                    raise HTTPException(
                        status_code=400,
                        detail="Долив только для реквизитов выплаты или треугольника",
                    )
                if payin_one_check_only(row.get("amount_rub")):
                    raise HTTPException(
                        status_code=400,
                        detail="Сумма до 2000 ₽ закрывается одним чеком, без долива",
                    )
            limit_kop = to_kop(row["doliv_limit_rub"] or 0)
            amount_kop = to_kop(amount_rub)
            if limit_kop and amount_kop > limit_kop:
                raise HTTPException(
                    status_code=400,
                    detail=f"Долив больше лимита {int(row['doliv_limit_rub'])} ₽",
                )
            free_kop = to_kop(remaining_rub(row)) - await reserved_kop(conn, requisite_id)
            if amount_kop > free_kop:
                raise HTTPException(
                    status_code=409, detail="Долив больше свободного остатка реквизита"
                )
            sell_bind = (
                str(row.get("source_sell_order_id") or "").strip() or None
                if is_triangle_row(row)
                else None
            )
            alloc = await conn.fetchrow(
                """
                INSERT INTO payout_requisite_allocations
                    (requisite_id, order_id, kind, amount_rub, status,
                     receipt_file, paid_at, operator_id, note)
                VALUES ($1, $2, 'doliv', $3, 'PAID', $4, now(), $5, $6)
                RETURNING id, requisite_id, order_id, kind, amount_rub, status,
                          receipt_file, paid_at, note, created_at, client_confirmed_at
                """,
                int(requisite_id),
                sell_bind,
                amount_rub,
                receipt_name,
                int(op["id"]),
                (note or "").strip() or None,
            )
            await conn.execute(
                """
                UPDATE operator_payout_requisites
                SET paid_rub = LEAST(paid_rub + $2, amount_rub), updated_at = now()
                WHERE id = $1
                """,
                int(requisite_id),
                amount_rub,
            )
            await _refresh_status(conn, requisite_id)
            fresh = await _load_requisite(conn, requisite_id)
    fresh_dict = dict(fresh)
    if is_triangle_row(fresh_dict):
        sell_id = str(fresh_dict.get("source_sell_order_id") or "")
        if sell_id and receipt_name:
            async with pool.acquire() as conn:
                sell_order = await conn.fetchrow(
                    """
                    SELECT order_id, user_id, crypto, crypto_amount, fiat_amount
                    FROM orders WHERE order_id = $1
                    """,
                    sell_id,
                )
            if sell_order:
                await _deliver_payout_receipt(
                    dict(sell_order), receipt_name, fallback_text=True
                )
        if str(fresh_dict.get("status") or "") == "CLOSED":
            await complete_triangle_sell(fresh_dict, op)
            await complete_triangle_withdrawal(fresh_dict, op)
    return {
        "requisite": _requisite_out(fresh, reveal=True),
        "allocation": _allocation_out(alloc, reveal_order=True),
    }


@router.get("/payout-requisites/{requisite_id}/allocations/{allocation_id}/receipt")
async def get_doliv_receipt(
    requisite_id: int,
    allocation_id: int,
    op: dict = Depends(get_current_operator),
):
    op = await _require_payout_requisites(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        receipt = await conn.fetchval(
            """
            SELECT receipt_file FROM payout_requisite_allocations
            WHERE id = $1 AND requisite_id = $2
            """,
            int(allocation_id),
            int(requisite_id),
        )
    return doliv_receipt_response(receipt)


# ---------------------------------------------------------------------------
# Закрытие реквизита
# ---------------------------------------------------------------------------


class CloseBody(BaseModel):
    note: Optional[str] = Field(None, max_length=500)


async def _finish_requisite(
    requisite_id: int,
    op: dict,
    status: str,
    note: str | None,
    *,
    allow_queued: bool = False,
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await _load_requisite(conn, requisite_id, for_update=True)
            _require_owner(row, op)
            if row["status"] == "QUEUED":
                if not allow_queued:
                    raise HTTPException(
                        status_code=409,
                        detail="Сначала подтвердите реквизит в пул или снимите с очереди",
                    )
            else:
                _require_active(row)
            if status == "CANCELED" and row.get("source_withdrawal_id") not in (None, ""):
                from user_referral_withdraw import triangle_has_paid_check

                if await triangle_has_paid_check(conn, int(row["source_withdrawal_id"])):
                    raise HTTPException(
                        status_code=409,
                        detail="По карте уже есть оплата, снять её нельзя",
                    )
            released = await conn.fetch(
                """
                UPDATE payout_requisite_allocations
                SET status = 'CANCELED', updated_at = now()
                WHERE requisite_id = $1 AND status = 'RESERVED'
                RETURNING order_id
                """,
                int(requisite_id),
            )
            for rel in released:
                if rel["order_id"]:
                    await conn.execute(
                        """
                        UPDATE orders
                        SET operator_id = NULL, finance_operator_id = NULL, updated_at = now()
                        WHERE order_id = $1
                          AND status = ANY($2::text[])
                          AND operator_id = $3
                        """,
                        rel["order_id"],
                        list(CANDIDATE_ORDER_STATUSES),
                        int(op["id"]),
                    )
            fresh = await conn.fetchrow(
                f"""
                UPDATE operator_payout_requisites
                SET status = $2, closed_at = now(), close_note = $3, updated_at = now()
                WHERE id = $1
                RETURNING {REQUISITE_COLUMNS}
                """,
                int(requisite_id),
                status,
                (note or "").strip() or None,
            )
            await safe_post_requisite_cost(conn, fresh)
    if status == "CLOSED" and fresh is not None and is_triangle_row(fresh):
        await complete_triangle_sell(dict(fresh), op)
        await complete_triangle_withdrawal(dict(fresh), op)
    return {
        "requisite": _requisite_out(fresh, reveal=True),
        "released": len(released),
    }


@router.post("/payout-requisites/{requisite_id}/close")
async def close_payout_requisite(
    requisite_id: int,
    body: CloseBody,
    op: dict = Depends(get_current_operator),
):
    op = await _require_payout_requisites(op)
    return await _finish_requisite(requisite_id, op, "CLOSED", body.note)


@router.post("/payout-requisites/{requisite_id}/cancel")
async def cancel_payout_requisite(
    requisite_id: int,
    body: CloseBody,
    op: dict = Depends(get_current_operator),
):
    op = await _require_payout_requisites(op)
    return await _finish_requisite(requisite_id, op, "CANCELED", body.note, allow_queued=True)


__all__ = ["router", "ACTIVE_ALLOCATION_STATUSES"]
