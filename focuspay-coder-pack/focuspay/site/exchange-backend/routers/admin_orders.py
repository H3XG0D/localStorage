from typing import Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from auth import get_current_admin, get_current_finance_viewer
from receipt_serve import receipt_file_response
from buy_crypto_amount import expected_crypto_for_paid_rub, max_crypto_for_paid_rub
from db import get_pool
from finance_access import can_view_finance_admin
from economics_snapshot import order_economics
from admin_order_close import (
    admin_cancel_awaiting_check_error,
    cancel_user_telegram_text,
)
from admin_orders_list import (
    ORDERS_WITH_BUYER_SQL,
    fetch_orders_archive,
    partner_option_from_row,
    serialize_admin_order,
)
from order_verification import (
    assemble_order_verification,
    fetch_bot_user_reviews,
)

router = APIRouter()
logger = logging.getLogger("admin_orders")

_ORDERS_WITH_BUYER_SQL = ORDERS_WITH_BUYER_SQL

VALID_STATUSES = {
    "CREATED", "AWAITING_CHECK", "PENDING", "COMPLETED",
    "PAID", "FAILED", "CANCELED", "EXPIRED", "DISPUTE", "OPERATOR_PENDING",
}


def _order_out(row, *, include_finance: bool = False) -> dict:
    return serialize_admin_order(row, include_finance=include_finance)


def _payout_audit(row: dict) -> dict:
    """Предупреждение, если крипта в заявке больше оплаченной суммы."""
    o = dict(row)
    cap = max_crypto_for_paid_rub(o)
    crypto = float(o.get("crypto_amount") or 0)
    out = {"crypto_ok": True, "crypto_cap": cap}
    if cap is not None and crypto > cap * 1.001:
        out["crypto_ok"] = False
        out["expected_crypto"] = expected_crypto_for_paid_rub(
            fiat_amount=float(o.get("fiat_amount") or 0),
            rate=float(o.get("rate") or 0),
            crypto=str(o.get("crypto") or ""),
            cashback_applied_rub=float(o.get("cashback_applied_rub") or 0),
        )
        out["service_profit_rub"] = order_economics(o)["service_profit_rub"]
    return out


@router.get("/orders")
async def list_orders(
    status: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    crypto: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    origin: Optional[str] = Query(
        None, description="manual | auto — ручные / автоматические (Payfast)"
    ),
    user_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    partner_id: Optional[int] = Query(
        None, ge=1, description="promo_campaigns.id — заявки клиентов этого партнёра"
    ),
    merchant_id: Optional[str] = Query(None, description="фильтр по мерчанту (payfast, custom_treugol, ...)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        data = await fetch_orders_archive(
            conn,
            status=status,
            direction=direction,
            crypto=crypto,
            search=search,
            origin=origin,
            user_id=user_id,
            partner_id=partner_id,
            date_from=date_from,
            date_to=date_to,
            merchant_id=merchant_id,
            limit=limit,
            offset=offset,
        )
        preview_ctx = await _safe_preview_context(conn, (r["user_id"] for r in data["rows"]))

    include_finance = can_view_finance_admin(admin)
    return {
        "orders": [
            _with_preview(_order_out(r, include_finance=include_finance), r, preview_ctx)
            for r in data["rows"]
        ],
        "total": data["total"],
        "limit": limit,
        "offset": offset,
        "partner_options": [partner_option_from_row(r) for r in data["partner_rows"]],
    }


@router.get("/orders/{order_id}")
async def get_order(order_id: str, admin=Depends(get_current_admin)):
    include_finance = can_view_finance_admin(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            {_ORDERS_WITH_BUYER_SQL}
            WHERE o.order_id = $1
            """,
            order_id,
        )
        if row:
            preview_ctx = await _safe_preview_context(conn, [row["user_id"]])
            live_checks = await _safe_live_checks(conn, row)
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    data = _with_preview(_order_out(row, include_finance=include_finance), row, preview_ctx)
    pf_check = await _safe_payfast_check(row)
    if pf_check and live_checks is not None:
        live_checks = [pf_check] + live_checks
    if data.get("autopay_preview") and live_checks:
        from auto_preview import with_live_checks

        with_live_checks(data["autopay_preview"], live_checks, dict(row))
    if (row["direction"] or "").lower() == "buy":
        data["payout_audit"] = _payout_audit(dict(row))
    return data


async def _safe_preview_context(conn, user_ids):
    from auto_preview import build_preview_context

    try:
        return await build_preview_context(conn, list(user_ids))
    except Exception:
        # Колонка override появляется с миграцией автопилота; без неё — без оценки.
        logger.warning("autopay preview context failed", exc_info=True)
        return None


async def _safe_live_checks(conn, row) -> list[dict] | None:
    if (row["direction"] or "").lower() != "buy":
        return None
    from auto_preview import live_payout_checks

    try:
        return await live_payout_checks(conn)
    except Exception:
        logger.warning("autopay live checks failed", exc_info=True)
        return None


async def _safe_payfast_check(row) -> dict | None:
    if (row["direction"] or "").lower() != "buy":
        return None
    from auto_preview import live_payfast_check

    try:
        return await live_payfast_check(dict(row))
    except Exception:
        logger.warning("autopay payfast check failed", exc_info=True)
        return {"key": "payfast_live", "ok": False, "detail": "payfast_api_error"}


def _with_preview(out: dict, row, ctx) -> dict:
    if ctx is None:
        return out
    from auto_preview import preview_order_autopay

    try:
        out["autopay_preview"] = preview_order_autopay(dict(row), ctx)
    except Exception:
        logger.warning("autopay preview failed order=%s", out.get("order_id"), exc_info=True)
    return out


@router.get("/orders/{order_id}/verification")
async def get_order_verification(order_id: str, _admin=Depends(get_current_admin)):
    """Карточка проверок: чек, риск, повторы. Только чтение, без записи snapshot."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            {_ORDERS_WITH_BUYER_SQL}
            WHERE o.order_id = $1
            """,
            order_id,
        )
        bot_user = None
        if row and row["user_id"]:
            bot_user = await fetch_bot_user_reviews(conn, int(row["user_id"]))
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    payout = None
    if (row["direction"] or "").lower() == "buy":
        payout = _payout_audit(dict(row))
    return await assemble_order_verification(dict(row), bot_user=bot_user, payout_audit=payout)


@router.get("/orders/{order_id}/receipt")
async def get_order_receipt(order_id: str, _admin=Depends(get_current_admin)):
    """Отдать файл чека/видео, загруженного клиентом, для просмотра в админке."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        receipt_file = await conn.fetchval(
            "SELECT receipt_file FROM orders WHERE order_id = $1", order_id
        )
    return receipt_file_response(receipt_file)


@router.post("/orders/{order_id}/sync-crypto-to-payin")
async def sync_crypto_to_payin(
    order_id: str,
    _admin=Depends(get_current_finance_viewer),
):
    """Подогнать crypto_amount под фактический payin (для испорченных заявок)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM orders WHERE order_id = $1 FOR UPDATE",
                order_id.strip().upper(),
            )
            if not row:
                raise HTTPException(status_code=404, detail="Order not found")
            if (row["direction"] or "").lower() != "buy":
                raise HTTPException(status_code=400, detail="Only BUY orders")
            if row["status"] == "PAID":
                raise HTTPException(
                    status_code=400,
                    detail="Заявка уже PAID — меняйте вручную только с пониманием рисков",
                )
            expected = expected_crypto_for_paid_rub(
                fiat_amount=float(row["fiat_amount"] or 0),
                rate=float(row["rate"] or 0),
                crypto=str(row["crypto"] or ""),
                cashback_applied_rub=float(row["cashback_applied_rub"] or 0),
                exchange_discount_applied_rub=float(
                    row["exchange_discount_applied_rub"] or 0
                ),
            )
            if expected is None:
                raise HTTPException(status_code=400, detail="Cannot compute crypto from order")
            old = float(row["crypto_amount"] or 0)
            await conn.execute(
                "UPDATE orders SET crypto_amount = $1, updated_at = now() WHERE order_id = $2",
                expected,
                order_id.strip().upper(),
            )
            refreshed = await conn.fetchrow(
                "SELECT * FROM orders WHERE order_id = $1", order_id.strip().upper()
            )
    return {
        "order": _order_out(refreshed),
        "previous_crypto_amount": old,
        "new_crypto_amount": expected,
    }


@router.patch("/orders/{order_id}/status")
async def update_order_status(
    order_id: str,
    body: dict,
    _admin=Depends(get_current_admin),
):
    new_status = (body.get("status") or "").upper()
    if new_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Allowed: {', '.join(VALID_STATUSES)}",
        )

    if new_status == "PAID":
        pool = await get_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT direction FROM orders WHERE order_id = $1", order_id
            )
        if existing and (existing["direction"] or "").lower() == "buy":
            raise HTTPException(
                status_code=400,
                detail=(
                    "BUY-заявку нельзя пометить PAID вручную. Используйте "
                    "подтверждение выплаты с tx-хэшем (эндпоинт payout)."
                ),
            )

    from bot_status_bridge import update_order_status as bot_set_status

    if not await bot_set_status(order_id, new_status):
        raise HTTPException(
            status_code=409,
            detail=f"Status transition to {new_status} is not allowed",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1", order_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return _order_out(row)


class AdminPayoutRequest(BaseModel):
    tx_hash: str

    @field_validator("tx_hash")
    @classmethod
    def _tx_hash(cls, v: str) -> str:
        t = (v or "").strip()
        if not t:
            raise ValueError("Укажите hash транзакции")
        return t


class AdminCancelRequest(BaseModel):
    reason: str = Field(..., max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        t = (v or "").strip()
        if len(t) < 3:
            raise ValueError("Укажите причину отмены (минимум 3 символа)")
        return t


def _raise_admin_payout_error(err: str | None) -> None:
    if err == "not_found":
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if err == "already_paid":
        raise HTTPException(status_code=409, detail="Уже подтверждено в другом месте")
    if err == "invalid_tx":
        raise HTTPException(status_code=400, detail="Некорректный hash транзакции")
    if err == "wrong_status":
        raise HTTPException(
            status_code=400,
            detail="Подтверждение выплаты доступно только для BUY в статусе «ожидает чек»",
        )
    if err == "not_buy":
        raise HTTPException(status_code=400, detail="Только для BUY-заявок")
    if err == "crypto_exceeds_paid":
        raise HTTPException(
            status_code=400,
            detail=(
                "Сумма крипты в заявке больше оплаченной части. "
                "Исправьте заявку или пересчитайте крипту — выплата заблокирована."
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


@router.post("/orders/{order_id}/payout")
async def confirm_awaiting_check_payout(
    order_id: str,
    body: AdminPayoutRequest,
    admin: dict = Depends(get_current_admin),
):
    from bot_status_bridge import confirm_awaiting_check_buy_payout

    admin_id = admin.get("id")
    ok, err, _paid = await confirm_awaiting_check_buy_payout(
        order_id.strip(),
        tx_hash=body.tx_hash,
        actor=f"admin:{admin_id}",
    )
    if not ok:
        _raise_admin_payout_error(err)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"{_ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
            order_id.strip(),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    return _order_out(row)


@router.post("/orders/{order_id}/cancel")
async def cancel_awaiting_check_order(
    order_id: str,
    body: AdminCancelRequest,
    admin: dict = Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1",
            order_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        gate = admin_cancel_awaiting_check_error(row.get("status"))
        if gate == "already_canceled":
            return _order_out(row)
        if gate == "already_closed":
            raise HTTPException(
                status_code=400,
                detail="Оплаченную или завершённую заявку нельзя отменить этим действием",
            )
        if gate:
            raise HTTPException(
                status_code=400,
                detail="Отмена с этой кнопки доступна только для статуса «ожидает чек»",
            )
        await conn.execute(
            """
            UPDATE orders
            SET cancel_reason = $1, canceled_by = $2, updated_at = now()
            WHERE order_id = $3
            """,
            body.reason,
            admin.get("id"),
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

            await send_user_message(
                int(buyer),
                cancel_user_telegram_text(order_id, body.reason),
            )
        except Exception as e:
            logger.warning("notify cancel order=%s: %s", order_id, e)

    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1",
            order_id,
        )
    if not updated:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    return _order_out(updated)
