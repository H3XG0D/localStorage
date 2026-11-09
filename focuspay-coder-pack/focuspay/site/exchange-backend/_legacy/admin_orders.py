from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_admin, get_current_finance_viewer
from buy_crypto_amount import expected_crypto_for_paid_rub, max_crypto_for_paid_rub
from db import get_pool
from service_profit import order_service_profit, CARD_FEE_DEFAULT

router = APIRouter()

VALID_STATUSES = {
    "CREATED", "AWAITING_CHECK", "PENDING", "COMPLETED",
    "PAID", "FAILED", "CANCELED", "EXPIRED", "DISPUTE", "OPERATOR_PENDING",
}

STATUS_LABELS = {
    "CREATED": "Создана",
    "AWAITING_CHECK": "Ожидает чек",
    "PENDING": "На проверке",
    "COMPLETED": "Выполнена",
    "PAID": "Оплачена",
    "FAILED": "Ошибка",
    "CANCELED": "Отменена",
    "EXPIRED": "Истекла",
    "DISPUTE": "Спор",
    "OPERATOR_PENDING": "Ожидает оператора",
}


def _order_out(row) -> dict:
    r = dict(row)
    return {
        "id": r["id"],
        "order_id": r["order_id"],
        "user_id": r["user_id"],
        "status": r["status"],
        "status_label": STATUS_LABELS.get(r["status"], r["status"]),
        "direction": r["direction"],
        "crypto": r["crypto"],
        "crypto_amount": r["crypto_amount"],
        "fiat_amount": r["fiat_amount"],
        "rate": r["rate"],
        "requisites": r["requisites"],
        "sub_token": r.get("sub_token"),
        "merchant_order_id": r.get("merchant_order_id"),
        "promo_code": r.get("promo_code"),
        "promo_bonus_percent": r.get("promo_bonus_percent"),
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
        "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
        "cashback_applied_rub": float(r.get("cashback_applied_rub") or 0),
        "card_fee_pct": float(r["card_fee_pct"]) if r.get("card_fee_pct") is not None else None,
        "payout_tx_hash": r.get("payout_tx_hash"),
    }


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
        fee = float(o["card_fee_pct"]) if o.get("card_fee_pct") is not None else CARD_FEE_DEFAULT
        out["service_profit_rub"] = order_service_profit(
            "buy",
            o.get("crypto") or "",
            float(o.get("fiat_amount") or 0),
            crypto,
            float(o.get("rate") or 0),
            cashback_applied_rub=float(o.get("cashback_applied_rub") or 0),
            card_fee_pct=fee,
        )
    return out


@router.get("/orders")
async def list_orders(
    status: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    crypto: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin=Depends(get_current_admin),
):
    conditions = ["1=1"]
    params: list = []
    idx = 1

    if status:
        conditions.append(f"status = ${idx}")
        params.append(status.upper())
        idx += 1
    if direction:
        conditions.append(f"direction = ${idx}")
        params.append(direction.lower())
        idx += 1
    if crypto:
        conditions.append(f"LOWER(crypto) LIKE ${idx}")
        params.append(f"%{crypto.lower()}%")
        idx += 1
    if search:
        conditions.append(f"(order_id ILIKE ${idx} OR requisites ILIKE ${idx} OR user_id::text = ${idx})")
        params.append(f"%{search}%")
        idx += 1
    if user_id is not None:
        conditions.append(f"user_id = ${idx}")
        params.append(user_id)
        idx += 1

    where = " AND ".join(conditions)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM orders WHERE {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}",
            *params,
            limit,
            offset,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*)::int FROM orders WHERE {where}", *params
        )

    return {
        "orders": [_order_out(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/orders/{order_id}")
async def get_order(order_id: str, _admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM orders WHERE order_id = $1", order_id)
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    data = _order_out(row)
    if (row["direction"] or "").lower() == "buy":
        data["payout_audit"] = _payout_audit(dict(row))
    return data


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

    from bot_status_bridge import update_order_status as bot_set_status

    if not await bot_set_status(order_id, new_status):
        raise HTTPException(
            status_code=409,
            detail=f"Status transition to {new_status} is not allowed",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM orders WHERE order_id = $1 FOR UPDATE", order_id
            )
            if row and new_status == "PAID":
                from operator_payroll_split import ensure_order_participant, ensure_order_payroll_split

                await conn.execute(
                    """
                    UPDATE orders
                    SET payroll_model = 'role_split', payroll_split_required = TRUE,
                        updated_at = now()
                    WHERE order_id = $1
                    """,
                    order_id,
                )
                if row.get("intake_operator_id"):
                    await ensure_order_participant(
                        conn, order_id, int(row["intake_operator_id"]), "client", "intake", None
                    )
                if row.get("finance_operator_id"):
                    await ensure_order_participant(
                        conn, order_id, int(row["finance_operator_id"]), "finance", "payout", None
                    )
                await ensure_order_payroll_split(conn, order_id)
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return _order_out(row)
