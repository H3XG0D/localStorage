"""HMAC API реквизитов магазина: /api/exchanger/v1."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator

from db import get_pool
from exchanger_api_keys import ensure_exchanger_hmac_schema, get_key_by_api_key
from exchanger_hmac import (
    replay_cache,
    replay_key,
    timestamp_fresh,
    verify_signature,
)
from external_deal_payin import (
    attach_receipt_for_deal,
    cancel_cabinet_deal,
    confirm_deal_paid,
    create_cabinet_deal_with_payin,
    deal_public_out,
    get_deal_by_client_transaction_id,
    get_deal_for_exchanger,
    resolve_cabinet_input_rub,
)
from routers import exchanger as exchanger_cabinet

router = APIRouter()
logger = logging.getLogger("exchanger_v1")


def _deal_hmac_out(deal: dict[str, Any]) -> dict[str, Any]:
    payment = deal.get("payment") if isinstance(deal.get("payment"), dict) else {}
    bill = payment.get("bill") if isinstance(payment, dict) else {}
    return {
        **deal,
        "deal_id": deal.get("id"),
        "bill": bill or {},
        "expires_at": deal.get("expires_at"),
    }


def _clean_callback_url(url: str | None) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    if not raw.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="callback_url must be http(s)")
    if len(raw) > 2000:
        raise HTTPException(status_code=400, detail="callback_url too long")
    return raw


async def hmac_shop(request: Request) -> dict[str, Any]:
    api_key = (request.headers.get("x-api-key") or "").strip()
    timestamp = (request.headers.get("x-timestamp") or "").strip()
    signature = (request.headers.get("x-signature") or "").strip()
    if not api_key or not timestamp or not signature:
        raise HTTPException(
            status_code=401,
            detail="X-API-Key, X-Timestamp, X-Signature required",
        )
    body = (await request.body()).decode("utf-8")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await ensure_exchanger_hmac_schema(conn)
        row = await get_key_by_api_key(conn, api_key)
    if not row or not row["is_active"]:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not row["exchanger_is_active"]:
        raise HTTPException(status_code=401, detail="Shop disabled")
    if not timestamp_fresh(timestamp):
        raise HTTPException(status_code=401, detail="Timestamp expired")
    if not verify_signature(str(row["secret"]), timestamp, body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    if replay_cache.seen_or_add(
        replay_key(api_key, timestamp, body, method=request.method, path=request.url.path)
    ):
        raise HTTPException(status_code=401, detail="Replay rejected")
    try:
        payload = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    return {
        "exchanger_id": int(row["exchanger_id"]),
        "payload": payload,
        "api_key": api_key,
    }


class DealCreateBody(BaseModel):
    amount_rub: Optional[float] = None
    amount_crypto: Optional[float] = None
    sub_token: str = "SBPRUB"
    crypto: str = "usdt"
    client_transaction_id: Optional[str] = Field(default=None, max_length=128)
    callback_url: Optional[str] = None
    fingerprint: Optional[str] = Field(default=None, max_length=256)
    note: Optional[str] = None
    client_stat: Optional[dict[str, Any]] = None

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
    def _crypto(cls, v: str) -> str:
        if v not in ("btc", "usdt", "trx", "ltc"):
            raise ValueError("crypto must be btc/usdt/trx/ltc")
        return v

    @field_validator("sub_token")
    @classmethod
    def _sub(cls, v: str) -> str:
        u = (v or "SBPRUB").upper()
        if u not in ("SBPRUB", "CARDRUB"):
            raise ValueError("sub_token must be SBPRUB or CARDRUB")
        return u

    @model_validator(mode="after")
    def _amount(self):
        has_rub = self.amount_rub is not None and self.amount_rub > 0
        has_crypto = self.amount_crypto is not None and self.amount_crypto > 0
        if not has_rub and not has_crypto:
            raise ValueError("amount_rub or amount_crypto required")
        return self


class DealGetBody(BaseModel):
    deal_id: Optional[int] = None
    id: Optional[int] = None
    client_transaction_id: Optional[str] = Field(default=None, max_length=128)


class ReceiptBody(BaseModel):
    file: Optional[str] = None
    file_url: Optional[str] = None


class ClientStatBody(BaseModel):
    paid_orders: Optional[int] = None
    total_orders: Optional[int] = None
    buy_paid: Optional[int] = None
    buy_failed: Optional[int] = None
    conversion_pct: Optional[float] = None
    turnover_rub: Optional[float] = None
    first_order_at: Optional[str] = None
    last_paid_at: Optional[str] = None
    fingerprint: Optional[str] = Field(default=None, max_length=256)


class FingerprintStatBody(ClientStatBody):
    fingerprint: str = Field(..., min_length=1, max_length=256)


def _hmac_actor(shop: dict[str, Any]) -> dict[str, Any]:
    return {
        "external_exchanger_id": shop["exchanger_id"],
        "username": "hmac",
        "exchanger_name": "",
    }


async def _load_deal(conn, exchanger_id: int, deal_id: int) -> dict:
    row = await get_deal_for_exchanger(conn, deal_id, exchanger_id)
    if not row:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    return deal_public_out(dict(row))


@router.post("/deals", status_code=201)
async def v1_create_deal(shop=Depends(hmac_shop)):
    raw = shop["payload"] or {}
    try:
        body = DealCreateBody.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    exchanger_id = int(shop["exchanger_id"])
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
            created_by=f"hmac:{exchanger_id}",
            client_transaction_id=body.client_transaction_id,
            callback_url=_clean_callback_url(body.callback_url),
            fingerprint=(body.fingerprint or "").strip() or None,
            client_stat=body.client_stat,
        )
    try:
        if not deal.get("idempotent"):
            await exchanger_cabinet._notify_deal_ops("created", deal, _hmac_actor(shop))
    except Exception:
        logger.exception("hmac deal ops notify failed")
    return _deal_hmac_out(deal)


async def _resolve_deal_row(conn, exchanger_id: int, payload: dict, deal_id: int | None = None):
    target_id = deal_id or payload.get("deal_id") or payload.get("id")
    ctx = str(payload.get("client_transaction_id") or "").strip()
    if target_id:
        row = await get_deal_for_exchanger(conn, int(target_id), exchanger_id)
    elif ctx:
        row = await get_deal_by_client_transaction_id(conn, exchanger_id, ctx)
    else:
        raise HTTPException(status_code=400, detail="deal_id or client_transaction_id required")
    if not row:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    return row


@router.get("/deals/{deal_id}")
async def v1_get_deal(deal_id: int, shop=Depends(hmac_shop)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        deal = await _load_deal(conn, int(shop["exchanger_id"]), deal_id)
    return _deal_hmac_out(deal)


@router.get("/deals")
async def v1_find_deal(
    client_transaction_id: Optional[str] = Query(None),
    shop=Depends(hmac_shop),
):
    payload = dict(shop.get("payload") or {})
    if client_transaction_id:
        payload["client_transaction_id"] = client_transaction_id
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _resolve_deal_row(conn, int(shop["exchanger_id"]), payload)
    return _deal_hmac_out(deal_public_out(dict(row)))


@router.post("/deals/get")
async def v1_get_deal_post(shop=Depends(hmac_shop)):
    raw = shop["payload"] or {}
    try:
        body = DealGetBody.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = body.model_dump()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _resolve_deal_row(conn, int(shop["exchanger_id"]), payload)
    return _deal_hmac_out(deal_public_out(dict(row)))


@router.post("/deals/{deal_id}/paid")
async def v1_deal_paid(deal_id: int, shop=Depends(hmac_shop)):
    exchanger_id = int(shop["exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await confirm_deal_paid(conn, deal_id, exchanger_id)
    try:
        await exchanger_cabinet._notify_deal_ops(
            "confirm_paid", result.get("deal") or {"id": deal_id}, _hmac_actor(shop)
        )
    except Exception:
        logger.exception("hmac paid ops notify failed")
    deal = result.get("deal") or {}
    return {**result, "deal": _deal_hmac_out(deal) if deal else deal}


@router.post("/deals/{deal_id}/receipt")
async def v1_deal_receipt(deal_id: int, shop=Depends(hmac_shop)):
    raw = shop["payload"] or {}
    try:
        body = ReceiptBody.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    file_url = (body.file or body.file_url or "").strip()
    if not file_url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="file must be an http(s) URL")
    exchanger_id = int(shop["exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await attach_receipt_for_deal(
            conn, deal_id, exchanger_id, file_url, ""
        )
    deal = result.get("deal") or {}
    return {**result, "deal": _deal_hmac_out(deal) if deal else deal}


@router.post("/deals/{deal_id}/cancel")
async def v1_deal_cancel(deal_id: int, shop=Depends(hmac_shop)):
    exchanger_id = int(shop["exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await cancel_cabinet_deal(conn, deal_id, exchanger_id)
    try:
        await exchanger_cabinet._notify_deal_ops(
            "cancelled", result.get("deal") or {"id": deal_id}, _hmac_actor(shop)
        )
    except Exception:
        logger.exception("hmac cancel ops notify failed")
    deal = result.get("deal") or {}
    return {**result, "deal": _deal_hmac_out(deal) if deal else deal}


@router.post("/deals/{deal_id}/client-stat")
async def v1_deal_client_stat(deal_id: int, shop=Depends(hmac_shop)):
    from external_client_stat import check_public_out, coerce_client_stat_payload, save_client_stat

    exchanger_id = int(shop["exchanger_id"])
    parsed = coerce_client_stat_payload(shop.get("payload") or {})
    if parsed is None:
        raise HTTPException(status_code=400, detail="client_stat required")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await get_deal_for_exchanger(conn, deal_id, exchanger_id)
        if not row:
            raise HTTPException(status_code=404, detail="Сделка не найдена")
        fp = (shop.get("payload") or {}).get("fingerprint") or row.get("customer_fingerprint")
        await save_client_stat(
            conn,
            exchanger_id=exchanger_id,
            payload=parsed,
            fingerprint=str(fp or "").strip() or None,
            deal_id=deal_id,
        )
        refreshed = await get_deal_for_exchanger(conn, deal_id, exchanger_id)
    return check_public_out(dict(refreshed or row), parsed)


@router.post("/clients/stat")
async def v1_clients_stat(shop=Depends(hmac_shop)):
    from external_client_stat import coerce_client_stat_payload, save_client_stat

    raw = shop.get("payload") or {}
    try:
        body = FingerprintStatBody.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    parsed = coerce_client_stat_payload(raw)
    if parsed is None:
        raise HTTPException(status_code=400, detail="client_stat required")
    exchanger_id = int(shop["exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        await save_client_stat(
            conn,
            exchanger_id=exchanger_id,
            payload=parsed,
            fingerprint=body.fingerprint.strip(),
        )
    return {"ok": True, "fingerprint": body.fingerprint.strip(), **parsed}


@router.get("/deals/{deal_id}/check")
async def v1_deal_check(deal_id: int, shop=Depends(hmac_shop)):
    from external_client_stat import (
        check_public_out,
        fetch_fingerprint_stat,
        payload_from_row,
    )

    exchanger_id = int(shop["exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await get_deal_for_exchanger(conn, deal_id, exchanger_id)
        if not row:
            raise HTTPException(status_code=404, detail="Сделка не найдена")
        deal = dict(row)
        stat = None
        if deal.get("client_stat"):
            stat = payload_from_row(deal.get("client_stat"))
        if not stat:
            stat = await fetch_fingerprint_stat(
                conn, exchanger_id, deal.get("customer_fingerprint")
            )
    return check_public_out(deal, stat)
