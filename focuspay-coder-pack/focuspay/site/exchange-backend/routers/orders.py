from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user, resolve_client_user_id, user_to_dict
from db import get_pool

router = APIRouter()

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
}


_ORDERS_SELECT = """
    SELECT o.*,
           COALESCE(o.cashback_applied_rub, 0)::float AS cashback_applied_rub,
           (
               SELECT amount_rub FROM user_cashback_ledger l
               WHERE l.user_id = o.user_id AND l.type = 'accrual' AND l.order_id = o.order_id
               LIMIT 1
           ) AS cashback_accrued_rub
    FROM orders o
"""


def _order_out(row) -> dict:
    r = dict(row)
    applied = float(r.get("cashback_applied_rub") or 0)
    accrued_raw = r.get("cashback_accrued_rub")
    accrued = float(accrued_raw) if accrued_raw is not None else 0.0
    return {
        "id": r["id"],
        "order_id": r["order_id"],
        "status": r["status"],
        "status_label": STATUS_LABELS.get(r["status"], r["status"]),
        "direction": r["direction"],
        "crypto": r["crypto"],
        "crypto_amount": r["crypto_amount"],
        "fiat_amount": r["fiat_amount"],
        "rate": r["rate"],
        "requisites": r["requisites"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
        "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
        "promo_code": r.get("promo_code"),
        "promo_bonus_percent": r.get("promo_bonus_percent"),
        "cashback_applied_rub": round(applied, 2),
        "cashback_accrued_rub": round(accrued, 2) if accrued > 0 else 0,
    }


@router.get("/orders")
async def get_my_orders(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    client_id = resolve_client_user_id(current_user)

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            {_ORDERS_SELECT}
            WHERE o.user_id = $1
            ORDER BY o.created_at DESC
            LIMIT $2 OFFSET $3
            """,
            client_id,
            limit,
            offset,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*)::int FROM orders WHERE user_id = $1", client_id
        )

    return {
        "orders": [_order_out(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/orders/{order_id}")
async def get_my_order(order_id: str, current_user: dict = Depends(get_current_user)):
    client_id = resolve_client_user_id(current_user)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            {_ORDERS_SELECT}
            WHERE o.order_id = $1 AND o.user_id = $2
            """,
            order_id,
            client_id,
        )

    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return _order_out(row)


@router.get("/profile")
async def get_profile(current_user: dict = Depends(get_current_user)):
    client_id = resolve_client_user_id(current_user)
    stats = {"total_orders": 0, "completed_orders": 0}

    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*)::int FROM orders WHERE user_id = $1", client_id
        )
        completed = await conn.fetchval(
            "SELECT COUNT(*)::int FROM orders WHERE user_id = $1 AND status IN ('COMPLETED', 'PAID')",
            client_id,
        )
    stats = {"total_orders": total or 0, "completed_orders": completed or 0}

    return {
        "user": user_to_dict(current_user),
        "stats": stats,
    }
