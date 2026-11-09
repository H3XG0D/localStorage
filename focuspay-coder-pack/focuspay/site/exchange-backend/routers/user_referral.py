from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_user, resolve_client_user_id
from db import get_pool
from user_referral_db import (
    assign_referrer_if_first,
    get_referral_cabinet_payload,
    has_pending_withdrawal,
    seal_referral_gate,
)
from user_referral_withdraw import (
    create_withdrawal,
    format_withdrawal_admin_message,
    withdrawal_admin_inline_keyboard,
)
from telegram_notify import send_admin_message

router = APIRouter()


class ReferralApplyBody(BaseModel):
    ref_token: str = Field(min_length=4, max_length=32)


class ReferralWithdrawBody(BaseModel):
    amount_rub: float = Field(gt=0)
    method: str = Field(pattern="^(card|crypto)$")
    requisites: str = Field(min_length=5, max_length=500)
    crypto: str | None = None
    network: str | None = None


@router.get("/referral")
async def get_referral(current_user: dict = Depends(get_current_user)):
    from user_unified_balance import get_unified_balance_stats

    client_id = resolve_client_user_id(current_user)
    return await get_unified_balance_stats(client_id)


@router.post("/referral/apply")
async def apply_referral(
    body: ReferralApplyBody,
    current_user: dict = Depends(get_current_user),
):
    client_id = resolve_client_user_id(current_user)
    ok = await assign_referrer_if_first(client_id, body.ref_token)
    return {"applied": ok}


@router.post("/referral/finalize")
async def finalize_referral_gate(current_user: dict = Depends(get_current_user)):
    """Закрыть окно реферальной привязки после входа на сайте без invite-ссылки."""
    client_id = resolve_client_user_id(current_user)
    await seal_referral_gate(client_id)
    return {"ok": True}


@router.get("/referral/ledger")
async def referral_ledger(
    limit: int = Query(20, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    client_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT type, amount_rub, note, order_id, created_at
            FROM user_referral_ledger
            WHERE referrer_user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            client_id,
            limit,
        )
    return {
        "entries": [
            {
                "type": r["type"],
                "amount_rub": round(float(r["amount_rub"]), 2),
                "note": r.get("note"),
                "order_id": r.get("order_id"),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    }


@router.post("/referral/withdraw")
async def referral_withdraw(
    body: ReferralWithdrawBody,
    current_user: dict = Depends(get_current_user),
):
    """Алиас: вывод с единого баланса."""
    client_id = resolve_client_user_id(current_user)
    from user_unified_balance import get_unified_balance_stats

    stats = await get_unified_balance_stats(client_id)
    if stats["has_pending_withdrawal"]:
        raise HTTPException(status_code=400, detail="У вас уже есть заявка на вывод в обработке")
    try:
        row = await create_withdrawal(
            referrer_user_id=client_id,
            amount_rub=body.amount_rub,
            method=body.method,
            requisites=body.requisites,
            crypto=body.crypto,
            network=body.network,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    username = current_user.get("display_name")
    msg_id = await send_admin_message(
        format_withdrawal_admin_message(row, username),
        reply_markup=withdrawal_admin_inline_keyboard(row["id"], source=row.get("source")),
    )
    if msg_id:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_referral_withdrawals SET admin_message_id = $1 WHERE id = $2",
                msg_id,
                row["id"],
            )
    return {"id": row["id"], "status": row["status"], "amount_rub": float(row["amount_rub"])}
