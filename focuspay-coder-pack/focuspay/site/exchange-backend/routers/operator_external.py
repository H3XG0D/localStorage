"""Внештатные обмены — API для оператора (ops/create и ops/orders).

Оператор может:
  - искать внештатников по имени / контакту
  - получить превью расчёта сделки
  - создать сделку (статус awaiting_receipt, активная смена)
  - подтвердить или отменить ожидающую сделку (свои / команда на смене / *_any)
  - получить список ожидающих сделок (scoped)

Оператор НЕ может: CRUD внештатников, выводы, финансовую аналитику
без явного permission finance.analytics.
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from auth import get_current_operator
from config import settings
from db import get_pool
from external_deal_timing import (
    EXTERNAL_DEAL_CLIENT_PAY_MIN,
    EXTERNAL_DEAL_WARNING_ELAPSED_SEC,
    EXTERNAL_DEAL_WARNING_TEXT,
)
from external_deal_ops_notify import format_deal_ops_notify
from external_deals_telegram import external_deals_chat
from external_exchange_stats import fetch_exchanger_ops_stats
from external_exchange_calc import preview_deal
from external_exchange_service import (
    cancel_external_deal,
    confirm_external_deal,
    create_external_deal,
    search_exchangers,
)
from permissions import (
    PERM_EXTERNAL_CANCEL,
    PERM_EXTERNAL_CANCEL_ANY,
    PERM_EXTERNAL_CONFIRM,
    PERM_EXTERNAL_CONFIRM_ANY,
    PERM_EXTERNAL_CREATE,
    PERM_EXTERNAL_PREVIEW,
    PERM_EXTERNAL_VIEW,
    PERM_FINANCE_ANALYTICS,
    enrich_operator_permissions,
    has_permission,
    require_permission,
)
from telegram_notify import send_ops_message

router = APIRouter()
logger = logging.getLogger("operator_external")
_ops_schema_ready = False


async def _ensure_ops_deal_schema(conn) -> None:
    """client_stat колонки/таблица — IF NOT EXISTS, один раз на процесс."""
    global _ops_schema_ready
    if _ops_schema_ready:
        return
    from external_client_stat import ensure_client_stat_schema

    await ensure_client_stat_schema(conn)
    _ops_schema_ready = True


# Поля финансовой аналитики — не отдаём без finance.analytics.
_FINANCE_DEAL_FIELDS = (
    "reward_usdt",
    "house_profit_usd",
    "net_profit_rub",
    "payfast_fee_rub",
    "operator_earnings_rub",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _require_active_shift(conn, operator_id: int):
    """Ровно одна «текущая» открытая смена: последняя по started_at.

    Не расширяем контекст на несколько открытых смен без явной политики.
    """
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


async def _assert_deal_access(
    conn,
    principal: dict,
    deal_row,
    *,
    action: str,
) -> None:
    """action: confirm | cancel. Object ACL + team/any permissions."""
    op_id = int(principal["id"])
    owner_id = deal_row.get("operator_id")
    if owner_id is None:
        # HMAC/кабинет без закреплённого оператора — смена + базовое право.
        need = (
            PERM_EXTERNAL_CONFIRM if action == "confirm" else PERM_EXTERNAL_CANCEL
        )
        if not has_permission(principal, need):
            raise HTTPException(
                status_code=403,
                detail="Нет доступа к чужой сделке",
            )
        return

    owner_id = int(owner_id)
    if owner_id == op_id:
        return

    need_any = (
        PERM_EXTERNAL_CONFIRM_ANY if action == "confirm" else PERM_EXTERNAL_CANCEL_ANY
    )
    if has_permission(principal, need_any):
        return

    if await _operators_on_shift_together(conn, op_id, owner_id):
        return

    raise HTTPException(status_code=403, detail="Нет доступа к чужой сделке")


def _strip_finance_fields(deal: dict, principal: dict) -> dict:
    if has_permission(principal, PERM_FINANCE_ANALYTICS):
        return deal
    out = dict(deal)
    for key in _FINANCE_DEAL_FIELDS:
        out.pop(key, None)
    return out


def _jsonish(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            import json

            return json.loads(value)
        except Exception:
            return None
    return None


def _enrich_ops_deal(d: dict) -> dict:
    from external_client_stat import check_public_out, deal_status_as_order, payload_from_row

    out = dict(d)
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif hasattr(v, "__float__") and k not in ("id", "exchanger_id", "operator_id"):
            try:
                out[k] = float(v)
            except Exception:
                logger.debug("ignored non-fatal error", exc_info=True)
    snap = _jsonish(out.get("payment_snapshot")) or {}
    bill = snap.get("bill") if isinstance(snap, dict) else {}
    out["bill"] = bill or {}
    out["has_receipt"] = bool(out.get("receipt_file") or out.get("receipt_submitted_at"))
    out["fingerprint"] = str(out.get("customer_fingerprint") or "").strip() or None
    stat = payload_from_row(out.get("client_stat")) if out.get("client_stat") else None
    out["client_stat"] = stat
    out["order_status"] = deal_status_as_order(str(out.get("status") or ""))
    if stat:
        out["check"] = check_public_out(out, stat)
    else:
        out["check"] = check_public_out(out, None)
    return out


async def _send_external_deals(text: str) -> None:
    chat_id, topic_id = external_deals_chat()
    if not chat_id or not settings.telegram_bot_token:
        return
    try:
        await send_ops_message(text, chat_id=chat_id, message_thread_id=topic_id)
    except Exception as exc:
        logger.warning("external deals notify failed: %s", exc)


async def _notify_if_still_pending(deal_id: int, pool) -> None:
    """Фоновая задача: через 15 мин проверить статус, при необходимости — уведомить."""
    await asyncio.sleep(EXTERNAL_DEAL_WARNING_ELAPSED_SEC)
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT d.id, d.status, d.client_pays_rub, e.name
                FROM external_deals d
                JOIN external_exchangers e ON e.id = d.exchanger_id
                WHERE d.id = $1
                """,
                deal_id,
            )
        if row and row["status"] == "awaiting_receipt":
            name = html.escape(str(row["name"] or ""))
            amount = float(row["client_pays_rub"] or 0)
            await _send_external_deals(
                f"⚠️ Внештатная сделка #{deal_id} · <b>{name}</b> · "
                f"{amount:,.0f} ₽ · {EXTERNAL_DEAL_WARNING_TEXT}"
            )
    except Exception as exc:
        logger.warning("_notify_if_still_pending failed: %s", exc)


# ---------------------------------------------------------------------------
# GET /api/operator/external/exchangers?q=
# ---------------------------------------------------------------------------

@router.get("/external/exchangers")
async def search_external_exchangers(
    q: str = Query(..., min_length=2, max_length=64),
    op: dict = Depends(get_current_operator),
):
    principal = await enrich_operator_permissions(op)
    require_permission(principal, PERM_EXTERNAL_VIEW)
    pool = await get_pool()
    async with pool.acquire() as conn:
        results = await search_exchangers(conn, q, limit=20)
    return {"exchangers": results}


# ---------------------------------------------------------------------------
# GET /api/operator/external/preview-deal
# ---------------------------------------------------------------------------

@router.get("/external/preview-deal")
async def preview_external_deal(
    amount_rub: float = Query(..., gt=0),
    exchanger_id: int = Query(..., gt=0),
    op: dict = Depends(get_current_operator),
):
    principal = await enrich_operator_permissions(op)
    require_permission(principal, PERM_EXTERNAL_PREVIEW)
    from routers.public import get_exchanger_rates_cached

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM external_exchangers WHERE id = $1 AND is_active = TRUE",
            exchanger_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Внештатник не найден")

    rates = await get_exchanger_rates_cached()
    usdt_rate_rub = float(rates.get("usdt") or 0)
    if usdt_rate_rub <= 0:
        raise HTTPException(status_code=503, detail="Курс USDT/RUB недоступен")

    operator_percent = float(op.get("percent") or 0)
    result = preview_deal(
        amount_rub,
        usdt_rate_rub,
        markup_pct=settings.ext_markup_pct,
        card_fee_pct=settings.ext_card_fee_pct,
        receive_fee_usd=settings.ext_receive_fee_usd,
        operator_percent=operator_percent,
    )
    if result is None:
        raise HTTPException(status_code=400, detail="Ошибка расчёта")
    result.pop("house_profit_usd", None)
    result.pop("payfast_fee_rub", None)
    result.pop("net_profit_rub", None)
    result.pop("reward_usdt", None)
    if not has_permission(principal, PERM_FINANCE_ANALYTICS):
        result.pop("operator_earnings_rub", None)
    return result


# ---------------------------------------------------------------------------
# POST /api/operator/external/exchangers/{id}/deals  — создать (pending)
# ---------------------------------------------------------------------------

class ExternalDealCreate(BaseModel):
    amount_rub: float
    crypto: str = "usdt"
    note: Optional[str] = None
    client_is_new: bool = True

    @field_validator("amount_rub")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("amount_rub must be > 0")
        return v

    @field_validator("crypto")
    @classmethod
    def _valid_crypto(cls, v: str) -> str:
        if v not in ("btc", "usdt", "trx", "ltc"):
            raise ValueError("crypto must be btc/usdt/trx/ltc")
        return v


@router.post("/external/exchangers/{exchanger_id}/deals", status_code=201)
async def create_external_deal_op(
    exchanger_id: int,
    body: ExternalDealCreate,
    op: dict = Depends(get_current_operator),
):
    principal = await enrich_operator_permissions(op)
    require_permission(principal, PERM_EXTERNAL_CREATE)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, int(op["id"]))
        op_name = str(op.get("username") or op.get("id") or "operator")
        try:
            result = await create_external_deal(
                conn,
                exchanger_id=exchanger_id,
                amount_rub=body.amount_rub,
                crypto=body.crypto,
                note=body.note,
                created_by=f"op:{op_name}",
                pending=True,
                operator_id=int(op["id"]),
                operator_percent=float(op.get("percent") or 0),
                client_is_new=body.client_is_new,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))

    deal_id = result["id"]
    exchanger_ctx = {
        "exchanger_name": result.get("exchanger_name"),
        "username": None,
    }
    pool = await get_pool()
    async with pool.acquire() as conn:
        stats = await fetch_exchanger_ops_stats(conn, exchanger_id)
    await _send_external_deals(
        format_deal_ops_notify(
            "created",
            result,
            exchanger_ctx,
            note="ожидает чек · создано оператором",
            ops_stats=stats,
        )
    )
    asyncio.create_task(_notify_if_still_pending(deal_id, pool))

    return _strip_finance_fields(result, principal)


# ---------------------------------------------------------------------------
# GET /api/operator/external/deals/pending
# ---------------------------------------------------------------------------

@router.get("/external/deals/pending")
async def list_pending_external_deals(
    op: dict = Depends(get_current_operator),
):
    principal = await enrich_operator_permissions(op)
    require_permission(principal, PERM_EXTERNAL_VIEW)
    op_id = int(op["id"])
    can_any = has_permission(principal, PERM_EXTERNAL_CONFIRM_ANY) or has_permission(
        principal, PERM_EXTERNAL_CANCEL_ANY
    )
    pool = await get_pool()
    async with pool.acquire() as conn:
        if can_any:
            rows = await conn.fetch(
                """
                SELECT d.id, d.exchanger_id, d.amount_rub, d.client_pays_rub,
                       d.principal_usdt, d.reward_usdt,
                       d.crypto, d.note, d.created_by, d.created_at, d.status,
                       d.receipt_submitted_at, d.merchant_order_id, d.client_is_new,
                       d.operator_id, d.operator_earnings_rub,
                       e.name AS exchanger_name, e.contact AS exchanger_contact,
                       e.is_trusted_client, e.auto_credit_on_payfast
                FROM external_deals d
                JOIN external_exchangers e ON e.id = d.exchanger_id
                WHERE d.status IN ('awaiting_receipt', 'pending')
                ORDER BY d.created_at ASC
                """
            )
        else:
            # Свои + сделки операторов, которые сейчас тоже на открытой смене.
            rows = await conn.fetch(
                """
                SELECT d.id, d.exchanger_id, d.amount_rub, d.client_pays_rub,
                       d.principal_usdt, d.reward_usdt,
                       d.crypto, d.note, d.created_by, d.created_at, d.status,
                       d.receipt_submitted_at, d.merchant_order_id, d.client_is_new,
                       d.operator_id, d.operator_earnings_rub,
                       e.name AS exchanger_name, e.contact AS exchanger_contact,
                       e.is_trusted_client, e.auto_credit_on_payfast
                FROM external_deals d
                JOIN external_exchangers e ON e.id = d.exchanger_id
                WHERE d.status IN ('awaiting_receipt', 'pending')
                  AND (
                    d.operator_id = $1
                    OR d.operator_id IS NULL
                    OR (
                      d.operator_id IS NOT NULL
                      AND EXISTS (
                        SELECT 1 FROM operator_shifts me
                        WHERE me.operator_id = $1 AND me.ended_at IS NULL
                      )
                      AND EXISTS (
                        SELECT 1 FROM operator_shifts peer
                        WHERE peer.operator_id = d.operator_id AND peer.ended_at IS NULL
                      )
                    )
                  )
                ORDER BY d.created_at ASC
                """,
                op_id,
            )
    deals = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat()
            elif hasattr(v, "__float__"):
                try:
                    d[k] = float(v)
                except Exception:
                    logger.debug("ignored non-fatal error", exc_info=True)
        from external_exchange_trust import deal_fields_from_row, trust_fields_from_row

        d.update(trust_fields_from_row(d))
        d.update(deal_fields_from_row(d))
        d["total_credit_usdt"] = (
            float(r["principal_usdt"] or 0) + float(r["reward_usdt"] or 0)
        )
        deals.append(_strip_finance_fields(d, principal))
    return {"deals": deals}


_OPS_DEAL_COLS = """
                SELECT d.id, d.exchanger_id, d.amount_rub, d.client_pays_rub,
                       d.principal_usdt, d.reward_usdt,
                       d.crypto, d.note, d.created_by, d.created_at, d.status,
                       d.receipt_submitted_at, d.receipt_file, d.merchant_order_id,
                       d.client_is_new, d.operator_id, d.operator_earnings_rub,
                       d.expires_at, d.customer_fingerprint, d.client_stat, d.client_stat_at,
                       d.required_receipt_type, d.payment_snapshot, d.callback_url,
                       d.client_transaction_id, d.paid_confirmed_at,
                       e.name AS exchanger_name, e.contact AS exchanger_contact,
                       e.is_trusted_client, e.auto_credit_on_payfast
                FROM external_deals d
                JOIN external_exchangers e ON e.id = d.exchanger_id
"""


def _scope_sql(can_any: bool) -> str:
    if can_any:
        return ""
    return """
                  AND (
                    d.operator_id = $1
                    OR d.operator_id IS NULL
                    OR (
                      d.operator_id IS NOT NULL
                      AND EXISTS (
                        SELECT 1 FROM operator_shifts me
                        WHERE me.operator_id = $1 AND me.ended_at IS NULL
                      )
                      AND EXISTS (
                        SELECT 1 FROM operator_shifts peer
                        WHERE peer.operator_id = d.operator_id AND peer.ended_at IS NULL
                      )
                    )
                  )
"""


# ---------------------------------------------------------------------------
# GET /api/operator/external/deals
# ---------------------------------------------------------------------------

@router.get("/external/deals")
async def list_external_deals(
    status: str = Query("open"),
    limit: int = Query(80, ge=1, le=200),
    offset: int = Query(0, ge=0),
    op: dict = Depends(get_current_operator),
):
    principal = await enrich_operator_permissions(op)
    require_permission(principal, PERM_EXTERNAL_VIEW)
    op_id = int(op["id"])
    can_any = has_permission(principal, PERM_EXTERNAL_CONFIRM_ANY) or has_permission(
        principal, PERM_EXTERNAL_CANCEL_ANY
    )
    pool = await get_pool()
    key = (status or "open").strip().lower()
    if key in ("open", "pending"):
        status_sql = "d.status IN ('awaiting_receipt', 'pending')"
    elif key in ("confirmed", "paid"):
        status_sql = "d.status = 'confirmed'"
    elif key in ("cancelled", "canceled"):
        status_sql = "d.status IN ('cancelled', 'canceled')"
    else:
        status_sql = "TRUE"
    scope = _scope_sql(can_any)
    async with pool.acquire() as conn:
        await _ensure_ops_deal_schema(conn)
        if can_any:
            rows = await conn.fetch(
                f"""
                {_OPS_DEAL_COLS}
                WHERE {status_sql}
                ORDER BY d.created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
        else:
            rows = await conn.fetch(
                f"""
                {_OPS_DEAL_COLS}
                WHERE {status_sql}
                {scope}
                ORDER BY d.created_at DESC
                LIMIT $2 OFFSET $3
                """,
                op_id,
                limit,
                offset,
            )
    deals = []
    for r in rows:
        d = _enrich_ops_deal(dict(r))
        from external_exchange_trust import deal_fields_from_row, trust_fields_from_row

        d.update(trust_fields_from_row(d))
        d.update(deal_fields_from_row(d))
        d["total_credit_usdt"] = float(d.get("principal_usdt") or 0) + float(
            d.get("reward_usdt") or 0
        )
        deals.append(_strip_finance_fields(d, principal))
    return {"deals": deals}


# ---------------------------------------------------------------------------
# GET /api/operator/external/deals/{deal_id}
# ---------------------------------------------------------------------------

@router.get("/external/deals/{deal_id}")
async def get_external_deal(
    deal_id: int,
    op: dict = Depends(get_current_operator),
):
    principal = await enrich_operator_permissions(op)
    require_permission(principal, PERM_EXTERNAL_VIEW)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ensure_ops_deal_schema(conn)
        row = await conn.fetchrow(
            f"""
            {_OPS_DEAL_COLS}
            WHERE d.id = $1
            """,
            int(deal_id),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Сделка не найдена")
        from external_client_stat import fetch_fingerprint_stat

        d = _enrich_ops_deal(dict(row))
        if not d.get("client_stat"):
            cached = await fetch_fingerprint_stat(
                conn, int(d.get("exchanger_id") or 0), d.get("fingerprint")
            )
            if cached:
                d["client_stat"] = cached
                from external_client_stat import check_public_out

                d["check"] = check_public_out(d, cached)
    from external_exchange_trust import deal_fields_from_row, trust_fields_from_row

    d.update(trust_fields_from_row(d))
    d.update(deal_fields_from_row(d))
    d["total_credit_usdt"] = float(d.get("principal_usdt") or 0) + float(
        d.get("reward_usdt") or 0
    )
    return _strip_finance_fields(d, principal)


@router.get("/external/deals/{deal_id}/receipt")
async def get_external_deal_receipt(
    deal_id: int,
    op: dict = Depends(get_current_operator),
):
    from receipt_serve import receipt_file_response

    principal = await enrich_operator_permissions(op)
    require_permission(principal, PERM_EXTERNAL_VIEW)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, operator_id, receipt_file FROM external_deals WHERE id = $1",
            int(deal_id),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Сделка не найдена")
        await _assert_deal_access(conn, principal, row, action="confirm")
        receipt_file = row.get("receipt_file")
    return receipt_file_response(receipt_file)


class ExternalDealExtend(BaseModel):
    minutes: int = EXTERNAL_DEAL_CLIENT_PAY_MIN

    @field_validator("minutes")
    @classmethod
    def _minutes(cls, v: int) -> int:
        n = int(v or EXTERNAL_DEAL_CLIENT_PAY_MIN)
        if n < 5 or n > 120:
            raise ValueError("minutes must be 5..120")
        return n


@router.post("/external/deals/{deal_id}/video")
async def request_deal_video(
    deal_id: int,
    op: dict = Depends(get_current_operator),
):
    from external_deal_payin import request_external_deal_video

    principal = await enrich_operator_permissions(op)
    require_permission(principal, PERM_EXTERNAL_CONFIRM)
    pool = await get_pool()
    op_name = str(op.get("username") or op.get("id") or "operator")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_active_shift(conn, int(op["id"]))
            deal_row = await conn.fetchrow(
                "SELECT * FROM external_deals WHERE id = $1 FOR UPDATE",
                int(deal_id),
            )
            if not deal_row:
                raise HTTPException(status_code=404, detail="Сделка не найдена")
            await _assert_deal_access(conn, principal, deal_row, action="confirm")
            result = await request_external_deal_video(conn, deal_id, source="operator")
            if not result:
                raise HTTPException(status_code=400, detail="Нельзя запросить видео в этом статусе")
    await _send_external_deals(
        format_deal_ops_notify(
            "video_requested",
            result,
            {"exchanger_name": result.get("exchanger_name"), "username": result.get("account_username")},
            note=f"запросил {html.escape(op_name)}",
        )
    )
    return _strip_finance_fields(_enrich_ops_deal(result), principal)


@router.post("/external/deals/{deal_id}/extend")
async def extend_deal(
    deal_id: int,
    body: ExternalDealExtend | None = None,
    op: dict = Depends(get_current_operator),
):
    from exchanger_deal_callback import schedule_exchanger_deal_callback

    principal = await enrich_operator_permissions(op)
    require_permission(principal, PERM_EXTERNAL_CONFIRM)
    minutes = (body.minutes if body else EXTERNAL_DEAL_CLIENT_PAY_MIN)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _ensure_ops_deal_schema(conn)
            await _require_active_shift(conn, int(op["id"]))
            deal_row = await conn.fetchrow(
                "SELECT * FROM external_deals WHERE id = $1 FOR UPDATE",
                int(deal_id),
            )
            if not deal_row:
                raise HTTPException(status_code=404, detail="Сделка не найдена")
            await _assert_deal_access(conn, principal, deal_row, action="confirm")
            status = str(deal_row["status"] or "")
            if status not in ("awaiting_receipt", "pending"):
                raise HTTPException(status_code=400, detail="Продление только для открытой сделки")
            now = datetime.now(timezone.utc)
            current = deal_row["expires_at"]
            if current is not None and getattr(current, "tzinfo", None) is None:
                current = current.replace(tzinfo=timezone.utc)
            base = current if isinstance(current, datetime) and current > now else now
            new_exp = base + timedelta(minutes=minutes)
            await conn.execute(
                "UPDATE external_deals SET expires_at = $1 WHERE id = $2",
                new_exp,
                int(deal_id),
            )
            refreshed = await conn.fetchrow(f"{_OPS_DEAL_COLS} WHERE d.id = $1", int(deal_id))
    deal = _enrich_ops_deal(dict(refreshed or deal_row))
    try:
        schedule_exchanger_deal_callback(dict(refreshed or deal_row), "extended")
    except Exception:
        logger.warning("extend callback failed deal=%s", deal_id, exc_info=True)
    return _strip_finance_fields(deal, principal)


# ---------------------------------------------------------------------------
# POST /api/operator/external/deals/{deal_id}/confirm
# ---------------------------------------------------------------------------

@router.post("/external/deals/{deal_id}/confirm")
async def confirm_deal(
    deal_id: int,
    op: dict = Depends(get_current_operator),
):
    principal = await enrich_operator_permissions(op)
    require_permission(principal, PERM_EXTERNAL_CONFIRM)
    pool = await get_pool()
    op_name = str(op.get("username") or op.get("id") or "operator")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_active_shift(conn, int(op["id"]))
            deal_row = await conn.fetchrow(
                "SELECT * FROM external_deals WHERE id = $1 FOR UPDATE",
                int(deal_id),
            )
            if not deal_row:
                raise HTTPException(status_code=404, detail="Сделка не найдена")
            await _assert_deal_access(conn, principal, deal_row, action="confirm")
            try:
                result = await confirm_external_deal(
                    conn, deal_id, confirmed_by=f"op:{op_name}"
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

    exchanger_name = html.escape(str(result.get("exchanger_name") or ""))
    total = float(result.get("total_credit_usdt") or 0)
    await _send_external_deals(
        f"✅ Внештатная сделка #{deal_id} подтверждена · <b>{exchanger_name}</b> · "
        f"+${total:.2f} на баланс · оп. {html.escape(op_name)}"
    )
    return _strip_finance_fields(result, principal)


# ---------------------------------------------------------------------------
# POST /api/operator/external/deals/{deal_id}/cancel
# ---------------------------------------------------------------------------

@router.post("/external/deals/{deal_id}/cancel")
async def cancel_deal(
    deal_id: int,
    op: dict = Depends(get_current_operator),
):
    principal = await enrich_operator_permissions(op)
    require_permission(principal, PERM_EXTERNAL_CANCEL)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_active_shift(conn, int(op["id"]))
            deal_row = await conn.fetchrow(
                "SELECT * FROM external_deals WHERE id = $1 FOR UPDATE",
                int(deal_id),
            )
            if not deal_row:
                raise HTTPException(status_code=404, detail="Сделка не найдена")
            await _assert_deal_access(conn, principal, deal_row, action="cancel")
            try:
                result = await cancel_external_deal(conn, deal_id)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

    op_name = str(op.get("username") or op.get("id") or "operator")
    await _send_external_deals(
        f"❌ Внештатная сделка #{deal_id} отменена · оп. {html.escape(op_name)}"
    )
    return _strip_finance_fields(result, principal)
