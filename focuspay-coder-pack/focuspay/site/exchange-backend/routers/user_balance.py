from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_user, resolve_client_user_id
from db import get_pool
from user_cashback_db import set_use_cashback_on_next
from user_unified_balance import get_unified_balance_stats
from user_referral_withdraw import (
    create_withdrawal,
    format_withdrawal_admin_message,
    list_user_withdrawals,
    normalize_withdrawal_source,
    player_withdrawal_out,
    cancel_casino_withdrawal,
    notify_withdrawal_canceled,
    withdrawal_admin_inline_keyboard,
    SOURCE_CASINO,
)
from telegram_notify import send_admin_message
from user_referral_db import assign_referrer_if_first
from partner_author_track import schedule_author_promo_event
from promo_redeem import PromoRedeemError, redeem_promo_code
from user_balance_transfer import TransferError, transfer_balance
import vpn_billing

router = APIRouter()


class BalanceToggleBody(BaseModel):
    use_on_next: bool


class ReferralApplyBody(BaseModel):
    ref_token: str = Field(min_length=4, max_length=32)


class PromoRedeemBody(BaseModel):
    code: str = Field(min_length=3, max_length=32)


class CasinoCryptoAddressBody(BaseModel):
    coin: Literal["btc", "ltc"]


class TransferBody(BaseModel):
    recipient: str = Field(min_length=1, max_length=64)
    amount_rub: float = Field(gt=0)


class BalanceWithdrawBody(BaseModel):
    amount_rub: float = Field(gt=0)
    method: str = Field(pattern="^(card|crypto)$")
    requisites: str = Field(min_length=5, max_length=500)
    crypto: str | None = None
    network: str | None = None
    source: str | None = None


@router.get("/balance")
async def get_balance(current_user: dict = Depends(get_current_user)):
    client_id = resolve_client_user_id(current_user)
    return await get_unified_balance_stats(client_id)


@router.get("/discounts")
async def get_discounts(current_user: dict = Depends(get_current_user)):
    """Ваучеры «скидка на обмен» пользователя (активные + история)."""
    from exchange_discount_db import get_user_discounts_overview

    client_id = resolve_client_user_id(current_user)
    return await get_user_discounts_overview(client_id)


@router.get("/cashback")
async def get_cashback_alias(current_user: dict = Depends(get_current_user)):
    """Обратная совместимость."""
    return await get_balance(current_user)


@router.patch("/balance")
async def patch_balance(
    body: BalanceToggleBody,
    current_user: dict = Depends(get_current_user),
):
    client_id = resolve_client_user_id(current_user)
    await set_use_cashback_on_next(client_id, body.use_on_next)
    return await get_unified_balance_stats(client_id)


@router.patch("/cashback")
async def patch_cashback_alias(
    body: BalanceToggleBody,
    current_user: dict = Depends(get_current_user),
):
    return await patch_balance(body, current_user)


@router.get("/balance/ledger")
async def balance_ledger(
    limit: int = Query(30, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    client_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT 'cashback' AS source, type, amount_rub, note, order_id, created_at
            FROM user_cashback_ledger WHERE user_id = $1
            UNION ALL
            SELECT 'referral', type, amount_rub, note, order_id, created_at
            FROM user_referral_ledger WHERE referrer_user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            client_id,
            limit,
        )
    return {
        "entries": [
            {
                "source": r["source"],
                "type": r["type"],
                "amount_rub": round(float(r["amount_rub"]), 2),
                "note": r.get("note"),
                "order_id": r.get("order_id"),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    }


@router.get("/balance/withdrawals")
async def balance_withdrawals(
    limit: int = Query(30, ge=1, le=100),
    source: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    client_id = resolve_client_user_id(current_user)
    origin: str | None = None
    if source is not None and str(source).strip():
        try:
            origin = normalize_withdrawal_source(source)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = await list_user_withdrawals(client_id, limit=limit, source=origin)
    return {"withdrawals": rows}


@router.post("/balance/withdrawals/{withdrawal_id}/cancel")
async def balance_withdraw_cancel(
    withdrawal_id: int,
    current_user: dict = Depends(get_current_user),
):
    client_id = resolve_client_user_id(current_user)
    try:
        row = await cancel_casino_withdrawal(client_id, withdrawal_id)
    except WithdrawalCancelError as exc:
        status = 404 if exc.code == "not_found" else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    try:
        await notify_withdrawal_canceled(row)
    except Exception:
        pass
    return player_withdrawal_out(row)


@router.post("/balance/withdraw")
async def balance_withdraw(
    body: BalanceWithdrawBody,
    current_user: dict = Depends(get_current_user),
):
    client_id = resolve_client_user_id(current_user)
    stats = await get_unified_balance_stats(client_id)
    origin = normalize_withdrawal_source(body.source)
    if origin != SOURCE_CASINO and stats["has_pending_withdrawal"]:
        raise HTTPException(status_code=400, detail="У вас уже есть заявка на вывод в обработке")
    try:
        row = await create_withdrawal(
            referrer_user_id=client_id,
            amount_rub=body.amount_rub,
            method=body.method,
            requisites=body.requisites,
            crypto=body.crypto,
            network=body.network,
            source=body.source,
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


@router.post("/referral/apply")
async def apply_referral(
    body: ReferralApplyBody,
    current_user: dict = Depends(get_current_user),
):
    client_id = resolve_client_user_id(current_user)
    ok = await assign_referrer_if_first(client_id, body.ref_token)
    return {"applied": ok}


@router.post("/promo/redeem")
async def redeem_promo(
    body: PromoRedeemBody,
    current_user: dict = Depends(get_current_user),
):
    client_id = resolve_client_user_id(current_user)
    try:
        result = await redeem_promo_code(client_id, body.code)
    except PromoRedeemError as e:
        # A tournament code is not a cashback promo: it enrolls the player instead.
        from casino_tournaments import join_by_promo_code

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                joined = await join_by_promo_code(conn, user_id=client_id, promo_code=body.code)
        if joined:
            return {
                "kind": "tournament",
                "tournament_id": joined.get("tournament_id"),
                "title": joined.get("title"),
                "starting_chips": joined.get("starting_chips"),
                "balance": await get_unified_balance_stats(client_id),
            }
        raise HTTPException(status_code=400, detail=str(e)) from e
    if (result.get("campaign_kind") or "") == "exchange_discount":
        schedule_author_promo_event(
            "promo",
            client_id,
            promo=result.get("code"),
            discount=result.get("amount_rub"),
        )
    stats = await get_unified_balance_stats(client_id)
    return {**result, "balance": stats}


@router.post("/transfer")
async def post_transfer(body: TransferBody, current_user: dict = Depends(get_current_user)):
    client_id = resolve_client_user_id(current_user)
    try:
        return await transfer_balance(client_id, body.recipient, body.amount_rub)
    except TransferError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post("/casino/crypto-deposit/address")
async def post_casino_crypto_address(
    body: CasinoCryptoAddressBody,
    current_user: dict = Depends(get_current_user),
):
    from casino_crypto_deposit import ensure_crypto_address

    client_id = resolve_client_user_id(current_user)
    try:
        return await ensure_crypto_address(client_id, body.coin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/casino/crypto-deposits")
async def get_casino_crypto_deposits(current_user: dict = Depends(get_current_user)):
    from casino_crypto_deposit import list_user_crypto_deposits

    client_id = resolve_client_user_id(current_user)
    return {"deposits": await list_user_crypto_deposits(client_id)}


@router.get("/vpn-progress")
async def vpn_progress(current_user: dict = Depends(get_current_user)):
    """Прогресс FocusVPN теми же счётчиками, что user_status (обмены и приглашённые)."""
    telegram_id = resolve_client_user_id(current_user)
    if telegram_id <= 0:
        raise HTTPException(status_code=400, detail="Привяжите Telegram, чтобы видеть FocusVPN")
    pool = await get_pool()
    async with pool.acquire() as conn:
        status = await vpn_billing.user_status(conn, telegram_id)
    return vpn_billing.public_progress(status)
