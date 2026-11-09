"""
Кабинет оператора: управление сменами, создание и подтверждение ручных заявок.
"""

import json
import logging
import math
import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Literal, Optional

import asyncpg
from auth import require_operator_role
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field, field_validator, model_validator

import runtime_settings
from auth import get_current_operator, operator_public_dict
from commission import commission_percent
from config import settings
from db import get_pool
from economics_snapshot import build_economics_snapshot
from operator_earnings import utc_aware
from payroll_base import (
    order_completed_in_shift,
    order_in_shift,
    stats_for_operator_shift_conn,
    stats_from_orders_conn,
)
from finance_access import can_view_finance_operator, strip_operator_profit_fields
from hot_wallet_swap import SwapConfirmIn, SwapPreviewIn
from order_service import _validate_amounts
from order_source import normalize_order_source, order_source_label
from routers.public import get_need_rates_cached, get_rates_cached, get_sell_market_rates, rates_source
from admin_order_close import cancel_user_telegram_text as _cancel_user_text
from merchant_order_id import resolve_payfast_uuid_system
from user_cashback_db import (
    apply_cashback_with_conn,
    hold_cashback_for_order,
    should_use_cashback,
)

router = APIRouter()


def _role_grades_dict(value) -> dict[str, str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return dict(value) if isinstance(value, dict) else {}


logger = logging.getLogger("operator")

SUPPORTED_CRYPTOS = ("btc", "usdt", "trx", "ltc")
MANUAL_BUY_SPREAD_MIN = Decimal("14.00")
MANUAL_BUY_SPREAD_MAX = Decimal("25.00")


def _manual_buy_pricing(
    *,
    market_rate: float,
    fiat_amount: float | None,
    crypto_amount: float | None,
    spread_pct: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    market = Decimal(str(market_rate))
    rate = (market * (Decimal("1") + spread_pct / Decimal("100"))).quantize(
        Decimal("0.00000001"), rounding=ROUND_HALF_UP
    )
    if fiat_amount is not None and crypto_amount is None:
        fiat = Decimal(str(fiat_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        crypto = (fiat / rate).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    elif crypto_amount is not None and fiat_amount is None:
        crypto = Decimal(str(crypto_amount))
        fiat = (crypto * rate).quantize(Decimal("1"), rounding=ROUND_CEILING)
    elif fiat_amount is not None and crypto_amount is not None:
        fiat = Decimal(str(fiat_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        crypto = Decimal(str(crypto_amount))
    else:
        raise HTTPException(status_code=400, detail="Укажите сумму в рублях или в крипте")
    if fiat <= 0 or crypto <= 0:
        raise HTTPException(status_code=400, detail="Укажите сумму больше нуля")
    return crypto, fiat, rate


def _manual_buy_overpay(
    expected_fiat: float | Decimal,
    received_fiat: float | Decimal,
    spread_pct: Decimal,
) -> tuple[Decimal, Decimal]:
    expected = Decimal(str(expected_fiat)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    received = Decimal(str(received_fiat)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    overpay = max(Decimal("0"), received - expected)
    credit = (overpay * (Decimal("1") - spread_pct / Decimal("100"))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return overpay, credit


_ORDERS_WITH_BUYER_SQL = """
    SELECT o.*, bu.username AS buyer_username, bu.first_name AS buyer_first_name,
           oa.username AS operator_username, oa.display_name AS operator_display_name
    FROM orders o
    LEFT JOIN bot_users bu ON bu.user_id = o.user_id
    LEFT JOIN operator_accounts oa ON oa.id = o.operator_id
"""

_WITHDRAWALS_WITH_OPERATOR_SQL = """
    SELECT w.*, oa.username AS operator_username, oa.display_name AS operator_display_name,
           bu.username AS buyer_username, bu.first_name AS buyer_first_name,
           triangle_req.triangle_method, triangle_req.triangle_status,
           EXISTS (
               SELECT 1 FROM operator_payout_requisites gr
               WHERE gr.source_withdrawal_id = w.id AND gr.close_note = 'выплатить вручную'
           ) AS triangle_gave_up
    FROM user_referral_withdrawals w
    LEFT JOIN operator_accounts oa ON oa.id = w.operator_id
    LEFT JOIN bot_users bu ON bu.user_id = w.referrer_user_id
    LEFT JOIN LATERAL (
        SELECT r.method AS triangle_method, r.status AS triangle_status
        FROM operator_payout_requisites r
        WHERE r.source_withdrawal_id = w.id
          AND r.status IN ('QUEUED', 'OPEN', 'RESERVED', 'PARTIAL')
        ORDER BY r.id DESC
        LIMIT 1
    ) triangle_req ON true
"""
_BALANCE_WD_SQL = "COALESCE(w.source, 'balance') <> 'casino'"
_BALANCE_WD_BARE_SQL = "COALESCE(source, 'balance') <> 'casino'"

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


_LIVE_REQUISITE_STATUSES = ("CREATED", "PENDING", "AWAITING_CHECK")


def _payment_snapshot_dict(row: dict) -> dict:
    snap = row.get("payment_snapshot")
    if not snap:
        return {}
    if isinstance(snap, str):
        try:
            snap = json.loads(snap)
        except (TypeError, ValueError):
            return {}
    return snap if isinstance(snap, dict) else {}


def _payment_summary(row: dict) -> dict | None:
    snap = _payment_snapshot_dict(row)
    if not snap and not row.get("merchant_order_id"):
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
    if not parts and not merchant_uuid and not snap.get("pay_link"):
        return None
    return {
        "merchant_uuid": str(merchant_uuid) if merchant_uuid else None,
        "pay_link": snap.get("pay_link"),
        "summary": " · ".join(parts) if parts else None,
    }


def _can_send_receipt_to_payfast(row: dict) -> bool:
    if str(row.get("direction") or "").lower() != "buy":
        return False
    if str(row.get("status") or "").upper() != "AWAITING_CHECK":
        return False
    if not row.get("receipt_file"):
        return False
    if row.get("payin_requisite_id"):
        return False
    snap = _payment_snapshot_dict(row)
    if not snap.get("receipt_ops_pending"):
        return False
    try:
        req_type = int(row.get("required_receipt_type") or 2)
    except (TypeError, ValueError):
        req_type = 2
    if req_type == 3:
        return False
    return True


def _has_live_requisites(row: dict) -> bool:
    status = str(row.get("status") or "").upper()
    if status not in _LIVE_REQUISITE_STATUSES:
        return False
    if row.get("payin_requisite_id"):
        return True
    snap = _payment_snapshot_dict(row)
    bill = snap.get("bill") if isinstance(snap.get("bill"), dict) else {}
    merchant = (
        snap.get("merchant_uuid")
        or snap.get("uuid_system")
        or row.get("merchant_order_id")
    )
    return bool(bill or merchant)


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


def _payout_rail_out(row: dict) -> dict | None:
    if str(row.get("direction") or "").lower() != "sell":
        return None
    alloc_status = row.get("payout_alloc_status")
    receipt = row.get("payout_receipt_file")
    confirmed = row.get("payout_client_confirmed_at")
    crypto_at = row.get("crypto_confirmed_at")
    status = str(row.get("status") or "").upper()
    if status == "PAID" or confirmed:
        stage = "closed"
    elif str(alloc_status or "") == "PAID":
        stage = "paid_awaiting_client"
    elif str(alloc_status or "") == "RESERVED":
        stage = "reserved"
    elif crypto_at:
        stage = "awaiting_funding"
    else:
        stage = "awaiting_crypto"
    confirmed_at = confirmed
    if confirmed_at and hasattr(confirmed_at, "isoformat"):
        confirmed_at = confirmed_at.isoformat()
    req_id = row.get("payout_requisite_id")
    amount = row.get("payout_alloc_amount_rub")
    return {
        "stage": stage,
        "allocation_status": alloc_status,
        "has_receipt": bool(receipt),
        "client_confirmed": confirmed is not None,
        "client_confirmed_at": confirmed_at,
        "requisite_id": int(req_id) if req_id is not None else None,
        "amount_rub": float(amount) if amount is not None else None,
    }


_PAYOUT_RAIL_SQL = """
    SELECT DISTINCT ON (a.order_id)
           a.order_id,
           a.status AS payout_alloc_status,
           a.receipt_file AS payout_receipt_file,
           a.client_confirmed_at AS payout_client_confirmed_at,
           a.amount_rub AS payout_alloc_amount_rub,
           a.requisite_id AS payout_requisite_id
    FROM payout_requisite_allocations a
    WHERE a.order_id = ANY($1::text[])
      AND a.status = ANY($2::text[])
    ORDER BY a.order_id,
             CASE a.status WHEN 'PAID' THEN 0 ELSE 1 END,
             a.id DESC
"""


async def _fill_payout_rails(conn, rows: list[dict]) -> None:
    await _fill_wallet_confirms(conn, rows)
    ids = [
        str(r["order_id"])
        for r in rows
        if r.get("order_id") and str(r.get("direction") or "").lower() == "sell"
    ]
    if not ids:
        return
    try:
        allocs = await conn.fetch(_PAYOUT_RAIL_SQL, ids, ["RESERVED", "PAID"])
    except Exception as exc:
        name = type(exc).__name__
        if "UndefinedTable" in name or "UndefinedColumn" in name:
            logger.warning("payout rail schema missing; skip attach")
            return
        raise
    by_id = {a["order_id"]: a for a in allocs}
    for r in rows:
        a = by_id.get(r.get("order_id"))
        if not a:
            continue
        r["payout_alloc_status"] = a["payout_alloc_status"]
        r["payout_receipt_file"] = a["payout_receipt_file"]
        r["payout_client_confirmed_at"] = a["payout_client_confirmed_at"]
        r["payout_alloc_amount_rub"] = a["payout_alloc_amount_rub"]
        r["payout_requisite_id"] = a["payout_requisite_id"]


async def _fill_wallet_confirms(conn, rows: list[dict]) -> None:
    from payout_wallet_confirm import compute_wallet_grace_state, order_wallet_timer_active

    candidates = [r for r in rows if r.get("order_id") and order_wallet_timer_active(r)]
    if not candidates:
        return
    ids = list({str(r["order_id"]) for r in candidates})
    by_id: dict[str, dict] = {}
    try:
        confirms = await conn.fetch(
            """
            SELECT order_id, status, address, coin, asked_at, confirmed_at
            FROM payout_wallet_confirms
            WHERE order_id = ANY($1::text[])
            """,
            ids,
        )
        by_id = {str(c["order_id"]): dict(c) for c in confirms}
    except Exception as exc:
        name = type(exc).__name__
        if "UndefinedTable" not in name and "UndefinedColumn" not in name:
            logger.warning("wallet confirm schema fetch failed: %s", exc)
    for r in candidates:
        oid = str(r["order_id"])
        r["wallet_confirm_ops"] = compute_wallet_grace_state(r, by_id.get(oid))


def _has_video_receipt_file(row: dict) -> bool:
    name = str(row.get("receipt_file") or "").strip().lower()
    if "." not in name:
        return False
    return name.rsplit(".", 1)[-1] in {"mp4", "mov", "webm", "mkv", "avi"}


def _annotate_client_hold(row: dict) -> dict:
    """Почему заявка в блоке «Держат клиента» — для быстрой кнопки Закрыть."""
    out = dict(row)
    replaced = str(out.get("replaced_by_order_id") or "").strip() or None
    out["replaced_by_order_id"] = replaced
    status = str(out.get("status") or "").upper()
    req = int(out.get("required_receipt_type") or 0)
    if replaced:
        out["hold_reason"] = "replaced_by_operator"
        out["hold_reason_label"] = f"Есть новая заявка {replaced}"
    elif req == 3 and status == "AWAITING_CHECK":
        out["hold_reason"] = "video_hold"
        out["hold_reason_label"] = (
            "Видео у Payfast, ждём подтверждение"
            if _has_video_receipt_file(out)
            else "Ждёт видео"
        )
    elif status == "AWAITING_CHECK":
        out["hold_reason"] = "awaiting_check"
        out["hold_reason_label"] = "Ждёт чек, блокирует обмен"
    elif status == "CREATED":
        out["hold_reason"] = "expired_created"
        out["hold_reason_label"] = "Таймер вышел, клиент заблокирован"
    else:
        out["hold_reason"] = "blocks_client"
        out["hold_reason_label"] = "Блокирует новый обмен"
    return out


def _order_out(row: dict, *, current_operator_id: int | None = None) -> dict:
    from bot_user_avatars import bot_user_avatar_public_url

    r = dict(row)
    rail = _payout_rail_out(r)
    for key in (
        "payout_alloc_status",
        "payout_receipt_file",
        "payout_client_confirmed_at",
        "payout_alloc_amount_rub",
        "payout_requisite_id",
    ):
        r.pop(key, None)
    for key in ("created_at", "updated_at", "expires_at", "crypto_confirmed_at"):
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
    source = normalize_order_source(r.get("order_source"))
    r["order_source"] = source
    r["source_label"] = order_source_label(source)
    r["payment_summary"] = _payment_summary(r)
    r["has_receipt"] = bool(r.get("receipt_file"))
    snap = _payment_snapshot_dict(r)
    r["receipt_ops_pending"] = bool(snap.get("receipt_ops_pending"))
    payfast_id = None
    summary = r.get("payment_summary")
    if isinstance(summary, dict) and summary.get("merchant_uuid"):
        payfast_id = str(summary.get("merchant_uuid") or "").strip() or None
    r["payfast_id"] = payfast_id
    r["can_send_receipt_to_payfast"] = _can_send_receipt_to_payfast(r)
    r["live_requisites"] = _has_live_requisites(r)
    req_type = r.get("required_receipt_type")
    try:
        r["required_receipt_type"] = int(req_type) if req_type not in (None, "") else None
    except (TypeError, ValueError):
        r["required_receipt_type"] = None
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
    r["payout_rail"] = rail
    return r


async def _withdrawal_market_rates() -> dict:
    try:
        return await get_rates_cached() or {}
    except Exception:
        logger.debug("withdrawal market rates unavailable", exc_info=True)
        return {}


def _withdrawal_out(
    row: dict,
    *,
    current_operator_id: int | None = None,
    rates: dict | None = None,
) -> dict:
    from crypto_network_fee import quote_withdraw_crypto
    from user_referral_withdraw import player_status_fields, withdrawal_out

    r = withdrawal_out(dict(row))
    r.update(player_status_fields(row))
    r["assigned_operator"] = _assigned_operator_from_row(row)
    if current_operator_id is not None and row.get("operator_id") is not None:
        r["assigned_to_me"] = int(row["operator_id"]) == current_operator_id
    uid = r.get("user_id") or r.get("referrer_user_id")
    if uid is not None:
        r["user_id"] = int(uid)
    raw_uname = r.get("buyer_username") or r.get("player_username")
    if raw_uname:
        uname = str(raw_uname)
        r["buyer_username"] = uname if uname.startswith("@") else f"@{uname}"
    if r.get("buyer_first_name") is None and r.get("player_first_name"):
        r["buyer_first_name"] = r.get("player_first_name")
    r.update(
        quote_withdraw_crypto(
            method=r.get("method"),
            crypto=r.get("crypto"),
            amount_rub=r.get("amount_rub"),
            payout_amount_rub=r.get("payout_amount_rub"),
            network_fee_rub=r.get("network_fee_rub"),
            rates=rates,
        )
    )
    if "triangle_status" in r or "triangle_method" in r:
        from payin_requisite_rail import live_triangle_label, missing_triangle_label

        label = live_triangle_label(r.get("triangle_method"), r.get("triangle_status"))
        if label is None:
            label = missing_triangle_label(r)
        if label:
            r["triangle_label"] = label
        r.pop("triangle_status", None)
        r.pop("triangle_method", None)
        r.pop("triangle_gave_up", None)
    return r


def _withdrawals_out(
    rows,
    *,
    current_operator_id: int | None,
    rates: dict | None = None,
) -> list[dict]:
    return [
        _withdrawal_out(dict(r), current_operator_id=current_operator_id, rates=rates)
        for r in rows
    ]


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
# Статусы, из‑за которых бот не даёт клиенту создать новый обмен.
CLIENT_HOLD_STATUSES = (
    "CREATED",
    "AWAITING_CHECK",
    "PENDING",
    "COMPLETED",
    "OPERATOR_PENDING",
)
CLOSE_CLIENT_HOLD_REASON = "Снята блокировка обмена"

_CLIENT_HOLD_WHERE = """
    o.direction = 'buy'
    AND o.status = ANY($1::text[])
    AND (
      (o.status = 'AWAITING_CHECK' AND o.operator_id IS NULL)
      OR (
        o.status = 'CREATED'
        AND o.operator_id IS NULL
        AND o.expires_at <= now()
      )
      OR EXISTS (
        SELECT 1 FROM orders p
        WHERE p.user_id = o.user_id
          AND p.order_id <> o.order_id
          AND COALESCE(p.order_source, '') IN ('manual', 'manual_operator')
          AND p.created_at >= o.created_at
          AND p.status IN ('OPERATOR_PENDING', 'COMPLETED', 'PAID', 'PENDING')
      )
    )
"""

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
    client_holds = int(
        await conn.fetchval(
            f"SELECT COUNT(*) FROM orders o WHERE {_CLIENT_HOLD_WHERE}",
            list(CLIENT_HOLD_STATUSES),
        )
        or 0
    )
    wd_incoming = int(
        await conn.fetchval(
            """
            SELECT COUNT(*) FROM user_referral_withdrawals
            WHERE status = 'pending' AND operator_id IS NULL
              AND COALESCE(source, 'balance') <> 'casino'
            """
        )
        or 0
    )
    total_ready = ready + wd_incoming
    return {
        "queue_count": total_ready,
        "ready_to_accept_count": total_ready,
        "awaiting_receipt_count": awaiting_receipt,
        "client_hold_count": client_holds,
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


def _operator_has_role(op: dict, role: str) -> bool:
    assigned = op.get("operator_roles")
    if isinstance(assigned, str):
        assigned = [assigned]
    return role in {str(value) for value in (assigned or [op.get("operator_role") or "client"])}


def _role_split_update_query(
    order_id: str,
    *,
    intake_operator_id: int | None = None,
    finance_operator_id: int | None = None,
    source: str | None = None,
    required: bool = False,
) -> tuple[str, list]:
    """Build UPDATE for role-split freeze. Placeholders are 1..n with no gaps.

    Previously ``values`` started with unused ``order_id`` ($1), so Postgres
    raised IndeterminateDatatypeError on finance lock-in / manual buy finalize.
    """
    sets = ["payroll_model = 'role_split'"]
    values: list = []
    if required:
        sets.append("payroll_split_required = TRUE")
    if source:
        values.append(source)
        sets.append(f"order_source = ${len(values)}")
    if intake_operator_id is not None:
        values.append(intake_operator_id)
        sets.append(f"intake_operator_id = COALESCE(intake_operator_id, ${len(values)})")
    if finance_operator_id is not None:
        values.append(finance_operator_id)
        sets.extend(
            [
                f"finance_operator_id = ${len(values)}",
                "finance_claimed_at = COALESCE(finance_claimed_at, now())",
                "claimed_at = COALESCE(claimed_at, now())",
            ]
        )
    values.append(order_id)
    query = (
        f"UPDATE orders SET {', '.join(sets)}, updated_at = now() "
        f"WHERE order_id = ${len(values)} RETURNING *"
    )
    return query, values


async def _mark_role_split_order(
    conn,
    order_id: str,
    *,
    assigned_by: int | None = None,
    intake_operator_id: int | None = None,
    finance_operator_id: int | None = None,
    source: str | None = None,
    required: bool = False,
) -> dict:
    """Mark an order for role payroll and freeze any newly assigned participant."""
    from operator_payroll_split import ensure_order_participant

    row = await conn.fetchrow(
        "SELECT * FROM orders WHERE order_id = $1 FOR UPDATE",
        order_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    query, values = _role_split_update_query(
        order_id,
        intake_operator_id=intake_operator_id,
        finance_operator_id=finance_operator_id,
        source=source,
        required=required,
    )
    updated = await conn.fetchrow(query, *values)
    if not updated:
        raise HTTPException(status_code=409, detail="Заявка изменилась, повторите действие")
    if intake_operator_id is not None:
        await ensure_order_participant(
            conn, order_id, int(intake_operator_id), "client", "intake", assigned_by
        )
    if finance_operator_id is not None:
        await ensure_order_participant(
            conn, order_id, int(finance_operator_id), "finance", "payout", assigned_by
        )
    return dict(updated)


async def _clear_role_split_pending(pool, order_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE orders
            SET payroll_split_required = FALSE, updated_at = now()
            WHERE order_id = $1 AND status NOT IN ('PAID', 'COMPLETED')
            """,
            order_id,
        )


async def _finalize_role_split(pool, order_id: str) -> dict | None:
    from operator_payroll_split import ensure_order_payroll_split

    async with pool.acquire() as conn:
        async with conn.transaction():
            return await ensure_order_payroll_split(conn, order_id)


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


async def _operators_on_shift_together(conn, operator_a: int, operator_b: int) -> bool:
    """Оба имеют открытую смену (команда на смене)."""
    if int(operator_a) == int(operator_b):
        return True
    row = await conn.fetchrow(
        """
        SELECT 1
        FROM operator_shifts a
        JOIN operator_shifts b
          ON a.ended_at IS NULL AND b.ended_at IS NULL
        WHERE a.operator_id = $1 AND b.operator_id = $2
        LIMIT 1
        """,
        int(operator_a),
        int(operator_b),
    )
    return bool(row)


async def _assert_live_order_access(conn, op: dict, row) -> None:
    """Владелец заявки или коллега с открытой сменой — без claim."""
    owner = row["operator_id"] if not isinstance(row, dict) else row.get("operator_id")
    if owner is None:
        return
    op_id = int(op["id"])
    owner_id = int(owner)
    if owner_id == op_id:
        return
    if await _operators_on_shift_together(conn, op_id, owner_id):
        return
    name = await _operator_display_name(conn, owner_id)
    raise HTTPException(status_code=403, detail=f"Заявка у {name}")


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
          AND COALESCE(source, 'balance') <> 'casino'
        """,
        operator_id,
    )
    return int(orders or 0) + int(withdrawals or 0)


async def _team_snapshot(conn, viewer: dict) -> dict:
    from operator_avatars import operator_avatar_public_url

    include_role_grades = can_view_finance_operator(viewer)

    rows = await conn.fetch(
        """
        SELECT oa.id, oa.username, oa.display_name, oa.avatar_file_id,
               oa.operator_roles,
               COALESCE(role_grades.role_grades, '{}'::jsonb) AS role_grades,
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
                     AND COALESCE(w.source, 'balance') <> 'casino'
               ) AS withdrawals_in_progress
        FROM operator_accounts oa
        LEFT JOIN operator_shifts os
            ON os.operator_id = oa.id AND os.ended_at IS NULL
        LEFT JOIN LATERAL (
            SELECT jsonb_object_agg(p.role, p.grade) AS role_grades
            FROM operator_role_profiles p
            WHERE p.operator_id = oa.id AND p.valid_to IS NULL
        ) role_grades ON TRUE
        WHERE oa.is_active
        ORDER BY (os.started_at IS NULL), os.started_at DESC, oa.username
        """
    )
    operators = []
    on_shift = []
    for r in rows:
        started = r["shift_started_at"]
        roles = r.get("operator_roles") or ["client"]
        if isinstance(roles, str):
            roles = [roles]

        role_grades = _role_grades_dict(r.get("role_grades"))

        item = {
            "id": r["id"],
            "username": r["username"],
            "display_name": r.get("display_name"),
            "avatar_url": operator_avatar_public_url(r.get("avatar_file_id")),
            "operator_roles": list(roles),
            "on_shift": r["shift_id"] is not None,
            "shift_id": r["shift_id"],
            "shift_started_at": started.isoformat() if started else None,
            "orders_in_progress": int(r["orders_in_progress"] or 0),
            "withdrawals_in_progress": int(r["withdrawals_in_progress"] or 0),
        }
        if include_role_grades:
            item["role_grades"] = role_grades
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
    from permissions import enrich_operator_permissions

    op = await enrich_operator_permissions(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        shift_row = await conn.fetchrow(
            "SELECT * FROM operator_shifts WHERE operator_id = $1 AND ended_at IS NULL "
            "ORDER BY started_at DESC LIMIT 1",
            op["id"],
        )
        shift = _shift_out(dict(shift_row)) if shift_row else None
        team = await _team_snapshot(conn, op)

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
            current_shift = await stats_for_operator_shift_conn(
                conn,
                op["id"],
                shift_row["started_at"],
                None,
                float(op.get("percent") or 0),
            )
            current_shift = strip_operator_profit_fields(current_shift)
            try:
                from operator_hourly_pay import (
                    attach_open_shift_hourly,
                    open_shift_hourly_preview,
                )

                hourly_preview = await open_shift_hourly_preview(conn, op["id"])
                current_shift = attach_open_shift_hourly(current_shift, hourly_preview)
            except Exception:
                logger.exception("hourly preview failed operator=%s", op["id"])
            shift_balances = await _load_shift_balances(conn, shift_row["id"])

    public_op = operator_public_dict(op)
    public_op["permissions"] = op.get("permissions") or []
    from permissions import load_operator_role_grades

    public_op["role_grades"] = await load_operator_role_grades(int(op["id"]))
    return {
        "operator": public_op,
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
# GET /api/operator/hot-wallet — остаток BTC/LTC для старшего финансиста на смене
# ---------------------------------------------------------------------------

@router.get("/hot-wallet")
async def operator_hot_wallet(op: dict = Depends(get_current_operator)):
    from permissions import load_operator_role_grades, operator_is_finance_senior
    from hot_wallet_runway import build_hot_wallet_runway
    from signer_client import fetch_signer_deposit_addresses

    grades = await load_operator_role_grades(int(op["id"]))
    if not operator_is_finance_senior({**op, "role_grades": grades}, grades):
        raise HTTPException(
            status_code=403,
            detail="Горячий кошелёк видит старший финансовый оператор",
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, int(op["id"]))
        runway = await build_hot_wallet_runway(conn)
    addresses: dict = {}
    try:
        fetched = await fetch_signer_deposit_addresses()
        raw = fetched.get("addresses") if isinstance(fetched, dict) else None
        if isinstance(raw, dict):
            addresses = raw
    except Exception:
        logger.warning("hot wallet deposit addresses unavailable", exc_info=True)
    coins = []
    for row in runway.get("coins") or []:
        item = dict(row)
        coin = str(item.get("coin") or "")
        item["deposit_address"] = addresses.get(coin) or None
        coins.append(item)
    return {**runway, "coins": coins}


async def _require_hot_wallet_sender(op: dict):
    """Старший финансист на открытой смене — тот же заслон, что у карточки кошелька."""
    from permissions import load_operator_role_grades, operator_is_finance_senior

    grades = await load_operator_role_grades(int(op["id"]))
    if not operator_is_finance_senior({**op, "role_grades": grades}, grades):
        raise HTTPException(
            status_code=403,
            detail="Горячий кошелёк видит старший финансовый оператор",
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        shift = await _require_active_shift(conn, int(op["id"]))
    return shift


@router.post("/hot-wallet/send/preview")
async def operator_hot_wallet_send_preview(
    body: SwapPreviewIn,
    op: dict = Depends(get_current_operator),
):
    import hot_wallet_swap
    from project_wallet_payout import WalletPayoutError

    shift = await _require_hot_wallet_sender(op)
    try:
        return await hot_wallet_swap.preview(
            operator_id=int(op["id"]), shift_id=int(shift["id"]), body=body
        )
    except WalletPayoutError as exc:
        raise _wallet_http(exc) from None


@router.post("/hot-wallet/send")
async def operator_hot_wallet_send(
    body: SwapConfirmIn,
    op: dict = Depends(get_current_operator),
):
    import hot_wallet_swap
    from project_wallet_payout import WalletPayoutError

    shift = await _require_hot_wallet_sender(op)
    try:
        return await hot_wallet_swap.confirm(
            operator_id=int(op["id"]), shift_id=int(shift["id"]), body=body
        )
    except WalletPayoutError as exc:
        raise _wallet_http(exc) from None


# ---------------------------------------------------------------------------
# GET /api/operator/team — операторы и активные смены
# ---------------------------------------------------------------------------

@router.get("/team")
async def operator_team(
    op: dict = Depends(get_current_operator),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _team_snapshot(conn, op)


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
        from operator_hourly_pay import hourly_snapshot_for_shift_start

        hourly_enabled, hourly_rate = await hourly_snapshot_for_shift_start(conn)
        row = await conn.fetchrow(
            """
            INSERT INTO operator_shifts (operator_id, hourly_enabled, hourly_rate_rub)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            op["id"],
            hourly_enabled,
            hourly_rate,
        )
        await _save_start_balances(conn, row["id"], validated)
        op_name = op.get("display_name") or op["username"]
        try:
            from operator_shift_store import sync_active_shift_user_ids_from_db

            await sync_active_shift_user_ids_from_db(conn)
        except Exception:
            logger.warning("shift store sync after open failed", exc_info=True)
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
        summary = await stats_for_operator_shift_conn(
            conn,
            op["id"],
            row["started_at"],
            row["ended_at"],
            float(op.get("percent") or 0),
        )
        summary = strip_operator_profit_fields(summary)
        balance_summary = await _compute_network_fees(
            conn, row["id"], op["id"], row["started_at"], row["ended_at"]
        )
        from operator_payroll_pool import accrue_shift
        from operator_hourly_pay import accrue_shift_hourly

        await accrue_shift(conn, int(row["id"]), op["id"])
        await accrue_shift_hourly(conn, dict(row))
        op_name = op.get("display_name") or op["username"]
        try:
            from operator_shift_store import sync_active_shift_user_ids_from_db

            await sync_active_shift_user_ids_from_db(conn)
        except Exception:
            logger.warning("shift store sync after close failed", exc_info=True)
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
    limit: int = 200,
    offset: int = 0,
    op: dict = Depends(get_current_operator),
):
    """incoming — без оператора; orders — все открытые на смене; team_orders — у коллег."""
    pool = await get_pool()
    op_id = op["id"]
    async with pool.acquire() as conn:
        hold_rows = await conn.fetch(
            f"""
            SELECT o.*, bu.username AS buyer_username, bu.first_name AS buyer_first_name,
                   oa.username AS operator_username, oa.display_name AS operator_display_name,
                   (
                     SELECT p.order_id
                     FROM orders p
                     WHERE p.user_id = o.user_id
                       AND p.order_id <> o.order_id
                       AND COALESCE(p.order_source, '') IN ('manual', 'manual_operator')
                       AND p.created_at >= o.created_at
                       AND p.status IN ('OPERATOR_PENDING', 'COMPLETED', 'PAID', 'PENDING')
                     ORDER BY p.created_at ASC
                     LIMIT 1
                   ) AS replaced_by_order_id
            FROM orders o
            LEFT JOIN bot_users bu ON bu.user_id = o.user_id
            LEFT JOIN operator_accounts oa ON oa.id = o.operator_id
            WHERE {_CLIENT_HOLD_WHERE}
            ORDER BY o.created_at ASC
            LIMIT $2
            """,
            list(CLIENT_HOLD_STATUSES),
            limit,
        )
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
        open_rows = await conn.fetch(
            f"""
            {_ORDERS_WITH_BUYER_SQL}
            WHERE o.status NOT IN ('PAID', 'CANCELED', 'EXPIRED', 'FAILED')
            ORDER BY o.created_at DESC
            LIMIT $1 OFFSET $2
            """,
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
              AND {_BALANCE_WD_SQL}
            ORDER BY w.created_at ASC
            LIMIT $1
            """,
            limit,
        )
        wd_mine_rows = await conn.fetch(
            f"""
            {_WITHDRAWALS_WITH_OPERATOR_SQL}
            WHERE w.status = 'pending' AND w.operator_id = $1
              AND {_BALANCE_WD_SQL}
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
              AND {_BALANCE_WD_SQL}
            ORDER BY w.created_at DESC
            LIMIT $2
            """,
            op_id,
            limit,
        )
        try:
            from requisite_retry import list_open_retries

            requisite_retries = await list_open_retries(conn)
        except asyncpg.UndefinedTableError:
            requisite_retries = []
        stats = await _queue_stats(conn)
        holds = [_annotate_client_hold(dict(r)) for r in hold_rows]
        incoming = [dict(r) for r in incoming_rows]
        open_list = [dict(r) for r in open_rows]
        team = [dict(r) for r in team_rows]
        await _fill_payout_rails(conn, holds + incoming + open_list + team)
    cur = op_id
    rates = await _withdrawal_market_rates()
    return {
        **stats,
        "client_holds": [_order_out(r, current_operator_id=cur) for r in holds],
        "incoming": [_order_out(r, current_operator_id=cur) for r in incoming],
        "orders": [_order_out(r, current_operator_id=cur) for r in open_list],
        "team_orders": [_order_out(r, current_operator_id=cur) for r in team],
        "withdrawals_incoming": _withdrawals_out(
            wd_incoming_rows, current_operator_id=cur, rates=rates
        ),
        "withdrawals": _withdrawals_out(wd_mine_rows, current_operator_id=cur, rates=rates),
        "team_withdrawals": _withdrawals_out(
            wd_team_rows, current_operator_id=cur, rates=rates
        ),
        "requisite_retries": requisite_retries,
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
        await _fill_payout_rails(conn, [r])
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
              AND {_BALANCE_WD_SQL}
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
                  AND COALESCE(source, 'balance') <> 'casino'
                """
            )
            or 0
        )
        in_progress = [dict(r) for r in in_progress_rows]
        await _fill_payout_rails(conn, in_progress)
    cur = op_id
    rates = await _withdrawal_market_rates()
    in_progress_orders = [
        _order_out(r, current_operator_id=cur) for r in in_progress
    ]
    in_progress_withdrawals = _withdrawals_out(
        wd_in_progress_rows, current_operator_id=cur, rates=rates
    )
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
                    role = "finance" if (
                        (existing["direction"] or "").lower() == "buy"
                        and existing["status"] in ("COMPLETED", "OPERATOR_PENDING")
                    ) else "client"
                    if role == "finance" and not _operator_has_role(op, "finance"):
                        role = "client"
                    await _mark_role_split_order(
                        conn,
                        order_id,
                        assigned_by=op["id"],
                        intake_operator_id=op["id"] if role == "client" else None,
                        finance_operator_id=op["id"] if role == "finance" else None,
                    )
                    return {
                        "order": _order_out(dict(existing)),
                        "claimed_by": _claimed_by(op),
                    }
                handoff_to_finance = (
                    _operator_has_role(op, "finance")
                    and existing.get("finance_operator_id") is None
                    and existing.get("intake_operator_id") == existing.get("operator_id")
                    and (
                        (
                            (existing["direction"] or "").lower() == "buy"
                            and existing["status"] in ("COMPLETED", "OPERATOR_PENDING")
                        )
                        or (
                            (existing["direction"] or "").lower() == "sell"
                            and existing["status"] in SELL_INCOMING_STATUSES
                        )
                    )
                )
                if handoff_to_finance:
                    row = await conn.fetchrow(
                        """
                        UPDATE orders
                        SET operator_id = $1,
                            finance_operator_id = $1,
                            finance_claimed_at = COALESCE(finance_claimed_at, now()),
                            claimed_at = COALESCE(claimed_at, now()),
                            payroll_model = 'role_split',
                            updated_at = now()
                        WHERE order_id = $2
                          AND operator_id = $3
                          AND finance_operator_id IS NULL
                        RETURNING *
                        """,
                        op["id"],
                        order_id,
                        existing["operator_id"],
                    )
                    if row:
                        from operator_payroll_split import ensure_order_participant

                        await ensure_order_participant(
                            conn, order_id, op["id"], "finance", "payout", op["id"]
                        )
                        return {"order": _order_out(dict(row)), "claimed_by": _claimed_by(op)}
                name = await _operator_display_name(conn, int(existing["operator_id"]))
                raise HTTPException(
                    status_code=409,
                    detail=f"Заявка уже у {name}",
                )
            direction = (existing["direction"] or "").lower()
            status = existing["status"]
            if (
                direction == "buy"
                and status in ("COMPLETED", "OPERATOR_PENDING")
                and not _operator_has_role(op, "finance")
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Эту заявку принимает только финансовый оператор",
                )
            claimable = (
                direction == "buy" and status in BUY_INCOMING_STATUSES
            ) or (direction == "sell" and status in SELL_INCOMING_STATUSES)
            if not claimable:
                raise HTTPException(
                    status_code=404,
                    detail="Заявка ещё без чека или недоступна для принятия",
                )
            claim_role = "finance" if (
                direction == "buy"
                and status in ("COMPLETED", "OPERATOR_PENDING")
            ) else "client"
            if direction == "sell" and not _operator_has_role(op, "client"):
                claim_role = "finance"
            row = await conn.fetchrow(
                """
                UPDATE orders
                SET operator_id = $1,
                    intake_operator_id = CASE WHEN $3 = 'client' THEN COALESCE(intake_operator_id, $1) ELSE intake_operator_id END,
                    finance_operator_id = CASE WHEN $3 = 'finance' THEN $1 ELSE finance_operator_id END,
                    finance_claimed_at = CASE WHEN $3 = 'finance' THEN COALESCE(finance_claimed_at, now()) ELSE finance_claimed_at END,
                    claimed_at = COALESCE(claimed_at, now()),
                    payroll_model = 'role_split',
                    updated_at = now()
                WHERE order_id = $2
                  AND operator_id IS NULL
                RETURNING *
                """,
                op["id"],
                order_id,
                claim_role,
            )
            if row:
                from operator_payroll_split import ensure_order_participant

                await ensure_order_participant(
                    conn,
                    order_id,
                    op["id"],
                    claim_role,
                    "payout" if claim_role == "finance" else "intake",
                    op["id"],
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
    return await execute_sell_paid(order_id, body, op)


async def execute_sell_paid(
    order_id: str,
    body: SellPaidRequest,
    op: dict,
    *,
    notify_user: bool = True,
) -> dict:
    require_operator_role(op, "finance")
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
            if row.get("finance_operator_id") is not None and row["finance_operator_id"] != op["id"]:
                raise HTTPException(status_code=403, detail="Заявка у другого оператора")
            if row.get("operator_id") != op["id"] and row.get("finance_operator_id") != op["id"]:
                raise HTTPException(status_code=403, detail="Сначала возьмите заявку в свою очередь")
            await _mark_role_split_order(
                conn,
                order_id,
                assigned_by=op["id"],
                finance_operator_id=op["id"],
                required=True,
            )

    from bot_status_bridge import update_order_status as bot_set_status

    if not await bot_set_status(order_id, "PAID"):
        await _clear_role_split_pending(pool, order_id)
        raise HTTPException(status_code=409, detail="Недопустимый переход статуса")

    pool = await get_pool()
    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            """
            UPDATE orders
            SET operator_id = COALESCE(operator_id, $1),
                finance_operator_id = COALESCE(finance_operator_id, $1),
                operator_crypto_received = $2,
                operator_fiat_paid_out = $3,
                updated_at = now()
            WHERE order_id = $4
              AND (operator_id IS NULL OR operator_id = $1 OR intake_operator_id = operator_id)
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
        await _finalize_role_split(pool, order_id)
    except Exception:
        logger.exception("sell payroll split pending order=%s", order_id)
    if notify_user:
        try:
            from bot_status_bridge import notify_order_completed_for_user

            await notify_order_completed_for_user(order_dict)
        except Exception as e:
            logger.warning("notify sell_paid order=%s: %s", order_id, e)
    return {"order": _order_out(order_dict)}


# ---------------------------------------------------------------------------
# POST /api/operator/orders/{order_id}/crypto_received — SELL: крипта пришла
# ---------------------------------------------------------------------------

@router.post("/orders/{order_id}/crypto_received")
async def confirm_sell_crypto_received(
    order_id: str,
    op: dict = Depends(get_current_operator),
):
    """Подтверждение прихода крипты — гейт для подбора реквизитов + треугольник в приём."""
    require_operator_role(op, "finance")
    from permissions import (
        PERM_PAYOUT_REQUISITES,
        enrich_operator_permissions,
        has_permission,
    )
    from routers.operator_payout_requisites import ensure_triangle_from_sell

    op = await enrich_operator_permissions(op)
    pool = await get_pool()
    triangle = None
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        row = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1",
            order_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if (row["direction"] or "").lower() != "sell":
            raise HTTPException(status_code=400, detail="Только для SELL-заявок")
        if row["status"] not in ("PENDING", "OPERATOR_PENDING", "AWAITING_CHECK"):
            raise HTTPException(
                status_code=400,
                detail=f"Нельзя подтвердить приход: статус «{row['status']}»",
            )
        finance_op = row.get("finance_operator_id")
        if finance_op is not None and int(finance_op) != int(op["id"]):
            raise HTTPException(status_code=403, detail="Заявка у другого оператора")
        already = row["crypto_confirmed_at"] is not None
        if not already:
            updated = await conn.fetchrow(
                """
                UPDATE orders
                SET crypto_confirmed_at = now(),
                    crypto_confirmed_by = $1,
                    updated_at = now()
                WHERE order_id = $2
                  AND crypto_confirmed_at IS NULL
                RETURNING *
                """,
                int(op["id"]),
                order_id,
            )
            if not updated:
                raise HTTPException(status_code=409, detail="Приход уже подтверждён")
            row = updated
        if has_permission(op, PERM_PAYOUT_REQUISITES):
            try:
                async with conn.transaction():
                    t_row, _plan, _free, created = await ensure_triangle_from_sell(
                        conn, order_id, op, None, idempotent=True
                    )
                triangle = {
                    "id": int(t_row["id"]),
                    "status": t_row["status"],
                    "created": bool(created),
                }
            except HTTPException as exc:
                logger.warning(
                    "triangle after crypto_received order=%s: %s",
                    order_id,
                    exc.detail,
                )
            except Exception:
                logger.exception("triangle after crypto_received order=%s", order_id)
    out = {"order": _order_out(dict(row)), "already_confirmed": already}
    if triangle:
        out["triangle_requisite"] = triangle
    return out


def _require_payin_rail_action(row, op: dict, *, action: str):
    from payin_requisite_rail import is_payin_order

    if not row:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    data = dict(row)
    if (data.get("direction") or "").lower() != "buy":
        raise HTTPException(status_code=400, detail="Только для BUY-заявок")
    if not is_payin_order(data):
        raise HTTPException(status_code=400, detail="Заявка не на реквизитной пейин-рельсе")
    if data.get("status") not in ("PENDING", "AWAITING_CHECK"):
        raise HTTPException(
            status_code=400,
            detail=f"Нельзя {action}: статус «{data.get('status')}»",
        )
    finance_op = data.get("finance_operator_id")
    if finance_op is not None and int(finance_op) != int(op["id"]):
        raise HTTPException(status_code=403, detail="Заявка у другого оператора")
    if data.get("operator_id") not in (None, op["id"]) and data.get("finance_operator_id") != op["id"]:
        raise HTTPException(status_code=403, detail="Сначала возьмите заявку в свою очередь")
    return data


async def _require_payin_confirm_perm(op: dict) -> dict:
    from permissions import (
        PERM_PAYOUT_REQUISITES_CONFIRM,
        enrich_operator_permissions,
        require_permission,
    )

    op = await enrich_operator_permissions(op)
    require_permission(op, PERM_PAYOUT_REQUISITES_CONFIRM)
    return op


async def _set_payin_rail_status(pool, order_id: str, status: str) -> None:
    """COMPLETED/CANCELED через бот-мост; если мост выключен (staging) — локально."""
    from bot_status_bridge import update_order_status as bot_set_status
    from payin_requisite_rail import release_payin_allocation, settle_payin_allocation

    try:
        ok = await bot_set_status(order_id, status)
    except Exception as e:
        logger.warning("bot status %s order=%s: %s", status, order_id, e)
        ok = False
    if ok:
        return
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE orders
                SET status = $2, updated_at = now()
                WHERE order_id = $1
                  AND status = ANY($3::text[])
                RETURNING order_id
                """,
                order_id,
                status,
                ["PENDING", "AWAITING_CHECK", status],
            )
            if not row:
                raise HTTPException(status_code=409, detail="Недопустимый переход статуса")
            if status == "CANCELED":
                await release_payin_allocation(conn, order_id)
            elif status == "COMPLETED":
                await settle_payin_allocation(conn, order_id)


@router.post("/orders/{order_id}/payin_received")
async def confirm_payin_fiat_received(
    order_id: str,
    op: dict = Depends(get_current_operator),
):
    """Подтверждение прихода рублей на карту реквизитчика (пейин-рельса)."""
    op = await _require_payin_confirm_perm(op)
    from payin_requisite_rail import settle_payin_allocation

    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        row = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1",
            order_id,
        )
        _require_payin_rail_action(row, op, action="подтвердить приход")

    if row["status"] != "COMPLETED":
        await _set_payin_rail_status(pool, order_id, "COMPLETED")

    async with pool.acquire() as conn:
        async with conn.transaction():
            await settle_payin_allocation(conn, order_id)
            updated = await conn.fetchrow(
                "SELECT * FROM orders WHERE order_id = $1",
                order_id,
            )
            src = dict(updated or row)
            req_id = src.get("payin_requisite_id")
            triangle_row = None
            if req_id:
                from payout_requisite_matcher import REQUISITE_COLUMNS

                triangle_row = await conn.fetchrow(
                    f"SELECT {REQUISITE_COLUMNS} FROM operator_payout_requisites WHERE id = $1",
                    int(req_id),
                )
    if triangle_row is not None:
        from payin_requisite_rail import complete_triangle_sell, complete_triangle_withdrawal

        await complete_triangle_sell(dict(triangle_row), op)
        await complete_triangle_withdrawal(dict(triangle_row), op)
    return {"order": _order_out(dict(updated) if updated else dict(row))}


PAYIN_REJECT_REASON = "Чек не принят"


@router.post("/orders/{order_id}/payin_reject")
async def reject_payin_receipt(
    order_id: str,
    op: dict = Depends(get_current_operator),
):
    """Отклонить чек на пейин-рельсе: отменить заявку, освободить слот, без бана и без PayFast."""
    op = await _require_payin_confirm_perm(op)

    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        row = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1",
            order_id,
        )
        order = _require_payin_rail_action(row, op, action="отклонить чек")
        await conn.execute(
            """
            UPDATE orders
            SET cancel_reason = $1, canceled_by = $2, updated_at = now()
            WHERE order_id = $3
            """,
            PAYIN_REJECT_REASON,
            op["id"],
            order_id,
        )

    await _set_payin_rail_status(pool, order_id, "CANCELED")

    buyer = order.get("user_id")
    if buyer and int(buyer) > 0:
        try:
            from telegram_notify import send_user_message

            await send_user_message(int(buyer), _cancel_user_text(order_id, PAYIN_REJECT_REASON))
        except Exception as e:
            logger.warning("notify payin reject order=%s: %s", order_id, e)

    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1",
            order_id,
        )
    return {"order": _order_out(dict(updated) if updated else order)}


class DolivSellPushBody(BaseModel):
    pay_method: str = "sbp"
    phone: str | None = None
    card_number: str | None = None
    recipient_name: str | None = None
    bank: str | None = None

    @field_validator("pay_method")
    @classmethod
    def _pm(cls, v: str) -> str:
        m = (v or "sbp").lower()
        if m not in ("sbp", "c2c"):
            raise ValueError("pay_method must be sbp or c2c")
        return m


@router.get("/doliv/card-balances")
async def doliv_card_balances(op: dict = Depends(get_current_operator)):
    """Сводка float на картах трейдеров Doliv (если bridge включён)."""
    del op
    import doliv_bridge

    if not doliv_bridge.bridge_enabled():
        raise HTTPException(503, detail="Doliv bridge disabled")
    data = await doliv_bridge.card_balances()
    if data is None:
        raise HTTPException(502, detail="Doliv bridge unreachable")
    return data


@router.post("/orders/{order_id}/push-doliv-payout")
async def push_sell_to_doliv(
    order_id: str,
    body: DolivSellPushBody,
    op: dict = Depends(get_current_operator),
):
    """SELL: отправить выплату ₽ трейдерам Doliv (PayoutJob)."""
    require_operator_role(op, "finance")
    import doliv_bridge

    if not doliv_bridge.bridge_enabled():
        raise HTTPException(503, detail="Doliv bridge disabled")

    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        row = await conn.fetchrow("SELECT * FROM orders WHERE order_id = $1", order_id)
        if not row:
            raise HTTPException(404, detail="Заявка не найдена")
        if (row["direction"] or "").lower() != "sell":
            raise HTTPException(400, detail="Только для SELL")
        if row["status"] not in ("PENDING", "OPERATOR_PENDING", "AWAITING_CHECK", "COMPLETED"):
            raise HTTPException(400, detail=f"Статус «{row['status']}» не подходит")
        amount_rub = float(row["fiat_amount"] or 0)
        if amount_rub <= 0:
            raise HTTPException(400, detail="fiat_amount пуст")

    requisites = {
        "phone": body.phone,
        "card_number": body.card_number,
        "recipient_name": body.recipient_name,
        "bank": body.bank,
        "method": body.pay_method,
        "order_id": order_id,
        "order_requisites": row["requisites"] if "requisites" in row.keys() else None,
    }
    job = await doliv_bridge.create_payout_job(
        amount_rub=amount_rub,
        pay_method=body.pay_method,
        requisites=requisites,
        source="sell",
        external_ref=f"sell-{order_id}",
    )
    if not job:
        raise HTTPException(502, detail="Doliv did not create payout job")
    return {"order_id": order_id, "doliv_job": job}


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
                SET status = 'CANCELED', payout_tx_hash = NULL, updated_at = now()
                WHERE order_id = $1 AND status = 'OPERATOR_PENDING'
                """,
                order_id,
            )
    except Exception as e:
        logger.warning("rollback orphan manual buy order=%s: %s", order_id, e)


async def _require_retry_wallet(order) -> None:
    """Заявка из черновика не выплачивается, пока клиент не подтвердил кошелёк."""
    from payout_wallet_confirm import WalletNotConfirmed, ensure_retry_wallet_confirmed

    try:
        await ensure_retry_wallet_confirmed(dict(order))
    except WalletNotConfirmed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _finalize_manual_buy_paid(
    pool,
    order_id: str,
    operator_id: int,
    tx_hash_raw: str,
) -> dict:
    """OPERATOR_PENDING → PAID + payout fields + финансовые хуки + уведомление."""
    from bot_status_bridge import confirm_manual_buy_payout

    async with pool.acquire() as conn:
        pending = await conn.fetchrow("SELECT * FROM orders WHERE order_id = $1", order_id)
    if pending:
        await _require_retry_wallet(pending)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await _mark_role_split_order(
                conn,
                order_id,
                assigned_by=operator_id,
                finance_operator_id=operator_id,
                required=True,
            )

    ok, err, order_out = await confirm_manual_buy_payout(
        order_id,
        tx_hash=tx_hash_raw,
        actor=f"operator:{operator_id}",
        operator_id=operator_id,
    )
    if not ok:
        await _clear_role_split_pending(pool, order_id)
        _raise_manual_payout_error(err)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            order_id,
        )
    try:
        await _finalize_role_split(pool, order_id)
    except Exception:
        logger.exception("manual buy payroll split pending order=%s", order_id)
    if row:
        return dict(row)
    return order_out or {}


async def _finalize_completed_project_paid(
    pool,
    order_id: str,
    operator_id: int,
    tx_hash_raw: str,
) -> dict:
    """COMPLETED → PAID после отправки с кошелька проекта. Начисление смены то же, что у ручной."""
    from bot_status_bridge import confirm_buy_payout

    async with pool.acquire() as conn:
        async with conn.transaction():
            await _mark_role_split_order(
                conn,
                order_id,
                assigned_by=operator_id,
                finance_operator_id=operator_id,
                required=True,
            )

    ok, err, order_out = await confirm_buy_payout(
        order_id,
        tx_hash=tx_hash_raw,
        actor=f"operator:{operator_id}",
        operator_id=operator_id,
        force=True,
    )
    if not ok:
        await _clear_role_split_pending(pool, order_id)
        _raise_manual_payout_error(err)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            order_id,
        )
    try:
        await _finalize_role_split(pool, order_id)
    except Exception:
        logger.exception("completed project payout split pending order=%s", order_id)
    if row:
        return dict(row)
    return order_out or {}


class _ManualBuyPreview(Exception):
    """Расчёт ручной BUY без записи: транзакция откатывается, наружу — цифры."""

    def __init__(self, data: dict) -> None:
        super().__init__("preview")
        self.data = data


def _wallet_http(exc) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


async def _project_wallet_send_and_finalize(
    pool,
    *,
    order_id: str,
    op_id: int,
    recon_operator_id: int,
    user_id: int,
    crypto: str,
    address: str,
    crypto_amount: float,
    amount_rub: float,
    cancel_on_reject: bool,
    order_status: str = "OPERATOR_PENDING",
) -> tuple[dict, str]:
    """Отправка с кошелька проекта → PAID. Если крипта ушла, заявку не откатываем."""
    import project_wallet_payout as pwp

    coin = pwp.coin_of(crypto)
    async with pool.acquire() as conn:
        pending = await conn.fetchrow("SELECT * FROM orders WHERE order_id = $1", order_id)
    if pending:
        await _require_retry_wallet(pending)
    try:
        st, resp = await pwp.send_from_project_wallet(
            order_id=order_id,
            user_id=user_id,
            coin=coin,
            address=address,
            crypto_amount=crypto_amount,
            amount_rub=amount_rub,
            operator_id=op_id,
        )
    except pwp.WalletPayoutError as exc:
        if cancel_on_reject:
            await _rollback_orphan_manual_buy(pool, order_id)
        raise _wallet_http(exc) from None
    if st == "rejected":
        if cancel_on_reject:
            await _rollback_orphan_manual_buy(pool, order_id)
        reason = str(resp.get("reason") or resp.get("error") or "rejected")
        raise HTTPException(
            status_code=409,
            detail=f"Кошелёк проекта отклонил отправку ({reason}). Крипта не ушла.",
        )
    txid = str(resp.get("txid") or "")
    if st != "accepted" or not txid:
        await pwp.notify_admin(
            f"❗️ Заявка {order_id}: отправка с кошелька проекта без ответа "
            f"({coin.upper()} {crypto_amount:.8f} → <code>{address}</code>). "
            "Проверьте по ноде, повторно не отправляйте."
        )
        raise HTTPException(
            status_code=502,
            detail="Кошелёк не подтвердил отправку. Заявка заморожена до проверки админом — "
            "не отправляйте крипту повторно со своего кошелька.",
        )
    try:
        if order_status == "COMPLETED":
            order_dict = await _finalize_completed_project_paid(pool, order_id, op_id, txid)
        else:
            order_dict = await _finalize_manual_buy_paid(pool, order_id, op_id, txid)
    except Exception as exc:
        logger.exception("finalize after project wallet send failed order=%s", order_id)
        await pwp.notify_admin(
            f"❗️ Заявка {order_id}: крипта отправлена с кошелька проекта "
            f"(tx <code>{txid}</code>), но заявка не закрылась: {exc}. Нужна ручная сверка."
        )
        raise HTTPException(
            status_code=500,
            detail=f"Крипта отправлена (tx {txid}), но заявка не закрылась — админ проверит. "
            "Повторно не отправляйте.",
        ) from None
    await pwp.mark_confirmed(str(resp.get("request_id") or f"order:{order_id}"))
    try:
        await pwp.record_shift_recon(
            order_id=order_id,
            operator_id=recon_operator_id,
            amount_rub=amount_rub,
            coin=coin,
            txid=txid,
        )
    except Exception:
        logger.exception("project wallet recon entry failed order=%s", order_id)
    try:
        from network_fees import record_project_wallet_fee

        await record_project_wallet_fee(
            order_id=order_id,
            request_id=str(resp.get("request_id") or ""),
            coin=coin,
            txid=txid,
            fee_crypto=resp.get("fee"),
            vsize=resp.get("vsize"),
        )
    except Exception:
        logger.exception("project wallet fee record failed order=%s", order_id)
    await pwp.notify_admin(
        f"Ручная заявка {order_id}: оператор #{op_id} отправил с кошелька проекта "
        f"{crypto_amount:.8f} {coin.upper()} ({amount_rub:,.0f} ₽). tx <code>{txid}</code>".replace(",", " ")
    )
    return order_dict, txid


def _wallet_fp_new(body: "CreateOrderRequest") -> str:
    import project_wallet_payout as pwp

    return pwp.fingerprint(
        {
            "buyer_user_id": body.buyer_user_id,
            "crypto": body.crypto,
            "network": body.network,
            "fiat_amount": body.fiat_amount,
            "crypto_amount": body.crypto_amount,
            "wallet_address": (body.wallet_address or "").strip(),
            "manual_spread_pct": body.manual_spread_pct,
            "received_fiat_amount": body.received_fiat_amount,
            "exchange_discount_id": body.exchange_discount_id,
            "apply_balance": body.apply_balance,
        }
    )


def _wallet_fp_handoff(order_id: str, address: str, crypto_amount: float) -> str:
    import project_wallet_payout as pwp

    return pwp.fingerprint(
        {"order_id": order_id, "address": address, "amount": f"{Decimal(str(crypto_amount)):.8f}"}
    )


class WalletSendBody(BaseModel):
    preview_token: str = Field(..., min_length=10, max_length=2000)
    totp_code: str = Field(..., min_length=6, max_length=8)
    allow_other_client: bool = False


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
    # True/False — явное решение оператора; None — флаг клиента use_cashback_on_next
    apply_balance: Optional[bool] = None
    manual_spread_pct: Optional[Decimal] = None
    received_fiat_amount: Optional[Decimal] = None
    requisite_ticket: Optional[str] = None
    wallet_send: Optional[WalletSendBody] = None

    @field_validator("requisite_ticket")
    @classmethod
    def _validate_requisite_ticket(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        from manual_requisite_store import normalize_ticket_code

        code = normalize_ticket_code(v)
        if not code:
            raise ValueError("Код реквизита — вида MAN-AB12CD")
        return code

    @field_validator("manual_spread_pct")
    @classmethod
    def _validate_manual_spread_pct(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is None:
            return None
        if not v.is_finite():
            raise ValueError("Индивидуальный процент должен быть конечным числом")
        spread = v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if spread != v or not MANUAL_BUY_SPREAD_MIN <= spread <= MANUAL_BUY_SPREAD_MAX:
            raise ValueError("Индивидуальный процент должен быть от 14.00% до 25.00%")
        return spread

    @field_validator("received_fiat_amount")
    @classmethod
    def _validate_received_fiat_amount(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is None:
            return None
        if not v.is_finite():
            raise ValueError("Полученная сумма должна быть конечным числом")
        amount = v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amount != v or amount <= 0:
            raise ValueError("Полученная сумма должна быть больше нуля с точностью до копеек")
        return amount

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
        if v is not None and (not math.isfinite(v) or v <= 0):
            raise ValueError("Сумма в рублях должна быть конечным числом больше нуля")
        return v

    @field_validator("crypto_amount")
    @classmethod
    def _validate_crypto_amount(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (not math.isfinite(v) or v <= 0):
            raise ValueError("Сумма в крипте должна быть конечным числом больше нуля")
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
            if self.fiat_amount is None and self.crypto_amount is None:
                raise ValueError("Укажите сумму в рублях или в крипте")
            if self.manual_spread_pct is None:
                raise ValueError("Укажите индивидуальный процент ручной заявки")
            if self.received_fiat_amount is None:
                raise ValueError("Укажите полученную на реквизит сумму")
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
    is_finance = _operator_has_role(op, "finance")
    if body.wallet_send is not None:
        import project_wallet_payout as pwp

        if body.order_type != "buy" or not is_finance:
            raise HTTPException(status_code=403, detail="Отправка с кошелька проекта — только финансовому оператору")
        if body.tx_hash:
            raise HTTPException(status_code=400, detail="Либо hash своей транзакции, либо отправка с кошелька проекта")
        if not pwp.project_mode_for(body.crypto):
            raise HTTPException(status_code=400, detail="Отправка с кошелька проекта сейчас выключена")
    elif body.order_type == "buy":
        if is_finance and not (body.tx_hash or "").strip():
            raise HTTPException(status_code=400, detail="Финансовому оператору нужен hash транзакции")
        if not is_finance and body.tx_hash:
            raise HTTPException(
                status_code=403,
                detail="Клиентский оператор не фиксирует выплату — передайте заявку финансовому оператору",
            )
    if body.order_type == "sell_qr" and not is_finance:
        raise HTTPException(status_code=403, detail="Продажа QR доступна только финансовому оператору")
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
        if body.wallet_send is None:
            return await _create_operator_order_impl(body, op, pool)
        import project_wallet_payout as pwp

        async with pwp.operator_lock(op["id"]):
            try:
                async with pool.acquire() as conn:
                    pinned = await pwp.authorize(
                        conn,
                        operator_id=op["id"],
                        token=body.wallet_send.preview_token,
                        fp=_wallet_fp_new(body),
                        totp_code=body.wallet_send.totp_code,
                        user_id=body.buyer_user_id,
                        crypto=body.crypto,
                        address=(body.wallet_address or "").strip(),
                        allow_other_client=body.wallet_send.allow_other_client,
                    )
            except pwp.WalletPayoutError as exc:
                raise _wallet_http(exc) from None
            return await _create_operator_order_impl(body, op, pool, pinned=pinned)
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
    *,
    preview: bool = False,
    pinned: dict | None = None,
):
    try:
        market = await get_rates_cached()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Не удалось получить курс: {e}")

    if body.order_type in ("sell", "sell_qr"):
        try:
            market = await get_sell_market_rates()
        except Exception as e:
            logger.warning("sell CoinGecko market unavailable, Rapira kept: %s", e)

    base_rate = market.get(body.crypto)
    if not base_rate:
        raise HTTPException(status_code=400, detail=f"Курс для {body.crypto} недоступен")
    if pinned is not None:
        import project_wallet_payout as pwp

        # Курс из окна подтверждения: иначе крипта к отправке «поплывёт».
        if not pwp.rate_close(float(base_rate), float(pinned["rate"])):
            raise HTTPException(
                status_code=409,
                detail="Курс сдвинулся больше чем на 1% — откройте окно подтверждения заново",
            )
        base_rate = float(pinned["rate"])

    order_id = "OP" + secrets.token_hex(8).upper()
    buyer_id = body.buyer_user_id

    if body.order_type == "buy":
        is_finance = _operator_has_role(op, "finance")
        manual_spread_pct = body.manual_spread_pct
        received_fiat_amount = body.received_fiat_amount
        if manual_spread_pct is None or received_fiat_amount is None:
            raise HTTPException(status_code=400, detail="Укажите индивидуальный процент и полученную сумму")
        crypto_dec, fiat_dec, rate_dec = _manual_buy_pricing(
            market_rate=float(base_rate),
            fiat_amount=body.fiat_amount,
            crypto_amount=body.crypto_amount,
            spread_pct=manual_spread_pct,
        )
        fiat_amount = float(fiat_dec)
        crypto_amount = float(crypto_dec)
        rate_used = float(rate_dec)
        cb_applied = 0.0
        disc_applied = 0.0
        disc_id = body.exchange_discount_id

        # Нормализуем tx_hash до INSERT, чтобы не потерять при таймауте финализации
        payout_tx_hash = None
        if is_finance and body.tx_hash:
            payout_tx_hash = _normalize_operator_tx(body.tx_hash)

        from buy_crypto_amount import clamp_buy_crypto_amount
        from exchange_discount_db import apply_discount_with_conn, hold_discount_for_order

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Лок на покупателя: исключаем гонку cashback-холдов при
                # параллельном создании заявок (сайт/панель/бот).
                await conn.execute("SELECT pg_advisory_xact_lock($1)", buyer_id)
                buyer = await _resolve_buyer_user_id(conn, buyer_id)
                if body.apply_balance is None:
                    use_cb = await should_use_cashback(buyer_id)
                else:
                    use_cb = bool(body.apply_balance)
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
                # Ручная фиксация: введённая крипта — факт. Не ужимаем её
                # после округления рублей и auto/manual спреда.
                crypto_amount = clamp_buy_crypto_amount(
                    crypto_amount,
                    fiat_amount=fiat_amount,
                    rate=rate_used,
                    crypto=body.crypto,
                    cashback_applied_rub=float(cb_applied or 0),
                    exchange_discount_applied_rub=float(disc_applied or 0),
                    lock_crypto=body.crypto_amount is not None,
                )
                overpay_rub, overpay_credit_rub = _manual_buy_overpay(
                    fiat_amount,
                    received_fiat_amount,
                    manual_spread_pct,
                )
                economics_json = json.dumps(
                    build_economics_snapshot(
                        "buy",
                        body.crypto,
                        fiat_amount,
                        crypto_amount,
                        rate_used,
                        cashback_applied_rub=float(cb_applied or 0),
                        card_fee=runtime_settings.card_fee_pct(manual=True),
                        manual_buy=True,
                        buy_markup_override=1 + float(manual_spread_pct) / 100,
                    )
                )
                if preview:
                    raise _ManualBuyPreview(
                        {
                            "buyer": dict(buyer),
                            "fiat_amount": float(fiat_amount),
                            "crypto_amount": float(crypto_amount),
                            "rate_used": float(rate_used),
                            "base_rate": float(base_rate),
                            "cashback_applied": float(cb_applied or 0),
                            "exchange_discount_applied": float(disc_applied or 0),
                        }
                    )
                if pinned is not None and not pwp.same_amount(crypto_amount, pinned["amt"]):
                    raise HTTPException(
                        status_code=409,
                        detail="Сумма к отправке изменилась — откройте окно подтверждения заново",
                    )
                await conn.fetchrow(
                    """
                    INSERT INTO orders (
                        order_id, user_id, direction, crypto, fiat_amount, crypto_amount,
                        rate, wallet_address, network, requisites, status, operator_id,
                        intake_operator_id, finance_operator_id, order_source, payroll_model,
                        card_fee_pct, cashback_applied_rub,
                        exchange_discount_applied_rub, exchange_discount_id,
                        payout_tx_hash,
                        manual_spread_pct, received_fiat_amount, overpay_rub, overpay_credit_rub,
                        economics_snapshot,
                        created_at, expires_at, updated_at
                    ) VALUES (
                        $1, $2, 'buy', $3, $4, $5, $6, $7::text, $8, $7::varchar,
                        'OPERATOR_PENDING', $9, $10, $11, 'manual_operator', 'role_split',
                        $12, $13, $14, $15, $16, $17, $18, $19, $20, $21::jsonb,
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
                    body.wallet_address or "",
                    body.network,
                    op["id"] if is_finance else None,
                    None if is_finance else op["id"],
                    op["id"] if is_finance else None,
                    runtime_settings.card_fee_pct(manual=True),
                    float(cb_applied or 0),
                    float(disc_applied or 0),
                    disc_id,
                    payout_tx_hash,
                    manual_spread_pct,
                    received_fiat_amount,
                    overpay_rub,
                    overpay_credit_rub,
                    economics_json,
                )
                if body.requisite_ticket:
                    from manual_requisite_store import apply_ticket_to_order, claim_ticket

                    ticket = await claim_ticket(conn, body.requisite_ticket, order_id)
                    if ticket is None:
                        raise HTTPException(
                            status_code=409,
                            detail="Код реквизита не найден или уже привязан к другой заявке",
                        )
                    await apply_ticket_to_order(conn, ticket, order_id)

                from operator_payroll_split import ensure_order_participant

                await ensure_order_participant(
                    conn,
                    order_id,
                    op["id"],
                    "finance" if is_finance else "client",
                    "payout" if is_finance else "intake",
                    op["id"],
                )
                if cb_applied and cb_applied > 0:
                    await hold_cashback_for_order(conn, buyer_id, order_id, cb_applied)

        if not is_finance:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
                    order_id,
                )
            out = _order_out(dict(row) if row else {})
            out["buyer_username"] = buyer.get("username")
            out["buyer_first_name"] = buyer.get("first_name")
            return {
                "order": out,
                "handoff_required": True,
                "rate_used": round(rate_used, 2),
                "market_rate": round(base_rate, 2),
                "cashback_applied": float(cb_applied or 0),
                "exchange_discount_applied": float(disc_applied or 0),
            }

        if pinned is not None:
            order_dict, txid = await _project_wallet_send_and_finalize(
                pool,
                order_id=order_id,
                op_id=op["id"],
                recon_operator_id=op["id"],
                user_id=buyer_id,
                crypto=body.crypto,
                address=(body.wallet_address or "").strip(),
                crypto_amount=crypto_amount,
                amount_rub=fiat_amount,
                cancel_on_reject=True,
            )
            out = _order_out(order_dict)
            out["buyer_username"] = buyer.get("username")
            out["buyer_first_name"] = buyer.get("first_name")
            return {
                "order": out,
                "txid": txid,
                "paid_from": "project_wallet",
                "rate_used": round(rate_used, 2),
                "market_rate": round(base_rate, 2),
                "cashback_applied": float(cb_applied or 0),
                "exchange_discount_applied": float(disc_applied or 0),
            }
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
        sell_role = "client" if _operator_has_role(op, "client") else "finance"
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
        economics_json = json.dumps(
            build_economics_snapshot(
                "sell", body.crypto, fiat_amount, crypto_amount, rate_used
            )
        )
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _resolve_buyer_user_id(conn, buyer_id)
                row = await conn.fetchrow(
                    """
                    INSERT INTO orders (
                        order_id, user_id, direction, crypto, fiat_amount, crypto_amount,
                        rate, requisites, status, operator_id,
                        intake_operator_id, finance_operator_id, order_source, payroll_model,
                        economics_snapshot,
                        created_at, expires_at, updated_at
                    ) VALUES (
                        $1, $2, 'sell', $3, $4, $5, $6, $7, 'PENDING', $8,
                        CASE WHEN $9 = 'client' THEN $8 ELSE NULL END,
                        CASE WHEN $9 = 'finance' THEN $8 ELSE NULL END,
                        'manual_operator', 'role_split', $10::jsonb,
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
                    sell_role,
                    economics_json,
                )
                from operator_payroll_split import ensure_order_participant

                await ensure_order_participant(
                    conn,
                    order_id,
                    op["id"],
                    sell_role,
                    "intake" if sell_role == "client" else "payout",
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
    economics_json = json.dumps(
        build_economics_snapshot(
            "sell", body.crypto, float(fiat_paid), float(crypto_received), float(rate_used)
        )
    )
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _resolve_buyer_user_id(conn, buyer_id)
            await conn.fetchrow(
                """
                INSERT INTO orders (
                    order_id, user_id, direction, crypto, fiat_amount, crypto_amount,
                    rate, requisites, status, operator_id,
                    intake_operator_id, finance_operator_id, order_source, payroll_model,
                        payroll_split_required,
                        operator_crypto_received, operator_fiat_paid_out, economics_snapshot,
                        created_at, expires_at, updated_at
                    ) VALUES (
                        $1, $2, 'sell', $3, $4, $5, $6, $7, 'CREATED', $8,
                        NULL, $8, 'manual_operator', 'role_split', TRUE, $9, $10, $11::jsonb,
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
                economics_json,
            )
            from operator_payroll_split import ensure_order_participant

            await ensure_order_participant(
                conn, order_id, op["id"], "finance", "payout", op["id"]
            )

    from bot_status_bridge import (
        notify_order_completed_for_user,
        update_order_status as bot_set_status,
    )

    if not await bot_set_status(order_id, "PAID"):
        await _clear_role_split_pending(pool, order_id)
        raise HTTPException(status_code=500, detail="Не удалось закрыть заявку")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            order_id,
        )
    order_dict = dict(row) if row else {}
    try:
        await _finalize_role_split(pool, order_id)
    except Exception:
        logger.exception("sell qr payroll split pending order=%s", order_id)
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

    require_operator_role(op, "finance")
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
            from user_referral_withdraw import is_casino_withdrawal

            if is_casino_withdrawal(dict(existing)):
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
        is_casino_withdrawal,
        notify_withdrawal_completed,
        withdrawal_out,
    )

    require_operator_role(op, "finance")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])

    wd_row = await get_withdrawal(withdrawal_id)
    if not wd_row:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if is_casino_withdrawal(dict(wd_row)):
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
        is_casino_withdrawal,
        manual_triangle_payout_error,
        notify_withdrawal_completed,
        process_withdrawal_paid,
        withdrawal_out,
    )

    require_operator_role(op, "finance")

    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        block = await manual_triangle_payout_error(conn, withdrawal_id)
    if block:
        raise HTTPException(status_code=409, detail=block)

    wd_row = await get_withdrawal(withdrawal_id)
    if not wd_row:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if is_casino_withdrawal(dict(wd_row)):
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


@router.post("/withdrawals/{withdrawal_id}/transfer-to-finance")
async def transfer_withdrawal_to_finance(
    withdrawal_id: int,
    op: dict = Depends(get_current_operator),
):
    """Вернуть вывод в очередь, чтобы его принял финансовый оператор."""
    require_operator_role(op, "client")
    if _operator_has_role(op, "finance"):
        raise HTTPException(status_code=400, detail="Финансовому оператору не нужно передавать вывод")

    from user_referral_withdraw import withdrawal_out

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_active_shift(conn, op["id"])
            row = await conn.fetchrow(
                "SELECT * FROM user_referral_withdrawals WHERE id = $1 FOR UPDATE",
                withdrawal_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            from user_referral_withdraw import is_casino_withdrawal

            if is_casino_withdrawal(dict(row)):
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            if row["status"] != "pending":
                raise HTTPException(status_code=400, detail="Вывод уже обработан")
            if row["operator_id"] != op["id"]:
                raise HTTPException(status_code=403, detail="Вывод не взят вами в работу")
            row = await conn.fetchrow(
                """
                UPDATE user_referral_withdrawals
                SET operator_id = NULL
                WHERE id = $1 AND status = 'pending' AND operator_id = $2
                RETURNING *
                """,
                withdrawal_id,
                op["id"],
            )
    return {"withdrawal": withdrawal_out(dict(row)), "handoff_required": True}


@router.post("/withdrawals/{withdrawal_id}/cancel")
async def cancel_balance_withdrawal(
    withdrawal_id: int,
    op: dict = Depends(get_current_operator),
):
    """Отменить pending-вывод баланса. Деньги остаются на балансе клиента."""
    from user_referral_withdraw import (
        WithdrawalCancelError,
        is_casino_withdrawal,
        notify_withdrawal_rejected,
        release_empty_withdrawal_triangle,
        withdrawal_out,
    )

    require_operator_role(op, "finance")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_active_shift(conn, op["id"])
            row = await conn.fetchrow(
                """
                SELECT * FROM user_referral_withdrawals
                WHERE id = $1
                FOR UPDATE
                """,
                withdrawal_id,
            )
            if not row or is_casino_withdrawal(dict(row)):
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            if row["status"] != "pending":
                raise HTTPException(status_code=409, detail="Заявка уже обработана")
            if row["operator_id"] not in (None, op["id"]):
                raise HTTPException(status_code=403, detail="Заявка у другого оператора")
            try:
                await release_empty_withdrawal_triangle(conn, withdrawal_id)
            except WithdrawalCancelError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            row = await conn.fetchrow(
                """
                UPDATE user_referral_withdrawals
                SET status = 'rejected', processed_at = now()
                WHERE id = $1
                  AND status = 'pending'
                  AND (operator_id IS NULL OR operator_id = $2)
                RETURNING *
                """,
                withdrawal_id,
                op["id"],
            )
    if not row:
        raise HTTPException(status_code=409, detail="Заявка уже обработана")
    wd = dict(row)
    await notify_withdrawal_rejected(wd)
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
    require_operator_role(op, "finance")
    pool = await get_pool()
    oid = order_id.strip()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        preview = await conn.fetchrow("SELECT * FROM orders WHERE order_id = $1", oid)
    if not preview:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if preview.get("finance_operator_id") not in (None, op["id"]):
        raise HTTPException(status_code=403, detail="Заявка у другого финансового оператора")
    if preview.get("operator_id") not in (None, op["id"]):
        raise HTTPException(status_code=403, detail="Сначала возьмите заявку в свою очередь")
    if preview.get("operator_id") is None and preview.get("finance_operator_id") is None:
        raise HTTPException(status_code=403, detail="Сначала возьмите заявку в свою очередь")
    await _require_retry_wallet(preview)

    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM orders WHERE order_id = $1 FOR UPDATE",
                oid,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            if row.get("finance_operator_id") not in (None, op["id"]):
                raise HTTPException(status_code=403, detail="Заявка у другого финансового оператора")
            if row.get("operator_id") not in (None, op["id"]):
                raise HTTPException(status_code=403, detail="Сначала возьмите заявку в свою очередь")
            if row.get("operator_id") is None and row.get("finance_operator_id") is None:
                raise HTTPException(status_code=403, detail="Сначала возьмите заявку в свою очередь")
            await _mark_role_split_order(
                conn,
                oid,
                assigned_by=op["id"],
                finance_operator_id=op["id"],
                required=True,
            )

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
        await _clear_role_split_pending(pool, order_id.strip())
        from services.payfast_payin_guard import payfast_block_message

        raise HTTPException(status_code=409, detail=payfast_block_message(err))
    if err == "wrong_status":
        await _clear_role_split_pending(pool, order_id.strip())
        raise HTTPException(
            status_code=400,
            detail="Подтверждение выплаты доступно только для заявок со статусом COMPLETED",
        )
    if not ok:
        await _clear_role_split_pending(pool, order_id.strip())
        _raise_manual_payout_error(err)
    try:
        await _finalize_role_split(pool, order_id.strip())
    except Exception:
        logger.exception("buy payroll split pending order=%s", order_id.strip())
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
    require_operator_role(op, "finance")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        row = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            order_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if row.get("finance_operator_id") not in (None, op["id"]):
            raise HTTPException(
                status_code=403,
                detail="Заявка у другого финансового оператора",
            )
        if row.get("operator_id") != op["id"] and row.get("finance_operator_id") != op["id"]:
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
        await _forbid_open_project_send(conn, order_id)

    order_dict = await _finalize_manual_buy_paid(
        pool, order_id, op["id"], body.tx_hash
    )
    return {"order": _order_out(order_dict)}


async def _forbid_open_project_send(conn, order_id: str) -> None:
    """Крипта могла уйти с кошелька проекта — второй выплаты быть не должно."""
    open_req = await conn.fetchval(
        """
        SELECT request_id FROM payout_requests
        WHERE ref_id = $1 AND kind = 'manual_buy' AND status <> 'failed'
        LIMIT 1
        """,
        order_id,
    )
    if open_req:
        raise HTTPException(
            status_code=409,
            detail="По заявке уже была отправка с кошелька проекта — дождитесь проверки админом",
        )


@router.get("/payout-wallet-mode")
async def payout_wallet_mode(op: dict = Depends(get_current_operator)):
    import project_wallet_payout as pwp
    from auto_settings import manual_payout_wallet

    return {
        "mode": manual_payout_wallet(),
        "coins": list(pwp.PROJECT_COINS),
        "can_send": _operator_has_role(op, "finance"),
        "preview_ttl_sec": pwp.PREVIEW_TTL_SEC,
    }


async def _require_finance_shift(op: dict) -> None:
    require_operator_role(op, "finance")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])


@router.post("/orders/wallet-preview")
async def wallet_preview_new_order(
    body: CreateOrderRequest,
    op: dict = Depends(get_current_operator),
):
    """Окно подтверждения для новой ручной BUY: точные суммы без записи заявки."""
    import project_wallet_payout as pwp

    await _require_finance_shift(op)
    if body.order_type != "buy":
        raise HTTPException(status_code=400, detail="Только для покупки крипты клиентом")
    if not pwp.project_mode_for(body.crypto):
        raise HTTPException(status_code=400, detail="Отправка с кошелька проекта сейчас выключена")
    if body.tx_hash:
        raise HTTPException(status_code=400, detail="Уберите hash — крипту отправит кошелёк проекта")
    pool = await get_pool()
    try:
        await _create_operator_order_impl(body, op, pool, preview=True)
    except _ManualBuyPreview as p:
        calc = p.data
    else:
        raise HTTPException(status_code=500, detail="Не удалось рассчитать заявку")
    address = (body.wallet_address or "").strip()
    try:
        async with pool.acquire() as conn:
            out = await pwp.build_preview(
                conn,
                operator_id=op["id"],
                fp=_wallet_fp_new(body),
                user_id=body.buyer_user_id,
                crypto=body.crypto,
                address=address,
                crypto_amount=calc["crypto_amount"],
                amount_rub=calc["fiat_amount"],
                base_rate=calc["base_rate"],
            )
    except pwp.WalletPayoutError as exc:
        raise _wallet_http(exc) from None
    buyer = calc.get("buyer") or {}
    out["client"] = {
        "user_id": body.buyer_user_id,
        "username": buyer.get("username"),
        "first_name": buyer.get("first_name"),
    }
    out["rate_used"] = round(calc["rate_used"], 2)
    out["cashback_applied"] = calc["cashback_applied"]
    out["exchange_discount_applied"] = calc["exchange_discount_applied"]
    return out


async def _load_handoff_order(conn, order_id: str, op: dict) -> dict:
    row = await conn.fetchrow(f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1", order_id)
    if not row:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if row.get("finance_operator_id") not in (None, op["id"]):
        raise HTTPException(status_code=403, detail="Заявка у другого финансового оператора")
    if row.get("operator_id") != op["id"] and row.get("finance_operator_id") != op["id"]:
        raise HTTPException(status_code=403, detail="Сначала возьмите заявку в очереди")
    direction = str(row.get("direction") or "").lower()
    if direction != "buy" or row["status"] not in ("OPERATOR_PENDING", "COMPLETED"):
        raise HTTPException(status_code=400, detail=f"Нельзя отправить: статус заявки «{row['status']}»")
    _require_order_buyer(row)
    return dict(row)


def _handoff_address(row: dict) -> str:
    return str(row.get("wallet_address") or row.get("requisites") or "").strip()


@router.post("/orders/{order_id}/wallet-preview")
async def wallet_preview_handoff(order_id: str, op: dict = Depends(get_current_operator)):
    import project_wallet_payout as pwp

    await _require_finance_shift(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _load_handoff_order(conn, order_id, op)
        if not pwp.project_mode_for(row.get("crypto")):
            raise HTTPException(status_code=400, detail="Отправка с кошелька проекта сейчас выключена")
        await _forbid_open_project_send(conn, order_id)
        coin = pwp.coin_of(row.get("crypto"))
        market = await get_rates_cached()
        base_rate = float(market.get(coin) or 0)
        if base_rate <= 0:
            raise HTTPException(status_code=503, detail=f"Курс для {coin} недоступен")
        address = _handoff_address(row)
        amount = float(row.get("crypto_amount") or 0)
        try:
            out = await pwp.build_preview(
                conn,
                operator_id=op["id"],
                fp=_wallet_fp_handoff(order_id, address, amount),
                user_id=int(row["user_id"]),
                crypto=coin,
                address=address,
                crypto_amount=amount,
                amount_rub=float(row.get("fiat_amount") or 0),
                base_rate=base_rate,
            )
        except pwp.WalletPayoutError as exc:
            raise _wallet_http(exc) from None
    out["order_id"] = order_id
    out["client"] = {
        "user_id": row.get("user_id"),
        "username": row.get("buyer_username"),
        "first_name": row.get("buyer_first_name"),
    }
    out["rate_used"] = float(row.get("rate") or 0)
    return out


@router.post("/orders/{order_id}/wallet-send")
async def wallet_send_handoff(
    order_id: str,
    body: WalletSendBody,
    op: dict = Depends(get_current_operator),
):
    import project_wallet_payout as pwp

    await _require_finance_shift(op)
    pool = await get_pool()
    async with pwp.operator_lock(op["id"]):
        async with pool.acquire() as conn:
            row = await _load_handoff_order(conn, order_id, op)
            if not pwp.project_mode_for(row.get("crypto")):
                raise HTTPException(status_code=400, detail="Отправка с кошелька проекта сейчас выключена")
            await _forbid_open_project_send(conn, order_id)
            address = _handoff_address(row)
            amount = float(row.get("crypto_amount") or 0)
            try:
                payload = await pwp.authorize(
                    conn,
                    operator_id=op["id"],
                    token=body.preview_token,
                    fp=_wallet_fp_handoff(order_id, address, amount),
                    totp_code=body.totp_code,
                    user_id=int(row["user_id"]),
                    crypto=row.get("crypto"),
                    address=address,
                    allow_other_client=body.allow_other_client,
                )
            except pwp.WalletPayoutError as exc:
                raise _wallet_http(exc) from None
        order_dict, txid = await _project_wallet_send_and_finalize(
            pool,
            order_id=order_id,
            op_id=op["id"],
            recon_operator_id=int(row.get("intake_operator_id") or op["id"]),
            user_id=int(row["user_id"]),
            crypto=str(row.get("crypto") or ""),
            address=address,
            crypto_amount=float(payload["amt"]),
            amount_rub=float(payload["rub"]),
            cancel_on_reject=False,
            order_status=str(row["status"]),
        )
    return {"order": _order_out(order_dict), "txid": txid, "paid_from": "project_wallet"}


@router.post("/orders/{order_id}/transfer-to-finance")
async def transfer_order_to_finance(
    order_id: str,
    op: dict = Depends(get_current_operator),
):
    """Вернуть заявку в очередь финансового оператора."""
    require_operator_role(op, "client")
    if _operator_has_role(op, "finance"):
        raise HTTPException(status_code=400, detail="Финансовому оператору не нужно передавать заявку")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_active_shift(conn, op["id"])
            row = await conn.fetchrow(
                f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1 FOR UPDATE",
                order_id.strip().upper(),
            )
            if not row:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            if row["operator_id"] != op["id"]:
                raise HTTPException(status_code=403, detail="Заявка не взята вами в работу")
            if row["status"] not in ("PENDING", "COMPLETED", "OPERATOR_PENDING"):
                raise HTTPException(status_code=400, detail="Эту заявку пока нельзя передать финансам")
            row = await conn.fetchrow(
                """
                UPDATE orders
                SET operator_id = NULL,
                    intake_operator_id = COALESCE(intake_operator_id, $2),
                    payroll_model = 'role_split',
                    updated_at = now()
                WHERE order_id = $1 AND operator_id = $2
                RETURNING *
                """,
                order_id.strip().upper(),
                op["id"],
            )
            from operator_payroll_split import ensure_order_participant

            await ensure_order_participant(
                conn,
                order_id.strip().upper(),
                op["id"],
                "client",
                "intake",
                op["id"],
            )
    return {"order": _order_out(dict(row) if row else {}), "handoff_required": True}


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
        await _assert_live_order_access(conn, op, row)
        if row["status"] not in _CANCELABLE_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Заявку нельзя отменить: статус «{row['status']}»",
            )

    order_dict = dict(row)

    if (order_dict.get("direction") or "").lower() == "buy":
        has_payin_rail = order_dict.get("payin_requisite_id") is not None
        has_merchant = bool(
            resolve_payfast_uuid_system(order_dict)
            or str(order_dict.get("merchant_order_id") or "").strip()
        )
        if not has_payin_rail and has_merchant:
            try:
                from merchant_api_helpers import cancel_payin_for_order

                await cancel_payin_for_order(order_dict)
            except Exception as e:
                logger.warning("cancel payin order=%s: %s", order_id, e)

    from bot_status_bridge import update_order_status as bot_set_status

    try:
        ok = await bot_set_status(
            order_id,
            "CANCELED",
            cancel_reason=body.reason,
            canceled_by=int(op["id"]),
        )
    except Exception:
        logger.exception("cancel status order=%s", order_id)
        raise HTTPException(
            status_code=500,
            detail="Не удалось отменить заявку. Повторите или сообщите администратору.",
        )
    if not ok:
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


def _video_request_user_text(order_id: str) -> str:
    import html

    try:
        from services.receipt_instructions import receipt_request_message

        return receipt_request_message(str(order_id), 3)
    except Exception:
        pass
    oid = html.escape(str(order_id))
    return (
        "📎 <b>PDF не принят — требуется видео</b>\n\n"
        f"🆔 Заявка: <code>{oid}</code>\n\n"
        "Пришлите в бот <b>видео</b> подтверждения оплаты (MP4, MOV) — "
        "отправьте видео в чат (не «кружок»)."
    )


async def _fallback_set_video_check(conn, order_id: str) -> bool:
    res = await conn.execute(
        """
        UPDATE orders
        SET status = 'AWAITING_CHECK',
            required_receipt_type = 3,
            updated_at = now()
        WHERE order_id = $1
          AND UPPER(status) NOT IN ('PAID', 'FAILED')
        """,
        order_id,
    )
    return str(res).endswith("1")


async def _set_account_review_status(
    conn,
    user_id: int,
    status: str,
    *,
    reason: str | None,
    operator_id: int,
) -> bool:
    res = await conn.execute(
        """
        UPDATE bot_users
        SET account_review_status = $2,
            account_review_reason = $3,
            account_reviewed_at = CASE
                WHEN $2 IN ('approved', 'rejected') THEN now()
                WHEN $2 = 'pending' THEN COALESCE(account_reviewed_at, now())
                ELSE account_reviewed_at
            END,
            account_reviewed_by = CASE
                WHEN $4::bigint IS NOT NULL THEN $4
                ELSE account_reviewed_by
            END
        WHERE user_id = $1
        """,
        user_id,
        status,
        reason,
        operator_id,
    )
    return str(res).endswith("1")


class AccountReviewRequest(BaseModel):
    action: Literal["approve", "reject"]


class AdjustBalanceRequest(BaseModel):
    amount_rub: float
    reason: str = Field(..., max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        t = (v or "").strip()
        if len(t) < 3:
            raise ValueError("Укажите причину (минимум 3 символа)")
        return t

    @field_validator("amount_rub")
    @classmethod
    def _amount(cls, v: float) -> float:
        amt = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amt == 0:
            raise ValueError("Сумма должна быть не меньше 0.01 ₽")
        return float(amt)


@router.post("/orders/{order_id}/video")
async def request_order_video(
    order_id: str,
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
        await _assert_live_order_access(conn, op, row)
        if str(row["direction"] or "").lower() != "buy":
            raise HTTPException(status_code=400, detail="Видео только для покупки")
        status = str(row["status"] or "").upper()
        if status in ("PAID", "FAILED"):
            raise HTTPException(
                status_code=400,
                detail=f"Нельзя запросить видео: статус «{row['status']}»",
            )

    from bot_status_bridge import request_client_video

    ok, reason = await request_client_video(order_id, source="operator")
    if not ok:
        if str(reason).startswith("status_blocked"):
            raise HTTPException(status_code=400, detail="Нельзя запросить видео в этом статусе")
        if reason == "not_buy":
            raise HTTPException(status_code=400, detail="Видео только для покупки")
        if reason == "order_not_found":
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        async with pool.acquire() as conn:
            fallback_ok = await _fallback_set_video_check(conn, order_id)
        if not fallback_ok:
            raise HTTPException(status_code=409, detail="Не удалось поставить заявку на видео")
        reason = "db_only"
        buyer = row["user_id"]
        if buyer and int(buyer) > 0:
            try:
                from telegram_notify import send_user_message

                await send_user_message(int(buyer), _video_request_user_text(order_id))
            except Exception as e:
                logger.warning("notify video request order=%s: %s", order_id, e)
    elif reason == "db_only":
        buyer = row["user_id"]
        if buyer and int(buyer) > 0:
            try:
                from telegram_notify import send_user_message

                await send_user_message(int(buyer), _video_request_user_text(order_id))
            except Exception as e:
                logger.warning("notify video request order=%s: %s", order_id, e)

    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            order_id,
        )
    return {
        "order": _order_out(dict(updated), current_operator_id=op["id"]) if updated else {},
        "result": reason,
    }


def _send_receipt_http_error(err: str | None) -> HTTPException:
    msg = (err or "Не удалось отправить чек в Payfast").strip()
    low = msg.lower()
    if "не найден" in low and "заявк" in low:
        return HTTPException(status_code=404, detail=msg)
    if "временно недоступен" in low:
        return HTTPException(status_code=503, detail=msg)
    if "уже обработан" in low or "не ожидает" in low:
        return HTTPException(status_code=409, detail=msg)
    if "bridge_unavailable" in low:
        return HTTPException(status_code=503, detail="Мост бота недоступен — повторите отправку")
    return HTTPException(status_code=400, detail=msg)


@router.post("/orders/{order_id}/send-receipt")
async def send_order_receipt_to_payfast(
    order_id: str,
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
        await _assert_live_order_access(conn, op, row)
        if not _can_send_receipt_to_payfast(dict(row)):
            if str(row.get("direction") or "").lower() != "buy":
                raise HTTPException(status_code=400, detail="Чек в Payfast только для покупки")
            if str(row.get("status") or "").upper() != "AWAITING_CHECK":
                raise HTTPException(status_code=409, detail="Заявка не ожидает чек")
            if row.get("payin_requisite_id"):
                raise HTTPException(status_code=400, detail="Это реквизитчик — подтвердите «Рубли получены»")
            try:
                if int(row.get("required_receipt_type") or 2) == 3:
                    raise HTTPException(
                        status_code=400,
                        detail="Видео уходит в Appeals, не в Payfast API",
                    )
            except HTTPException:
                raise
            except (TypeError, ValueError):
                pass
            if not row.get("receipt_file"):
                raise HTTPException(status_code=400, detail="Файл чека не найден")
            raise HTTPException(status_code=400, detail="Нельзя отправить чек в Payfast")

    from bot_status_bridge import send_receipt_to_payfast

    ok, reason = await send_receipt_to_payfast(order_id, operator_id=int(op["id"]))
    if not ok:
        raise _send_receipt_http_error(reason)

    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            order_id,
        )
        upd_dict = dict(updated) if updated else {}
        if upd_dict:
            await _fill_payout_rails(conn, [upd_dict])
    return {
        "order": _order_out(upd_dict, current_operator_id=op["id"]) if upd_dict else {},
        "result": "sent",
    }


@router.post("/orders/{order_id}/send-wallet-confirm")
async def send_order_wallet_confirm_early(
    order_id: str,
    op: dict = Depends(get_current_operator),
):
    """Убрать 5-минутный таймер и досрочно отправить покупателю запрос уточнения кошелька."""
    from payout_wallet_confirm import send_wallet_confirm_early

    oid = order_id.strip().upper()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        row = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            oid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        await _assert_live_order_access(conn, op, row)

    result = await send_wallet_confirm_early(oid)

    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            oid,
        )
        upd_dict = dict(updated) if updated else {}
        if upd_dict:
            await _fill_payout_rails(conn, [upd_dict])
    return {
        "order": _order_out(upd_dict, current_operator_id=op["id"]) if upd_dict else {},
        "result": result,
    }


@router.post("/users/{user_id}/account-review")
async def review_client_account(
    user_id: int,
    body: AccountReviewRequest,
    op: dict = Depends(get_current_operator),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        buyer = await conn.fetchrow(
            """
            SELECT user_id, account_review_status, is_banned
            FROM bot_users WHERE user_id = $1
            """,
            user_id,
        )
        if not buyer:
            raise HTTPException(status_code=404, detail="Клиент не найден в системе")
        current = str(buyer["account_review_status"] or "none")
        if body.action == "approve":
            if current == "approved":
                return {
                    "ok": True,
                    "user_id": user_id,
                    "account_review_status": "approved",
                    "result": "already_approved",
                }
            ok = await _set_account_review_status(
                conn,
                user_id,
                "approved",
                reason="ops_approved",
                operator_id=op["id"],
            )
            if not ok:
                raise HTTPException(status_code=409, detail="Не удалось обновить проверку")
            logger.info("account review approve user=%s by_op=%s", user_id, op["id"])
            return {
                "ok": True,
                "user_id": user_id,
                "account_review_status": "approved",
                "result": "ok",
            }

        if current == "rejected":
            result = "already_rejected"
        else:
            ok = await _set_account_review_status(
                conn,
                user_id,
                "rejected",
                reason="ops_rejected",
                operator_id=op["id"],
            )
            if not ok:
                raise HTTPException(status_code=409, detail="Не удалось обновить проверку")
            result = "ok"

    from bot_status_bridge import ban_user as db_ban_user

    banned = await db_ban_user(
        user_id,
        reason="account_review_rejected",
        operator_id=op["id"],
        ban_type="hard",
    )
    cancelled_order = await _cancel_active_order_for_ban(user_id, pool) if banned else None
    if banned:
        await _notify_user_banned(user_id, "hard")
    logger.info(
        "account review reject user=%s by_op=%s banned=%s order_cancelled=%s",
        user_id,
        op["id"],
        banned,
        cancelled_order,
    )
    return {
        "ok": True,
        "user_id": user_id,
        "account_review_status": "rejected",
        "banned": bool(banned),
        "cancelled_order_id": cancelled_order,
        "result": result,
    }


@router.post("/users/{user_id}/balance")
async def adjust_client_balance(
    user_id: int,
    body: AdjustBalanceRequest,
    op: dict = Depends(get_current_operator),
):
    from permissions import (
        PERM_FINANCE_PAYOUT,
        enrich_operator_permissions,
        has_permission,
        operator_is_senior,
    )
    from user_unified_balance import get_unified_balance_stats, unified_available

    op = await enrich_operator_permissions(op)
    if not (has_permission(op, PERM_FINANCE_PAYOUT) or operator_is_senior(op)):
        raise HTTPException(status_code=403, detail="Недостаточно прав для изменения баланса")

    amount = Decimal(str(body.amount_rub)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    username = str(op.get("username") or op.get("display_name") or op["id"])
    note = f"ops:{username}: {body.reason}"
    ledger_type = "accrual" if amount > 0 else "spend"

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_active_shift(conn, op["id"])
            exists = await conn.fetchval(
                "SELECT 1 FROM bot_users WHERE user_id = $1",
                user_id,
            )
            if not exists:
                raise HTTPException(status_code=404, detail="Клиент не найден в системе")
            available = Decimal(str(await unified_available(conn, user_id))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if amount == 0:
                raise HTTPException(status_code=400, detail="Сумма должна быть не меньше 0.01 ₽")
            if amount < 0 and available + amount < 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Недостаточно средств: доступно {available} ₽",
                )
            await conn.execute(
                """
                INSERT INTO user_cashback_ledger (user_id, type, amount_rub, note)
                VALUES ($1, $2, $3, $4)
                """,
                user_id,
                ledger_type,
                float(amount),
                note,
            )

    stats = await get_unified_balance_stats(user_id)
    logger.info(
        "balance adjust user=%s amount=%s type=%s by_op=%s",
        user_id,
        float(amount),
        ledger_type,
        op["id"],
    )
    return {
        "ok": True,
        "user_id": user_id,
        "amount_rub": float(amount),
        "type": ledger_type,
        "available_rub": stats.get("available_rub"),
        "balance_rub": stats.get("balance_rub"),
        "cashback_rub": stats.get("cashback_rub"),
        "referral_rub": stats.get("referral_rub"),
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
    try:
        sell_market = await get_sell_market_rates()
    except Exception:
        sell_market = market
    base = market.get(crypto)
    if not base:
        # Per-coin fallback: CoinGecko RUB cache / Rapira snapshot file,
        # so one missing coin never 404s the whole form.
        try:
            need = await get_need_rates_cached()
            base = (need or {}).get(crypto) or base
        except Exception:
            pass
    if not base:
        try:
            from routers.public import _load_snapshot_rates as _load_snapshot
            base = (_load_snapshot() or {}).get(crypto) or base
        except Exception:
            pass
    if not base:
        raise HTTPException(status_code=404, detail="Rate not available")
    sell_base = (sell_market or {}).get(crypto) or base
    import runtime_settings

    manual_m = runtime_settings.buy_markup(manual=True)
    sell_d = runtime_settings.sell_discount()
    source = rates_source()
    return {
        "crypto": crypto,
        "market_rate": round(base, 2),
        "buy_rate": round(base * manual_m, 2),
        "sell_rate": round(sell_base * sell_d, 2),
        "sell_market_rate": round(float(sell_base), 2),
        "buy_commission_pct": commission_percent(crypto, "buy", manual=True),
        "sell_commission_pct": commission_percent(crypto, "sell"),
        "buy_markup": manual_m,
        "sell_discount": sell_d,
        "sell_pricing_mode": runtime_settings.sell_pricing_mode(),
        "source": source,
        "frozen": source == "frozen",
    }


# ---------------------------------------------------------------------------
# GET /api/operator/rate/coingecko — справочный курс CoinGecko (для калькулятора ручной заявки)
# ---------------------------------------------------------------------------

@router.get("/rate/coingecko")
async def get_coingecko_rate_for_order(
    crypto: str = "usdt",
    op: dict = Depends(get_current_operator),
):
    """Только справочно для формы ручной заявки (buy): 1 crypto = X ₽ по CoinGecko.

    Использует серверный кэш CoinGecko RUB (TTL 60 сек, см. routers/public.py),
    поэтому ввод каждой цифры не упирается в rate-limit CoinGecko.
    В заявку не сохраняется и на тариф не влияет.
    """
    del op
    crypto = (crypto or "").lower()
    if crypto not in SUPPORTED_CRYPTOS:
        raise HTTPException(status_code=400, detail="Unsupported crypto")
    try:
        need = await get_need_rates_cached()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"CoinGecko недоступен: {e}")
    rub_rate = (need or {}).get(crypto)
    if not rub_rate:
        raise HTTPException(status_code=404, detail=f"Курс CoinGecko для {crypto} недоступен")
    return {
        "crypto": crypto,
        "rub_rate": round(float(rub_rate), 2),
        "source": "coingecko",
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
    from operator_payroll_split import on_shift_payroll_distribution
    from finance_access import can_view_finance_operator
    from permissions import enrich_operator_permissions

    op = await enrich_operator_permissions(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await backfill_accruals(conn)
        bal = await operator_balance(conn, op["id"])
        distribution = await on_shift_payroll_distribution(conn)
        from operator_hourly_pay import open_shift_hourly_preview, payroll_ledger_kind

        try:
            hourly_preview = await open_shift_hourly_preview(conn, op["id"])
        except Exception:
            logger.exception("hourly preview failed operator=%s", op["id"])
            hourly_preview = {
                "open": False,
                "applies": False,
                "rate_rub": 0.0,
                "forecast_rub": 0.0,
                "started_at": None,
            }
        recent_rows = await conn.fetch(
            """
            SELECT id, type, amount_rub, note, created_at
            FROM operator_payroll_ledger
            WHERE operator_id = $1 AND type IN ('accrual', 'hourly', 'penalty')
            ORDER BY created_at DESC
            LIMIT 12
            """,
            op["id"],
        )
        recent_accruals = []
        for raw in recent_rows:
            item = dict(raw)
            created = item.get("created_at")
            if hasattr(created, "isoformat"):
                item["created_at"] = created.isoformat()
            if item.get("amount_rub") is not None:
                item["amount_rub"] = round(float(item["amount_rub"]), 2)
            item["kind"] = payroll_ledger_kind(item)
            recent_accruals.append(item)
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

    # Strip grade_weight от non-finance операторов
    if not can_view_finance_operator(op):
        for participant in distribution.get("participants", []):
            participant.pop("grade_weight", None)
        for participant in distribution.get("client_participants", []):
            participant.pop("grade_weight", None)
        for participant in distribution.get("finance_participants", []):
            participant.pop("grade_weight", None)
        for participant in distribution.get("presence_participants", []):
            participant.pop("grade_weight", None)

    pending = None
    if my_pending:
        pending = dict(my_pending)
        if pending.get("created_at") and hasattr(pending["created_at"], "isoformat"):
            pending["created_at"] = pending["created_at"].isoformat()
    return {
        **bal,
        "my_pending_request": pending,
        "payroll_distribution": distribution,
        "hourly_preview": hourly_preview,
        "recent_accruals": recent_accruals,
    }


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
