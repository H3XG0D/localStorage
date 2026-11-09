"""Владелец: выдача USDT операторам на смене."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from auth import get_current_finance_owner
from db import get_pool
from operator_usdt_issuance import shift_usdt_context

router = APIRouter()


class UsdtIssuanceCreate(BaseModel):
    operator_id: int
    amount_usdt: float
    note: Optional[str] = None

    @field_validator("amount_usdt")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("amount_usdt must be >= 0")
        return v


@router.get("/finance/operators-usdt-context")
async def operators_usdt_context(_owner=Depends(get_current_finance_owner)):
    """Операторы на смене + сделки с последней выдачи USDT."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        ops = await conn.fetch(
            """
            SELECT oa.id, oa.username, oa.display_name
            FROM operator_accounts oa
            WHERE oa.is_active
              AND EXISTS (
                SELECT 1 FROM operator_shifts os
                WHERE os.operator_id = oa.id AND os.ended_at IS NULL
              )
            ORDER BY oa.id
            """
        )
        items = []
        for op in ops:
            ctx = await shift_usdt_context(conn, int(op["id"]))
            if not ctx:
                continue
            items.append(
                {
                    "operator_id": int(op["id"]),
                    "username": op["username"],
                    "display_name": op.get("display_name"),
                    **ctx,
                }
            )
    return {"operators": items}


@router.post("/finance/usdt-issuance", status_code=201)
async def create_usdt_issuance(
    body: UsdtIssuanceCreate,
    owner=Depends(get_current_finance_owner),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        shift = await conn.fetchrow(
            """
            SELECT id FROM operator_shifts
            WHERE operator_id = $1 AND ended_at IS NULL
            ORDER BY started_at DESC
            LIMIT 1
            """,
            body.operator_id,
        )
        if not shift:
            raise HTTPException(
                status_code=400,
                detail="Оператор не на смене — выдача USDT только во время смены",
            )
        row = await conn.fetchrow(
            """
            INSERT INTO operator_usdt_issuances
                (operator_id, shift_id, amount_usdt, recorded_by, note)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, operator_id, shift_id, amount_usdt, note, created_at
            """,
            body.operator_id,
            shift["id"],
            body.amount_usdt,
            owner.get("id"),
            (body.note or "").strip() or None,
        )
    created = dict(row)
    if hasattr(created.get("created_at"), "isoformat"):
        created["created_at"] = created["created_at"].isoformat()
    created["amount_usdt"] = float(created["amount_usdt"])
    return {"issuance": created}


@router.get("/finance/usdt-issuances")
async def list_usdt_issuances(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 100,
    _owner=Depends(get_current_finance_owner),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT i.id, i.operator_id, i.shift_id, i.amount_usdt, i.note, i.created_at,
                   oa.username, oa.display_name
            FROM operator_usdt_issuances i
            JOIN operator_accounts oa ON oa.id = i.operator_id
            WHERE ($1::date IS NULL OR i.created_at::date >= $1)
              AND ($2::date IS NULL OR i.created_at::date <= $2)
            ORDER BY i.created_at DESC
            LIMIT $3
            """,
            date_from,
            date_to,
            min(limit, 500),
        )
    items = []
    for r in rows:
        d = dict(r)
        if hasattr(d.get("created_at"), "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        d["amount_usdt"] = float(d["amount_usdt"])
        items.append(d)
    return {"issuances": items}
