"""Payfast-compatible merchant payin endpoints."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import merchant_payin

router = APIRouter(prefix="/api_merchant", tags=["merchant"])


async def _auth_partner(
    request: Request,
    db: AsyncSession,
    x_api_key: str | None,
    x_timestamp: str | None,
    x_signature: str | None,
):
    if not x_api_key or not x_timestamp or not x_signature:
        raise HTTPException(401, "X-API-Key, X-Timestamp, X-Signature required")
    partner = await merchant_payin.get_partner_by_api_key(db, x_api_key)
    if not partner:
        raise HTTPException(401, "Invalid API key")
    body = (await request.body()).decode("utf-8")
    if not merchant_payin.verify_hmac(partner.secret, x_timestamp, body, x_signature):
        raise HTTPException(401, "Invalid signature")
    # re-parse for handlers
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError as e:
        raise HTTPException(400, "Invalid JSON body") from e
    return partner, payload


@router.post("/create_order_payin")
async def create_order_payin(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    x_timestamp: Annotated[str | None, Header(alias="X-Timestamp")] = None,
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
):
    partner, payload = await _auth_partner(request, db, x_api_key, x_timestamp, x_signature)
    amount = Decimal(str(payload.get("amount") or 0))
    if amount <= 0:
        raise HTTPException(400, "amount required")
    client_tx = str(payload.get("client_transaction_id") or "")
    if not client_tx:
        raise HTTPException(400, "client_transaction_id required")
    return await merchant_payin.create_order_payin(
        db,
        partner,
        client_transaction_id=client_tx,
        amount=amount,
        sub_token=str(payload.get("sub_token") or "SBPRUB"),
        fingerprint=str(payload.get("fingerprint") or "") or None,
        callback_url=str(payload.get("callback_url") or "") or None,
    )


@router.post("/get_order")
async def get_order(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    x_timestamp: Annotated[str | None, Header(alias="X-Timestamp")] = None,
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
):
    partner, payload = await _auth_partner(request, db, x_api_key, x_timestamp, x_signature)
    uuid_value = str(payload.get("uuid") or payload.get("uuid_system") or "")
    if not uuid_value:
        raise HTTPException(400, "uuid required")
    return await merchant_payin.get_order(db, partner, uuid_value)


@router.post("/cancel_order_payin")
async def cancel_order_payin(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    x_timestamp: Annotated[str | None, Header(alias="X-Timestamp")] = None,
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
):
    partner, payload = await _auth_partner(request, db, x_api_key, x_timestamp, x_signature)
    uuid_value = str(payload.get("uuid") or "")
    if not uuid_value:
        raise HTTPException(400, "uuid required")
    return await merchant_payin.cancel_order(db, partner, uuid_value)


@router.post("/payin_set_status")
async def payin_set_status(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    x_timestamp: Annotated[str | None, Header(alias="X-Timestamp")] = None,
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
):
    """Mark order paid|failed|expired|cancelled and fire partner callback."""
    from sqlalchemy import select

    from app.models import MerchantOrder, MerchantOrderStatus

    partner, payload = await _auth_partner(request, db, x_api_key, x_timestamp, x_signature)
    uuid_value = str(payload.get("uuid") or "")
    status_raw = str(payload.get("status") or "").lower()
    if not uuid_value:
        raise HTTPException(400, "uuid required")
    try:
        status = MerchantOrderStatus(status_raw)
    except ValueError as e:
        raise HTTPException(400, "status must be paid|failed|expired|cancelled") from e
    if status not in (
        MerchantOrderStatus.paid,
        MerchantOrderStatus.failed,
        MerchantOrderStatus.expired,
        MerchantOrderStatus.cancelled,
    ):
        raise HTTPException(400, "invalid status transition")
    result = await db.execute(
        select(MerchantOrder).where(
            MerchantOrder.uuid == uuid_value,
            MerchantOrder.partner_id == partner.id,
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    await merchant_payin.set_order_status(db, order, status)
    return merchant_payin._order_payload(order)


@router.post("/payin_set_check")
async def payin_set_check(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    x_timestamp: Annotated[str | None, Header(alias="X-Timestamp")] = None,
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
):
    """Attach partner PDF/image check to the trader card session as a zaliv."""
    partner, payload = await _auth_partner(request, db, x_api_key, x_timestamp, x_signature)
    uuid_value = str(payload.get("uuid") or payload.get("uuid_system") or "")
    file_url = str(payload.get("file") or payload.get("file_url") or "")
    if not uuid_value:
        raise HTTPException(400, "uuid required")
    if not file_url:
        raise HTTPException(400, "file required")
    return await merchant_payin.payin_set_check(
        db, partner, uuid_value=uuid_value, file_url=file_url
    )
