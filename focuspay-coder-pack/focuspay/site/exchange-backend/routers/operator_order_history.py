"""Архив всех заявок для старших операторов: только чтение, без прибыли."""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from admin_orders_list import (
    fetch_order_archive_row,
    fetch_orders_archive,
    partner_option_from_row,
    serialize_admin_order,
)
from auth import get_current_operator
from db import get_pool
from permissions import PERM_ORDERS_HISTORY, enrich_operator_permissions, require_permission

router = APIRouter()


async def _require_orders_history(op: dict) -> dict:
    enriched = await enrich_operator_permissions(op)
    return require_permission(enriched, PERM_ORDERS_HISTORY)


def _history_order_out(row) -> dict:
    out = serialize_admin_order(row, include_finance=False)
    out.pop("service_profit_rub", None)
    return out


@router.get("/orders/history")
async def list_order_history(
    op: dict = Depends(get_current_operator),
    status: Annotated[Optional[str], Query()] = None,
    direction: Annotated[Optional[str], Query()] = None,
    crypto: Annotated[Optional[str], Query()] = None,
    search: Annotated[Optional[str], Query()] = None,
    origin: Annotated[Optional[str], Query()] = None,
    user_id: Annotated[Optional[int], Query()] = None,
    date_from: Annotated[Optional[str], Query()] = None,
    date_to: Annotated[Optional[str], Query()] = None,
    partner_id: Annotated[Optional[int], Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    await _require_orders_history(op)
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
            limit=limit,
            offset=offset,
            include_counts=True,
        )
    return {
        "orders": [_history_order_out(r) for r in data["rows"]],
        "total": data["total"],
        "limit": limit,
        "offset": offset,
        "counts": data["counts"] or {},
        "partner_options": [partner_option_from_row(r) for r in data["partner_rows"]],
    }


@router.get("/orders/history/{order_id}")
async def get_order_history_item(
    order_id: str,
    op: dict = Depends(get_current_operator),
):
    await _require_orders_history(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await fetch_order_archive_row(conn, order_id)
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return _history_order_out(row)
