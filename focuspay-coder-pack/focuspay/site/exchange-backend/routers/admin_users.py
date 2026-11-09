from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_admin
from bot_user_avatars import bot_user_avatar_public_url
from buyer_profile_service import build_buyer_profile
from db import get_pool
from finance_access import can_view_finance_admin

router = APIRouter()


# Канал пользователя: где он зарегистрирован/активен.
#   bot      — только бот (нет аккаунта на сайте)
#   web      — только сайт (регистрация по паролю, синтетический отрицательный id)
#   web+bot  — сайт через Telegram (есть и веб-аккаунт, и Telegram)
_CHANNEL_SQL = """
        CASE
            WHEN wu.id IS NULL THEN 'bot'
            WHEN wu.telegram_user_id IS NOT NULL THEN 'web+bot'
            ELSE 'web'
        END
"""

_CHANNEL_FILTERS = {
    "bot": "wu.id IS NULL",
    "web": "wu.id IS NOT NULL AND wu.telegram_user_id IS NULL",
    "web+bot": "wu.telegram_user_id IS NOT NULL",
}

_SORT_COLUMNS = {
    "last_seen_at": "u.last_seen_at",
    "first_seen_at": "u.first_seen_at",
    "last_order_at": "last_order_at",
    "total_orders": "total_orders",
    "paid_orders": "paid_orders",
    "total_fiat": "total_fiat",
    "conversion_pct": "conversion_pct",
    "user_id": "u.user_id",
    "username": "u.username",
}


@router.get("/users")
async def list_users(
    search: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    sort_by: str = Query("last_seen_at"),
    sort_dir: str = Query("desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin=Depends(get_current_admin),
):
    conditions = ["1=1"]
    params: list = []
    idx = 1

    if search:
        conditions.append(
            f"(u.user_id::text ILIKE ${idx} OR u.username ILIKE ${idx} OR u.first_name ILIKE ${idx})"
        )
        params.append(f"%{search}%")
        idx += 1

    if channel and channel in _CHANNEL_FILTERS:
        conditions.append(_CHANNEL_FILTERS[channel])

    order_col = _SORT_COLUMNS.get(sort_by, "u.last_seen_at")
    order_dir = "ASC" if sort_dir.lower() == "asc" else "DESC"

    where = " AND ".join(conditions)
    from_join = """
        FROM bot_users u
        LEFT JOIN web_users wu
            ON wu.telegram_user_id = u.user_id OR wu.client_user_id = u.user_id
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                u.user_id,
                u.username,
                u.first_name,
                u.first_seen_at,
                u.last_seen_at,
                wu.email AS web_email,
                {_CHANNEL_SQL} AS channel,
                COUNT(o.id)::int        AS total_orders,
                COUNT(CASE WHEN o.status IN ('PAID','COMPLETED') THEN 1 END)::int AS paid_orders,
                COALESCE(SUM(CASE WHEN o.status IN ('PAID','COMPLETED') THEN o.fiat_amount END), 0)::float AS total_fiat,
                MAX(o.created_at)       AS last_order_at,
                COUNT(CASE WHEN o.direction = 'buy' AND o.merchant_order_id IS NOT NULL THEN 1 END)::int AS payfast_taken,
                COUNT(CASE WHEN o.direction = 'buy' AND o.merchant_order_id IS NOT NULL AND o.status = 'PAID' THEN 1 END)::int AS payfast_paid,
                COUNT(CASE WHEN o.direction = 'buy' AND o.merchant_order_id IS NOT NULL AND o.status IN ('CANCELED','EXPIRED') THEN 1 END)::int AS payfast_failed,
                CASE
                    WHEN COUNT(CASE WHEN o.direction = 'buy' AND o.merchant_order_id IS NOT NULL AND o.status IN ('PAID','CANCELED','EXPIRED') THEN 1 END) = 0
                    THEN NULL
                    ELSE ROUND(
                        100.0 * COUNT(CASE WHEN o.direction = 'buy' AND o.merchant_order_id IS NOT NULL AND o.status = 'PAID' THEN 1 END)::numeric
                        / NULLIF(COUNT(CASE WHEN o.direction = 'buy' AND o.merchant_order_id IS NOT NULL AND o.status IN ('PAID','CANCELED','EXPIRED') THEN 1 END), 0)
                    , 1)
                END AS conversion_pct
            {from_join}
            LEFT JOIN orders o ON o.user_id = u.user_id
            WHERE {where}
            GROUP BY u.user_id, wu.id, wu.email, wu.telegram_user_id
            ORDER BY {order_col} {order_dir} NULLS LAST
            LIMIT ${idx} OFFSET ${idx+1}
            """,
            *params,
            limit,
            offset,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(DISTINCT u.user_id)::int {from_join} WHERE {where}",
            *params,
        )

    return {
        "users": [
            {
                "user_id": r["user_id"],
                "username": r["username"],
                "first_name": r["first_name"],
                "avatar_url": bot_user_avatar_public_url(r["user_id"]),
                "channel": r["channel"],
                "web_email": r["web_email"],
                "first_seen_at": r["first_seen_at"].isoformat() if r["first_seen_at"] else None,
                "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None,
                "total_orders": r["total_orders"],
                "paid_orders": r["paid_orders"],
                "total_fiat": round(r["total_fiat"], 2),
                "last_order_at": r["last_order_at"].isoformat() if r["last_order_at"] else None,
                "payfast_taken": int(r["payfast_taken"] or 0),
                "payfast_paid": int(r["payfast_paid"] or 0),
                "payfast_failed": int(r["payfast_failed"] or 0),
                "conversion_pct": float(r["conversion_pct"]) if r["conversion_pct"] is not None else None,
            }
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/users/{user_id}")
async def get_user_profile(
    user_id: int,
    _admin=Depends(get_current_admin),
):
    include_finance = can_view_finance_admin(_admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        profile = await build_buyer_profile(
            conn,
            user_id,
            mode="admin",
            include_finance=include_finance,
        )
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    return profile
