"""Internal API: Payfast webhook / reconciler → автоподтверждение внештатных сделок."""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from config import settings
from db import get_pool
from external_deal_payin import (
    get_deal_by_merchant_ref,
    try_auto_confirm_external_deal_on_payfast,
)
from external_deal_receipt_notify import notify_ops_auto_confirmed

router = APIRouter()


def _verify_internal_token(token: str | None) -> None:
    expected = (settings.internal_api_secret or settings.webhook_secret or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Internal API not configured")
    if not token or token.strip() != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


class PayfastSettledBody(BaseModel):
    webhook_body: Optional[dict[str, Any]] = None


class PayfastSettledByRefBody(BaseModel):
    merchant_ref: str = Field(..., min_length=1, max_length=128)
    webhook_body: Optional[dict[str, Any]] = None


async def _handle_auto_confirm(deal_id: int, webhook_body: dict | None) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await try_auto_confirm_external_deal_on_payfast(
            conn, deal_id, webhook_body=webhook_body
        )
    if result.get("confirmed"):
        deal = result.get("deal") or {"id": deal_id}
        exchanger = result.get("exchanger") or {}
        await notify_ops_auto_confirmed(deal, exchanger)
    return result


@router.post("/external/deals/{deal_id}/payfast-settled")
async def external_deal_payfast_settled(
    deal_id: int,
    body: PayfastSettledBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    return await _handle_auto_confirm(deal_id, body.webhook_body)


@router.post("/external/deals/payfast-settled-by-ref")
async def external_deal_payfast_settled_by_ref(
    body: PayfastSettledByRefBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await get_deal_by_merchant_ref(conn, body.merchant_ref)
    if not row:
        from external_deal_payin import record_payfast_review

        async with pool.acquire() as conn:
            await record_payfast_review(
                conn,
                incident_type="unknown_callback",
                merchant_ref=body.merchant_ref,
                detail={"source": "callback", "reason": "deal_not_found"},
            )
        return {"skipped": True, "reason": "deal_not_found"}
    return await _handle_auto_confirm(int(row["id"]), body.webhook_body)


@router.get("/pnl")
async def internal_pnl(
    date_from: str,
    date_to: str,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """P&L для /dash и /pulse бота — тот же compute_pnl, что админка."""
    from datetime import date

    from finance_pnl import compute_pnl

    _verify_internal_token(x_internal_token)
    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid date") from e
    if d_to < d_from:
        raise HTTPException(status_code=400, detail="Invalid date range")
    return await compute_pnl(d_from, d_to)


@router.get("/hot-wallet-runway")
async def internal_hot_wallet_runway(
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Запас BTC/LTC и срок для Telegram /dash. Тот же расчёт, что обзор админки."""
    from hot_wallet_runway import build_hot_wallet_runway

    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await build_hot_wallet_runway(conn)


_BTC_FEE_RATE_CACHE: dict[str, float] = {}
_BTC_FEE_RATE_TTL = 60.0


@router.get("/btc-fee-rate")
async def internal_btc_fee_rate(
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Ставка отправки BTC для котировки в боте. Кеш 60с: signer дёргается по HMAC.

    `rate` отсутствует, если оценки нет вообще — тогда бот не берёт наценку,
    а выдача реквизитов не должна падать из-за недоступного signer.
    """
    import time

    _verify_internal_token(x_internal_token)
    now = time.monotonic()
    cached = _BTC_FEE_RATE_CACHE.get("rate")
    if cached and now - _BTC_FEE_RATE_CACHE.get("at", 0.0) < _BTC_FEE_RATE_TTL:
        return {"rate_sat_vb": cached, "cached": True}

    from signer_client import fetch_signer_fee_estimate

    try:
        data = await fetch_signer_fee_estimate("btc")
    except Exception:
        data = {}
    rate = float(data.get("feerate_sat_vb") or 0) if data.get("ok") else 0.0
    if rate > 0:
        _BTC_FEE_RATE_CACHE.update({"rate": rate, "at": now})
        return {"rate_sat_vb": rate, "cached": False}
    return {"rate_sat_vb": cached or None, "cached": bool(cached), "stale": True}


@router.get("/autopilot-savings")
async def internal_autopilot_savings(
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Плюс автопилота за 7 дней для Telegram /dash. Начисления не меняет."""
    from autopilot_savings import build_autopilot_savings

    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await build_autopilot_savings(conn)


class NoShiftAccessBody(BaseModel):
    user_id: int = Field(..., gt=0)
    direction: str = Field("buy", max_length=16)
    fiat_amount: Optional[int] = Field(None, ge=0, le=50_000_000)
    crypto: Optional[str] = Field(None, max_length=32)
    crypto_amount: Optional[float] = Field(None, ge=0, le=1_000_000_000)


class RequisiteRetryBody(BaseModel):
    user_id: int = Field(..., gt=0)
    fiat_amount: float = Field(..., gt=0, le=50_000_000)
    crypto: str = Field(..., min_length=2, max_length=32)
    network: Optional[str] = Field(None, max_length=32)
    wallet: str = Field(..., min_length=10, max_length=200)
    sub_token: str = Field("SBPRUB", max_length=16)
    rate: float = Field(0, ge=0)
    crypto_amount: float = Field(0, ge=0)
    amount_currency: Optional[str] = Field(None, max_length=16)
    order_source: str = Field("bot", max_length=32)


class RequisiteRetryUserBody(BaseModel):
    user_id: int = Field(..., gt=0)


class RequisiteRetryCloseBody(BaseModel):
    user_id: int = Field(..., gt=0)
    order_id: str = Field(..., min_length=1, max_length=64)


@router.post("/requisite-retries")
async def internal_open_requisite_retry(
    body: RequisiteRetryBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Сохранить черновик, если клиенту не выдали реквизиты."""
    from requisite_retry import open_requisite_retry

    _verify_internal_token(x_internal_token)
    return await open_requisite_retry(body.model_dump())


@router.post("/requisite-retries/attempt")
async def internal_claim_requisite_retry(
    body: RequisiteRetryUserBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Списать кулдаун и отдать параметры для повторного поиска."""
    from requisite_retry import claim_requisite_attempt

    _verify_internal_token(x_internal_token)
    return await claim_requisite_attempt(body.user_id)


@router.post("/requisite-retries/close")
async def internal_close_requisite_retry(
    body: RequisiteRetryCloseBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Заявка создана — черновик закрыть и пометить выплату."""
    from requisite_retry import close_requisite_retry

    _verify_internal_token(x_internal_token)
    await close_requisite_retry(body.user_id, body.order_id.strip())
    return {"ok": True}


class PayoutWalletConfirmBody(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=64)
    user_id: int = Field(..., gt=0)
    action: Literal["confirm", "replace", "await_address", "cancel"]
    address: Optional[str] = Field(None, max_length=200)


@router.post("/payout-wallet-confirm")
async def internal_payout_wallet_confirm(
    body: PayoutWalletConfirmBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Клиент подтвердил адрес автовыплаты или прислал другой."""
    from payout_wallet_confirm import apply_client_decision

    _verify_internal_token(x_internal_token)
    return await apply_client_decision(
        order_id=body.order_id.strip(),
        user_id=int(body.user_id),
        action=body.action,
        address=body.address,
    )


class PayoutWalletEarlyBody(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=64)


@router.post("/payout-wallet-confirm/send-early")
async def internal_payout_wallet_send_early(
    body: PayoutWalletEarlyBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Оператор в Telegram убрал 5-минутный таймер и отправил запрос кошелька досрочно."""
    from payout_wallet_confirm import send_wallet_confirm_early

    _verify_internal_token(x_internal_token)
    return await send_wallet_confirm_early(body.order_id.strip())


class NoShiftServedBody(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=64)
    user_id: int = Field(..., gt=0)
    fiat_amount: float = Field(0, ge=0, le=50_000_000)
    crypto: str = Field("BTC", max_length=16)


@router.post("/no-shift-access")
async def internal_no_shift_access(
    body: NoShiftAccessBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Можно ли постоянному клиенту выдать реквизиты без полной смены."""
    from auto_service_gate import resolve_no_shift_access

    _verify_internal_token(x_internal_token)
    decision = await resolve_no_shift_access(
        body.user_id,
        body.direction,
        body.fiat_amount,
        crypto=body.crypto,
        crypto_amount=body.crypto_amount,
    )
    payload: dict[str, Any] = {"kind": decision.kind, "reason": decision.reason}
    if decision.reason == "insufficient_paid_buys":
        from auto_settings import auto_no_shift_min_buy_paid
        from payin_requisite_rail import buy_paid_count

        pool = await get_pool()
        async with pool.acquire() as conn:
            payload["paid_buys"] = await buy_paid_count(conn, body.user_id)
        payload["min_paid_buys"] = auto_no_shift_min_buy_paid()
    elif decision.reason == "amount_over_cap":
        from auto_settings import auto_no_shift_max_rub

        payload["max_rub"] = auto_no_shift_max_rub()
        if body.fiat_amount is not None:
            payload["fiat_amount"] = int(body.fiat_amount)
    elif decision.reason in ("coin_short", "coin_unknown"):
        if decision.coin:
            payload["coin"] = decision.coin
        if decision.need is not None:
            payload["need"] = decision.need
        if decision.spendable is not None:
            payload["spendable"] = decision.spendable
        if decision.reserved is not None:
            payload["reserved"] = decision.reserved
        if decision.spendable is not None and decision.reserved is not None:
            payload["available"] = round(decision.spendable - decision.reserved, 8)
    return payload


class WithdrawalAutoReserveBody(BaseModel):
    withdrawal_id: int = Field(..., gt=0)


@router.post("/withdrawals/auto-reserve")
async def internal_withdrawal_auto_reserve(
    body: WithdrawalAutoReserveBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Бот создал pending-вывод — прогнать тот же риск-гейт/reserve, что кабинет."""
    from user_referral_withdraw import auto_reserve_pending_withdrawal

    _verify_internal_token(x_internal_token)
    result = await auto_reserve_pending_withdrawal(int(body.withdrawal_id))
    if not result.get("ok") and result.get("outcome") == "missing":
        raise HTTPException(status_code=404, detail="withdrawal_not_found")
    return result


@router.post("/no-shift-access/served")
async def internal_no_shift_served(
    body: NoShiftServedBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Пометить заявку бота как обслуженную автопилотом и сказать операторам."""
    from auto_no_shift_notify import notify_auto_buy_order
    from auto_order_flags import mark_order_auto_served

    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id, direction
            FROM orders
            WHERE order_id = $1
            """,
            body.order_id,
        )
        if not row or int(row["user_id"]) != int(body.user_id):
            raise HTTPException(status_code=404, detail="order_not_found")
        if str(row["direction"] or "").lower() != "buy":
            raise HTTPException(status_code=400, detail="not_buy")
        await mark_order_auto_served(conn, body.order_id, None)
    await notify_auto_buy_order(
        order_id=body.order_id,
        user_id=body.user_id,
        fiat_amount=float(body.fiat_amount or 0),
        crypto=body.crypto or "BTC",
    )
    return {"ok": True}


@router.get("/owner-dashboard")
async def internal_owner_dashboard(
    period: str = "today",
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Dashboard данные для владельца (бот /owner)."""
    from owner_dashboard_data import get_owner_dashboard_data

    _verify_internal_token(x_internal_token)
    return await get_owner_dashboard_data(period)


@router.get("/users/{telegram_id}/referrer")
async def get_user_referrer(
    telegram_id: int,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """
    Получить реферера пользователя.

    Используется ботом казино для расчёта реферальных комиссий.

    Returns:
        {"referrer_id": int | null}
    """
    _verify_internal_token(x_internal_token)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT referrer_user_id
            FROM user_referral_attributions
            WHERE user_id = $1
            """,
            telegram_id,
        )

    if not row or not row["referrer_user_id"]:
        raise HTTPException(404, "No referrer found")

    return {"referrer_id": row["referrer_user_id"]}
    """Owner KPI snapshot for Telegram /dash — same service as /api/admin/dashboard/owner."""
    from owner_dashboard_metrics import PERIOD_KEYS, build_owner_dashboard

    _verify_internal_token(x_internal_token)
    key = (period or "today").strip().lower()
    if key not in PERIOD_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period. Allowed: {', '.join(PERIOD_KEYS)}",
        )
    return await build_owner_dashboard(key)
