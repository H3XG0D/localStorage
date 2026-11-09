"""Админ: заявки операторов на вывод из общего пула зарплаты."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_finance_viewer
from db import get_pool
from operator_payroll_pool import (
    format_payout_admin_message,
    pool_balance,
    process_request_paid,
    process_request_rejected,
)
from telegram_notify import edit_finance_owner_message

router = APIRouter()


@router.get("/operator-payroll/balance")
async def admin_pool_balance(_admin=Depends(get_current_finance_viewer)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await pool_balance(conn)


@router.get("/operator-payroll/requests")
async def list_payout_requests(
    status: str = "pending",
    limit: int = 50,
    _admin=Depends(get_current_finance_viewer),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.*, o.username, o.display_name
            FROM operator_payout_requests r
            JOIN operator_accounts o ON o.id = r.operator_id
            WHERE ($1 = '' OR r.status = $1)
            ORDER BY r.created_at DESC
            LIMIT $2
            """,
            status if status in ("pending", "paid", "rejected", "canceled") else "pending",
            limit,
        )
    out = []
    for r in rows:
        d = dict(r)
        for k in ("created_at", "processed_at"):
            v = d.get(k)
            if v and hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        d["operator_name"] = d.get("display_name") or d.get("username")
        out.append(d)
    return {"requests": out}


class ProcessNote(BaseModel):
    note: str | None = None


@router.post("/operator-payroll/requests/{request_id}/paid")
async def mark_paid(
    request_id: int,
    body: ProcessNote = ProcessNote(),
    _admin=Depends(get_current_finance_viewer),
):
    req = await process_request_paid(request_id, note=body.note)
    if not req:
        raise HTTPException(status_code=404, detail="Заявка не найдена или уже обработана")

    pool = await get_pool()
    async with pool.acquire() as conn:
        op = await conn.fetchrow(
            "SELECT username, display_name FROM operator_accounts WHERE id = $1",
            req["operator_id"],
        )
    name = (op["display_name"] or op["username"]) if op else str(req["operator_id"])

    if req.get("admin_message_id"):
        msg = format_payout_admin_message(req, name)
        await edit_finance_owner_message(
            int(req["admin_message_id"]),
            f"{msg}\n\n✅ <b>Выплачено</b>",
            reply_markup=None,
        )
    return {"request": req}


@router.post("/operator-payroll/requests/{request_id}/reject")
async def mark_rejected(
    request_id: int,
    body: ProcessNote = ProcessNote(),
    _admin=Depends(get_current_finance_viewer),
):
    req = await process_request_rejected(request_id, note=body.note)
    if not req:
        raise HTTPException(status_code=404, detail="Заявка не найдена или уже обработана")

    if req.get("admin_message_id"):
        pool = await get_pool()
        async with pool.acquire() as conn:
            op = await conn.fetchrow(
                "SELECT username, display_name FROM operator_accounts WHERE id = $1",
                req["operator_id"],
            )
        name = (op["display_name"] or op["username"]) if op else str(req["operator_id"])
        msg = format_payout_admin_message(req, name)
        await edit_finance_owner_message(
            int(req["admin_message_id"]),
            f"{msg}\n\n❌ <b>Отклонено</b>",
            reply_markup=None,
        )
    return {"request": req}
