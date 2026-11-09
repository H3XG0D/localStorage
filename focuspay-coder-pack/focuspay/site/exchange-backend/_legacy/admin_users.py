from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_admin
from buyer_profile_service import build_buyer_profile
from db import get_pool
from finance_access import can_view_finance_admin

router = APIRouter()


@router.get("/users")
async def list_users(
    search: Optional[str] = Query(None),
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

    where = " AND ".join(conditions)
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
                COUNT(o.id)::int        AS total_orders,
                COUNT(CASE WHEN o.status IN ('PAID','COMPLETED') THEN 1 END)::int AS paid_orders,
                COALESCE(SUM(CASE WHEN o.status IN ('PAID','COMPLETED') THEN o.fiat_amount END), 0)::float AS total_fiat
            FROM bot_users u
            LEFT JOIN orders o ON o.user_id = u.user_id
            WHERE {where}
            GROUP BY u.user_id
            ORDER BY u.last_seen_at DESC
            LIMIT ${idx} OFFSET ${idx+1}
            """,
            *params,
            limit,
            offset,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*)::int FROM bot_users u WHERE {where}", *params
        )

    return {
        "users": [
            {
                "user_id": r["user_id"],
                "username": r["username"],
                "first_name": r["first_name"],
                "first_seen_at": r["first_seen_at"].isoformat() if r["first_seen_at"] else None,
                "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None,
                "total_orders": r["total_orders"],
                "paid_orders": r["paid_orders"],
                "total_fiat": round(r["total_fiat"], 2),
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
