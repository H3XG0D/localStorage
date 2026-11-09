"""API личного кабинета внештатника (/exchanger)."""
from __future__ import annotations

import html
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, field_validator, model_validator

from auth import get_current_exchanger, get_current_exchanger_owner, validate_username
from config import settings
from db import get_pool
from external_exchange_stats import fetch_exchanger_ops_stats, fetch_exchanger_stats, fetch_history
from external_exchanger_accounts import (
    CLERK_ROLE,
    EXCHANGER_LOGIN_PATH,
    account_public_dict,
    account_role,
    create_exchanger_account,
    credentials_response,
    exchanger_login_url,
    fetch_account_of_exchanger,
    fetch_accounts_for_exchanger,
    is_owner_account,
    reset_account_password,
)
from external_deal_payin import (
    attach_receipt_for_deal,
    cancel_cabinet_deal,
    confirm_deal_paid,
    count_active_deals_for_exchanger,
    count_deals_for_exchanger,
    create_cabinet_deal_with_payin,
    deal_public_out,
    get_deal_for_exchanger,
    list_active_deals,
    list_deals_for_exchanger,
    preview_cabinet_deal,
    resolve_cabinet_input_rub,
)
from external_exchange_service import get_exchanger_active, resolve_exchanger_markup
from external_deals_telegram import external_deals_chat
from external_deal_ops_notify import format_deal_ops_notify
from external_deal_receipt_notify import notify_ops_external_receipt
from external_exchange_payout import (
    create_payout_request,
    create_rub_payout_and_push_doliv,
    list_exchanger_payouts,
    min_payout_gross_usd,
    payout_balance_info,
    preview_exchanger_payout,
    withdraw_fee_usd,
    withdraw_fees_map,
)
from receipt_public_url import build_receipt_public_url
from reki_snapshot import reki_public_out
from reki_store import load_reki_snapshot
from receipt_validation import MAX_RECEIPT_PDF_BYTES, is_valid_pdf_bytes
from telegram_notify import send_ops_message

router = APIRouter()
logger = logging.getLogger("exchanger_api")

RECEIPTS_DIR = Path(os.getenv("RECEIPTS_DIR", "/opt/tg_bot_btc/receipts"))


def _ensure_receipts_dir() -> Path:
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    return RECEIPTS_DIR


async def _send_external_deals(text: str) -> None:
    chat_id, topic_id = external_deals_chat()
    if not chat_id or not settings.telegram_bot_token:
        return
    try:
        await send_ops_message(text, chat_id=chat_id, message_thread_id=topic_id)
    except Exception as exc:
        logger.warning("external deals notify failed: %s", exc)


def _exchanger_ops_ctx(exchanger: dict[str, Any]) -> dict[str, Any]:
    return {
        "exchanger_name": exchanger.get("exchanger_name"),
        "username": exchanger.get("username"),
        "is_trusted_client": exchanger.get("is_trusted_client"),
    }


async def _notify_deal_ops(event: str, deal: dict[str, Any], exchanger: dict[str, Any]) -> None:
    exchanger_id = int(exchanger["external_exchanger_id"])
    deal_row = {**deal, "exchanger_id": deal.get("exchanger_id") or exchanger_id}
    pool = await get_pool()
    async with pool.acquire() as conn:
        stats = await fetch_exchanger_ops_stats(conn, exchanger_id)
    await _send_external_deals(
        format_deal_ops_notify(
            event,
            deal_row,
            _exchanger_ops_ctx(exchanger),
            ops_stats=stats,
        )
    )


class DealCreateBody(BaseModel):
    amount_rub: Optional[float] = None
    amount_crypto: Optional[float] = None
    crypto: str = "usdt"
    sub_token: str = "SBPRUB"
    note: Optional[str] = None
    client_is_new: bool = True
    payout_on_credit: bool = False
    payout_wallet: Optional[str] = None

    @field_validator("amount_rub")
    @classmethod
    def _positive(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if v <= 0:
            raise ValueError("amount_rub must be > 0")
        return v

    @field_validator("amount_crypto")
    @classmethod
    def _positive_crypto(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if v <= 0:
            raise ValueError("amount_crypto must be > 0")
        return v

    @field_validator("crypto")
    @classmethod
    def _valid_crypto(cls, v: str) -> str:
        if v not in ("btc", "usdt", "trx", "ltc"):
            raise ValueError("crypto must be btc/usdt/trx/ltc")
        return v

    @field_validator("sub_token")
    @classmethod
    def _valid_sub(cls, v: str) -> str:
        u = (v or "SBPRUB").upper()
        if u not in ("SBPRUB", "CARDRUB"):
            raise ValueError("sub_token must be SBPRUB or CARDRUB")
        return u

    @model_validator(mode="after")
    def _payout_intent(self):
        has_rub = self.amount_rub is not None and self.amount_rub > 0
        has_crypto = self.amount_crypto is not None and self.amount_crypto > 0
        if not has_rub and not has_crypto:
            raise ValueError("amount_rub or amount_crypto required")
        if self.payout_on_credit:
            wallet = (self.payout_wallet or "").strip()
            if len(wallet) < 8:
                raise ValueError("payout_wallet required for crypto settlement")
            self.payout_wallet = wallet
        else:
            self.payout_wallet = None
        return self


class PayoutRequestBody(BaseModel):
    gross_usd: float
    crypto: str = "usdt"
    wallet: str

    @field_validator("gross_usd")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("gross_usd must be > 0")
        return v

    @field_validator("crypto")
    @classmethod
    def _valid_crypto(cls, v: str) -> str:
        if v not in ("btc", "usdt", "trx", "ltc"):
            raise ValueError("crypto must be btc/usdt/trx/ltc")
        return v

    @field_validator("wallet")
    @classmethod
    def _wallet(cls, v: str) -> str:
        w = (v or "").strip()
        if len(w) < 8:
            raise ValueError("wallet too short")
        return w


class RubCardPayoutBody(BaseModel):
    """Вывод баланса внештатника на карту/СБП → PayoutJob в Doliv."""

    amount_rub: float
    pay_method: str = "sbp"
    phone: str | None = None
    card_number: str | None = None
    recipient_name: str | None = None
    bank: str | None = None

    @field_validator("amount_rub")
    @classmethod
    def _pos_rub(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("amount_rub must be > 0")
        return v

    @field_validator("pay_method")
    @classmethod
    def _method(cls, v: str) -> str:
        m = (v or "sbp").lower()
        if m not in ("sbp", "c2c"):
            raise ValueError("pay_method must be sbp or c2c")
        return m


class ClerkCreateBody(BaseModel):
    """Хозяин выпускает логин кассира: только логин, пароль генерируем сами."""

    username: str
    label: str | None = None

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return validate_username(v)


class AccountUpdateBody(BaseModel):
    is_active: bool | None = None
    label: str | None = None


@router.get("/rates")
async def exchanger_rates(_exchanger=Depends(get_current_exchanger)):
    """Raw Rapira close for freelancer cabinet — no USDT pad, no CoinGecko."""
    from routers.public import SUPPORTED, _cache, get_exchanger_rates_cached, rates_source

    try:
        market = await get_exchanger_rates_cached()
    except Exception as exc:
        logger.error("Exchanger rates unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Rate service temporarily unavailable") from exc

    result: dict[str, dict[str, object]] = {}
    for crypto in SUPPORTED:
        price = market.get(crypto)
        if price is None:
            continue
        result[crypto] = {"market": round(float(price), 2), "currency": "RUB"}

    src = rates_source()
    return {
        "rates": result,
        "updated_at": _cache.get("_ts"),
        "source": src,
        "frozen": src == "frozen",
    }


@router.get("/reki")
async def exchanger_reki(_exchanger=Depends(get_current_exchanger)):
    """Свободные коридоры сумм из /reki. Номеров реквизитов здесь нет."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        snapshot = await load_reki_snapshot(conn)
    return reki_public_out(snapshot)


@router.get("/dashboard")
async def exchanger_dashboard(exchanger=Depends(get_current_exchanger)):
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        from exchanger_api_keys import ensure_exchanger_hmac_schema

        await ensure_exchanger_hmac_schema(conn)
        stats = await fetch_exchanger_stats(conn, exchanger_id)
        active_rows = await list_active_deals(conn, exchanger_id)
        active_deal_ids = [int(r["id"]) for r in active_rows]
        payout_info = await payout_balance_info(conn, exchanger_id)
        ex_row = await get_exchanger_active(conn, exchanger_id)
    markup = resolve_exchanger_markup(ex_row or {})
    markup_mode = str(markup["markup_mode"])
    markup_hint = (
        "Вы указываете сумму, которую платит клиент. Процент вычитается — остаток поступит на ваш баланс."
        if markup_mode == "on_turnover"
        else "Вы указываете сумму, которая поступит на баланс. К оплате клиентом добавляется процент сверху."
    )
    return {
        "exchanger_id": exchanger_id,
        "name": exchanger.get("exchanger_name"),
        "username": exchanger.get("username"),
        "role": account_role(exchanger),
        "is_owner": is_owner_account(exchanger),
        "totp_enabled": bool(exchanger.get("totp_enabled")),
        "markup_pct": float(markup["markup_pct"]),
        "markup_mode": markup_mode,
        "markup_hint": markup_hint,
        "login_path": EXCHANGER_LOGIN_PATH,
        "login_url": exchanger_login_url(),
        "stats": stats,
        "balance_usd": stats["balance_usd"],
        "available_usd": payout_info["available_usd"],
        "has_pending_payout": payout_info["has_pending_payout"],
        "pending_payout_gross_usd": payout_info["pending_payout_gross_usd"],
        "deal_count": stats["deal_count"],
        "payout_count": stats["payout_count"],
        "turnover_base_rub": stats["turnover_base_rub"],
        "turnover_client_rub": stats["turnover_client_rub"],
        "total_credited_usd": stats["total_credited_usd"],
        "total_paid_out_usd": stats["total_paid_out_usd"],
        "conversion_pct": stats.get("conversion_pct"),
        "deals_confirmed": stats.get("deals_confirmed", stats.get("deal_count", 0)),
        "deals_failed": stats.get("deals_failed", 0),
        "last_deal_at": stats["last_deal_at"],
        "last_payout_at": stats["last_payout_at"],
        "payout_threshold_usd": min_payout_gross_usd("usdt"),
        "withdraw_fee_usd": withdraw_fee_usd("usdt"),
        "withdraw_fees": withdraw_fees_map(),
        "active_deal_id": active_deal_ids[0] if active_deal_ids else None,
        "active_deal_ids": active_deal_ids,
        "active_count": len(active_deal_ids),
    }


@router.get("/payouts/balance")
async def payouts_balance(exchanger=Depends(get_current_exchanger)):
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await payout_balance_info(conn, exchanger_id)


@router.get("/payouts/preview")
async def payouts_preview(
    gross_usd: float = Query(..., gt=0),
    crypto: str = Query("usdt"),
    exchanger=Depends(get_current_exchanger_owner),
):
    from routers.public import get_exchanger_rates_cached

    if crypto not in ("btc", "usdt", "trx", "ltc"):
        raise HTTPException(status_code=400, detail="Invalid crypto")
    rates = await get_exchanger_rates_cached()
    if float(rates.get("usdt") or 0) <= 0:
        raise HTTPException(status_code=503, detail="Курс недоступен")
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await preview_exchanger_payout(conn, exchanger_id, gross_usd, crypto, rates)


@router.get("/payouts")
async def payouts_list(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    exchanger=Depends(get_current_exchanger_owner),
):
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        items, total = await list_exchanger_payouts(
            conn, exchanger_id, limit=limit, offset=offset
        )
    return {"items": items, "total": total}


@router.post("/payouts", status_code=201)
async def payouts_create(body: PayoutRequestBody, exchanger=Depends(get_current_exchanger_owner)):
    from routers.public import get_exchanger_rates_cached

    rates = await get_exchanger_rates_cached()
    if float(rates.get("usdt") or 0) <= 0:
        raise HTTPException(status_code=503, detail="Курс недоступен")
    exchanger_id = int(exchanger["external_exchanger_id"])
    username = str(exchanger.get("username") or "exchanger")
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await create_payout_request(
            conn,
            exchanger_id,
            gross_usd=body.gross_usd,
            crypto=body.crypto,
            wallet=body.wallet,
            market_rub=rates,
            created_by=f"ex:{username}",
        )
    name = html.escape(str(exchanger.get("exchanger_name") or ""))
    uname = html.escape(str(username).lstrip("@"))
    await _send_external_deals(
        f"💸 Кабинет · заявка на вывод #{result['id']} · <b>{name}</b> · "
        f"${float(result['gross_usd']):,.0f} → {float(result['crypto_amount']):.6f} "
        f"{str(result['crypto']).upper()} · @{uname}"
    )
    from external_payout_notify import notify_admin_external_payout_requested

    msg_id = await notify_admin_external_payout_requested(
        result,
        exchanger_name=str(exchanger.get("exchanger_name") or ""),
        username=username,
        market_rub=rates,
    )
    if msg_id:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE external_payouts SET admin_message_id = $1 WHERE id = $2",
                int(msg_id),
                int(result["id"]),
            )
        result["admin_message_id"] = int(msg_id)
    return result


@router.post("/payouts/rub-card", status_code=201)
async def payouts_rub_card(body: RubCardPayoutBody, exchanger=Depends(get_current_exchanger_owner)):
    """Заявка на вывод ₽ на карту/СБП → Doliv PayoutJob."""
    if body.pay_method == "sbp" and not (body.phone or "").strip():
        raise HTTPException(status_code=400, detail="phone required for SBP")
    if body.pay_method == "c2c" and not (body.card_number or "").strip():
        raise HTTPException(status_code=400, detail="card_number required for C2C")
    exchanger_id = int(exchanger["external_exchanger_id"])
    username = str(exchanger.get("username") or "exchanger")
    requisites = {
        "phone": body.phone,
        "card_number": body.card_number,
        "recipient_name": body.recipient_name,
        "bank": body.bank,
        "method": body.pay_method,
    }
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await create_rub_payout_and_push_doliv(
            conn,
            exchanger_id,
            amount_rub=body.amount_rub,
            pay_method=body.pay_method,
            requisites=requisites,
            created_by=f"ex:{username}",
        )
    if not result.get("bridge_enabled"):
        raise HTTPException(
            status_code=503,
            detail="Doliv bridge disabled (set DOLIV_BRIDGE_URL and DOLIV_BRIDGE_KEY)",
        )
    if not result.get("doliv_job"):
        raise HTTPException(status_code=502, detail="Doliv bridge failed to create payout job")
    name = html.escape(str(exchanger.get("exchanger_name") or ""))
    await _send_external_deals(
        f"🏦 Кабинет · RUB-вывод → Doliv · <b>{name}</b> · "
        f"{body.amount_rub:,.0f} ₽ · {body.pay_method.upper()}"
    )
    return result


@router.get("/history")
async def exchanger_history(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    exchanger=Depends(get_current_exchanger),
):
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        from exchanger_api_keys import ensure_exchanger_hmac_schema

        await ensure_exchanger_hmac_schema(conn)
        items, total = await fetch_history(conn, exchanger_id, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/portal-link")
async def exchanger_portal_link(exchanger=Depends(get_current_exchanger)):
    return {
        "login_path": EXCHANGER_LOGIN_PATH,
        "login_url": exchanger_login_url(),
        "username": exchanger.get("username"),
    }


@router.get("/accounts")
async def accounts_list(exchanger=Depends(get_current_exchanger_owner)):
    """Логины магазина: хозяин и кассиры."""
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await fetch_accounts_for_exchanger(conn, exchanger_id)
    return {
        "items": [account_public_dict(row) for row in rows],
        "current_account_id": int(exchanger["id"]),
    }


@router.post("/accounts", status_code=201)
async def accounts_create_clerk(
    body: ClerkCreateBody,
    exchanger=Depends(get_current_exchanger_owner),
):
    """Кассирский логин: реквизиты и чеки, без выводов и настроек магазина."""
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            password_plain, account = await create_exchanger_account(
                conn,
                exchanger_id,
                body.username,
                role=CLERK_ROLE,
                label=body.label,
                created_by_account_id=int(exchanger["id"]),
            )
        except ValueError as exc:
            if str(exc) == "username_taken":
                raise HTTPException(status_code=400, detail="Логин уже занят") from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "account": account_public_dict(account),
        "credentials": credentials_response(
            account["username"], password_plain, role=CLERK_ROLE
        ),
    }


async def _clerk_of_owner(conn, account_id: int, exchanger_id: int) -> dict:
    row = await fetch_account_of_exchanger(conn, account_id, exchanger_id)
    if not row:
        raise HTTPException(status_code=404, detail="Логин не найден")
    if is_owner_account(row):
        raise HTTPException(
            status_code=400,
            detail="Свой логин меняйте через смену пароля и 2FA",
        )
    return dict(row)


@router.post("/accounts/{account_id}/reset-password")
async def accounts_reset_password(
    account_id: int,
    exchanger=Depends(get_current_exchanger_owner),
):
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _clerk_of_owner(conn, account_id, exchanger_id)
        password_plain = await reset_account_password(conn, account_id)
    return credentials_response(row["username"], password_plain, role=account_role(row))


@router.patch("/accounts/{account_id}")
async def accounts_update(
    account_id: int,
    body: AccountUpdateBody,
    exchanger=Depends(get_current_exchanger_owner),
):
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _clerk_of_owner(conn, account_id, exchanger_id)
        if body.is_active is not None:
            await conn.execute(
                "UPDATE external_exchanger_accounts SET is_active = $1 WHERE id = $2",
                bool(body.is_active),
                account_id,
            )
        if body.label is not None:
            await conn.execute(
                "UPDATE external_exchanger_accounts SET label = $1 WHERE id = $2",
                body.label.strip() or None,
                account_id,
            )
        row = await fetch_account_of_exchanger(conn, account_id, exchanger_id)
    return {"account": account_public_dict(row)}


@router.get("/api-keys")
async def api_keys_get(exchanger=Depends(get_current_exchanger_owner)):
    from exchanger_api_keys import list_key_for_exchanger

    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        key = await list_key_for_exchanger(conn, exchanger_id)
    return {"key": key}


@router.post("/api-keys")
async def api_keys_issue(_exchanger=Depends(get_current_exchanger_owner)):
    from exchanger_api_keys import ADMIN_ONLY_API_KEY_DETAIL

    raise HTTPException(status_code=403, detail=ADMIN_ONLY_API_KEY_DETAIL)


@router.post("/api-keys/revoke")
async def api_keys_revoke(_exchanger=Depends(get_current_exchanger_owner)):
    from exchanger_api_keys import ADMIN_ONLY_API_KEY_DETAIL

    raise HTTPException(status_code=403, detail=ADMIN_ONLY_API_KEY_DETAIL)


@router.get("/deals/preview")
async def deals_preview(
    amount_rub: Optional[float] = Query(None, gt=0),
    amount_crypto: Optional[float] = Query(None, gt=0),
    crypto: str = Query("usdt"),
    exchanger=Depends(get_current_exchanger),
):
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await preview_cabinet_deal(
            conn,
            exchanger_id,
            amount_rub,
            amount_crypto=amount_crypto,
            crypto=crypto,
        )


@router.post("/deals", status_code=201)
async def deals_create(body: DealCreateBody, exchanger=Depends(get_current_exchanger)):
    exchanger_id = int(exchanger["external_exchanger_id"])
    username = str(exchanger.get("username") or exchanger.get("id") or "exchanger")
    from routers.public import get_exchanger_rates_cached

    rates = await get_exchanger_rates_cached()
    amount_rub, _ = resolve_cabinet_input_rub(
        amount_rub=body.amount_rub,
        amount_crypto=body.amount_crypto,
        crypto=body.crypto,
        rates=rates,
    )
    pool = await get_pool()
    async with pool.acquire() as conn:
        deal = await create_cabinet_deal_with_payin(
            conn,
            exchanger_id=exchanger_id,
            amount_rub=amount_rub,
            crypto=body.crypto,
            sub_token=body.sub_token,
            note=body.note,
            created_by=f"ex:{username}",
            client_is_new=body.client_is_new,
            payout_on_credit=body.payout_on_credit,
            payout_wallet=body.payout_wallet,
        )

    await _notify_deal_ops("created", deal, exchanger)
    return deal


@router.get("/deals")
async def deals_list(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    exchanger=Depends(get_current_exchanger),
):
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        items = await list_deals_for_exchanger(
            conn, exchanger_id, limit=limit, offset=offset, status=status
        )
        total = await count_deals_for_exchanger(conn, exchanger_id, status=status)
        active_count = await count_active_deals_for_exchanger(conn, exchanger_id)
    return {"items": items, "total": total, "active_count": active_count}


@router.get("/deals/active")
async def deals_active(exchanger=Depends(get_current_exchanger)):
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await list_active_deals(conn, exchanger_id)
    if not rows:
        return {"active": False, "deals": []}
    deals = [deal_public_out(dict(r)) for r in rows]
    return {
        "active": True,
        "deals": deals,
        "deal": deals[0],
    }


@router.get("/deals/{deal_id}")
async def deals_get(deal_id: int, exchanger=Depends(get_current_exchanger)):
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await get_deal_for_exchanger(conn, deal_id, exchanger_id)
    if not row:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    return deal_public_out(dict(row))


@router.post("/deals/{deal_id}/confirm-paid")
async def deals_confirm_paid(deal_id: int, exchanger=Depends(get_current_exchanger)):
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await confirm_deal_paid(conn, deal_id, exchanger_id)

    await _notify_deal_ops("confirm_paid", result.get("deal") or {"id": deal_id}, exchanger)
    return result


@router.post("/deals/{deal_id}/receipt")
async def deals_upload_receipt(
    deal_id: int,
    file: UploadFile = File(...),
    exchanger=Depends(get_current_exchanger),
):
    exchanger_id = int(exchanger["external_exchanger_id"])
    filename = (file.filename or "").lower()
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    if ext != "pdf":
        raise HTTPException(status_code=400, detail="Only PDF receipts are accepted")

    content = await file.read()
    if len(content) > MAX_RECEIPT_PDF_BYTES:
        limit_mb = MAX_RECEIPT_PDF_BYTES // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"File too large (max {limit_mb} MB)")
    if not is_valid_pdf_bytes(content):
        raise HTTPException(status_code=400, detail="Invalid PDF file")

    _ensure_receipts_dir()
    receipt_id = uuid.uuid4().hex
    receipt_name = f"{receipt_id}.pdf"
    path = RECEIPTS_DIR / receipt_name
    path.write_bytes(content)
    receipt_url = build_receipt_public_url(receipt_name)

    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await attach_receipt_for_deal(
            conn, deal_id, exchanger_id, receipt_url, receipt_name
        )

    await notify_ops_external_receipt(
        result.get("deal") or {"id": deal_id},
        exchanger,
        path,
    )
    return result


@router.post("/deals/{deal_id}/cancel")
async def deals_cancel(deal_id: int, exchanger=Depends(get_current_exchanger)):
    exchanger_id = int(exchanger["external_exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await get_deal_for_exchanger(conn, deal_id, exchanger_id)
        if row:
            await _notify_deal_ops("cancelled", dict(row), exchanger)
        return await cancel_cabinet_deal(conn, deal_id, exchanger_id)
