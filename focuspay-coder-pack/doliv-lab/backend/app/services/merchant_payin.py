"""Merchant payin API — Payfast-compatible create/get/cancel skeleton."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    CardStatus,
    MerchantOrder,
    MerchantOrderStatus,
    MerchantPartner,
    PaymentChannel,
    Requisite,
    RequisiteStatus,
    TraderCard,
    Zaliv,
)
from app.services.office_day import day_start_utc

OPEN_STATUSES = {
    RequisiteStatus.active,
    RequisiteStatus.in_work,
    RequisiteStatus.awaiting_doliv,
    RequisiteStatus.doliv_in_progress,
}


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def verify_hmac(secret: str, timestamp: str, body: str, signature: str) -> bool:
    message = timestamp + body
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


async def create_partner(
    db: AsyncSession,
    *,
    name: str,
    callback_url_default: str | None = None,
) -> tuple[MerchantPartner, str]:
    api_key = secrets.token_hex(16)
    secret = secrets.token_hex(24)
    partner = MerchantPartner(
        name=name,
        api_key=api_key,
        secret=secret,
        secret_hash=hash_secret(secret),
        secret_hint=secret[:4] + "…",
        callback_url_default=callback_url_default,
        is_active=True,
    )
    db.add(partner)
    await db.flush()
    return partner, secret


async def get_partner_by_api_key(db: AsyncSession, api_key: str) -> MerchantPartner | None:
    result = await db.execute(
        select(MerchantPartner).where(
            MerchantPartner.api_key == api_key,
            MerchantPartner.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


def _band_ok(card: TraderCard, amount: Decimal) -> bool:
    bands = card.payment_bands or []
    if bands:
        for b in bands:
            try:
                lo = Decimal(str(b.get("min_rub", 0)))
                hi = Decimal(str(b.get("max_rub", 0)))
            except Exception:
                continue
            if lo <= amount <= hi:
                return True
        return False
    if card.min_payment_rub is not None and amount < Decimal(card.min_payment_rub):
        return False
    if card.max_payment_rub is not None and amount > Decimal(card.max_payment_rub):
        return False
    return True


async def fingerprint_history(
    db: AsyncSession, fingerprint: str | None
) -> tuple[int, Decimal]:
    """Successful payins for this buyer across the office."""
    fp = (fingerprint or "").strip()
    if not fp:
        return 0, Decimal("0")
    row = await db.execute(
        select(
            func.count(MerchantOrder.id),
            func.coalesce(func.sum(MerchantOrder.amount_rub), 0),
        ).where(
            MerchantOrder.fingerprint == fp,
            or_(
                MerchantOrder.zaliv_id.isnot(None),
                MerchantOrder.status == MerchantOrderStatus.paid,
            ),
        )
    )
    count, volume = row.one()
    return int(count or 0), Decimal(str(volume or 0))


def _traffic_ok(card: TraderCard, *, orders: int, volume: Decimal) -> bool:
    min_o = getattr(card, "traffic_min_orders", None)
    max_o = getattr(card, "traffic_max_orders", None)
    if min_o is not None and orders < int(min_o):
        return False
    if max_o is not None and orders > int(max_o):
        return False
    min_v = getattr(card, "traffic_min_volume_rub", None)
    max_v = getattr(card, "traffic_max_volume_rub", None)
    if min_v is not None and volume < Decimal(min_v):
        return False
    if max_v is not None and volume > Decimal(max_v):
        return False
    return True


async def pick_card_for_amount(
    db: AsyncSession,
    amount: Decimal,
    *,
    prefer_sbp: bool,
    fingerprint: str | None = None,
) -> tuple[TraderCard, Requisite] | None:
    orders, volume = await fingerprint_history(db, fingerprint)
    result = await db.execute(
        select(TraderCard)
        .options(selectinload(TraderCard.sessions))
        .where(TraderCard.status == CardStatus.active)
        .order_by(TraderCard.id.desc())
    )
    cards = list(result.scalars().all())
    # Prefer SBP or C2C based on sub_token
    cards.sort(key=lambda c: 0 if (c.channel == "sbp") == prefer_sbp else 1)

    for card in cards:
        if not getattr(card, "accepting_enabled", False):
            continue
        if not _band_ok(card, amount):
            continue
        if not _traffic_ok(card, orders=orders, volume=volume):
            continue
        # Open session with remaining
        sess = None
        if card.linked_requisite_id:
            sess = await db.get(Requisite, card.linked_requisite_id)
        if not sess or sess.status not in OPEN_STATUSES:
            continue
        remaining = Decimal(sess.total_amount) - Decimal(
            # approx: float already on card; remaining from total - zalivs better but use float path
            0
        )
        # Use total_amount - sum of zalivs if available; fallback float check
        from app.models import Zaliv

        zsum = await db.execute(
            select(Zaliv).where(Zaliv.requisite_id == sess.id)
        )
        zaliv_total = sum((Decimal(z.amount) for z in zsum.scalars().all()), Decimal("0"))
        remaining = Decimal(sess.total_amount) - zaliv_total
        if remaining < amount:
            continue
        if card.daily_limit_rub is not None:
            day_start = await day_start_utc(db)
            today_row = await db.execute(
                select(func.coalesce(func.sum(Zaliv.amount), 0))
                .join(Requisite, Zaliv.requisite_id == Requisite.id)
                .where(Requisite.card_id == card.id, Zaliv.created_at >= day_start)
            )
            received_today = Decimal(str(today_row.scalar() or 0))
            if received_today + amount > Decimal(card.daily_limit_rub):
                continue
        return card, sess
    return None


def _bill_from_card(card: TraderCard) -> dict:
    if card.channel == PaymentChannel.sbp.value or card.channel == "sbp":
        return {
            "reciver": card.phone or "",
            "bankName": card.bank or "",
            "holderName": card.recipient_name or "",
            "method": "sbp",
        }
    return {
        "reciver": card.card_number or "",
        "bankName": card.bank or "",
        "holderName": card.recipient_name or "",
        "method": "c2c",
    }


async def create_order_payin(
    db: AsyncSession,
    partner: MerchantPartner,
    *,
    client_transaction_id: str,
    amount: Decimal,
    sub_token: str = "SBPRUB",
    fingerprint: str | None = None,
    callback_url: str | None = None,
) -> dict:
    existing = await db.execute(
        select(MerchantOrder).where(
            MerchantOrder.partner_id == partner.id,
            MerchantOrder.client_transaction_id == client_transaction_id,
        )
    )
    found = existing.scalar_one_or_none()
    if found:
        return _order_payload(found)

    prefer_sbp = "SBP" in (sub_token or "").upper()
    picked = await pick_card_for_amount(
        db, amount, prefer_sbp=prefer_sbp, fingerprint=fingerprint
    )
    order_uuid = str(uuid.uuid4())
    if not picked:
        order = MerchantOrder(
            uuid=order_uuid,
            partner_id=partner.id,
            client_transaction_id=client_transaction_id,
            amount_rub=amount,
            sub_token=sub_token or "SBPRUB",
            fingerprint=fingerprint,
            callback_url=callback_url or partner.callback_url_default,
            status=MerchantOrderStatus.failed,
            bill=None,
        )
        db.add(order)
        await db.flush()
        return {"status_pending": "error", "error": "No accepting card for amount", "uuid": order_uuid}

    card, sess = picked
    bill = _bill_from_card(card)
    order = MerchantOrder(
        uuid=order_uuid,
        partner_id=partner.id,
        client_transaction_id=client_transaction_id,
        amount_rub=amount,
        sub_token=sub_token or "SBPRUB",
        fingerprint=fingerprint,
        callback_url=callback_url or partner.callback_url_default,
        status=MerchantOrderStatus.issued,
        card_id=card.id,
        requisite_id=sess.id,
        bill=bill,
    )
    db.add(order)
    await db.flush()
    return _order_payload(order)


def _order_payload(order: MerchantOrder) -> dict:
    return {
        "uuid": order.uuid,
        "uuid_system": order.uuid,
        "client_transaction_id": order.client_transaction_id,
        "amount": int(order.amount_rub),
        "status": order.status.value,
        "status_pending": "ok" if order.status == MerchantOrderStatus.issued else order.status.value,
        "bill": order.bill,
        "sub_token": order.sub_token,
    }


async def get_order(db: AsyncSession, partner: MerchantPartner, uuid_value: str) -> dict:
    result = await db.execute(
        select(MerchantOrder).where(
            MerchantOrder.uuid == uuid_value,
            MerchantOrder.partner_id == partner.id,
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    return _order_payload(order)


async def cancel_order(db: AsyncSession, partner: MerchantPartner, uuid_value: str) -> dict:
    result = await db.execute(
        select(MerchantOrder).where(
            MerchantOrder.uuid == uuid_value,
            MerchantOrder.partner_id == partner.id,
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status in (MerchantOrderStatus.paid, MerchantOrderStatus.cancelled):
        return _order_payload(order)
    order.status = MerchantOrderStatus.cancelled
    await db.flush()
    await fire_partner_callback(order, event="cancelled")
    return _order_payload(order)


async def set_order_status(
    db: AsyncSession,
    order: MerchantOrder,
    status: MerchantOrderStatus,
) -> MerchantOrder:
    order.status = status
    await db.flush()
    await fire_partner_callback(order, event=status.value)
    return order


async def fire_partner_callback(order: MerchantOrder, *, event: str) -> None:
    """Best-effort POST to partner callback_url (Payfast-style notify)."""
    url = (order.callback_url or "").strip()
    if not url:
        return
    import logging

    import httpx

    log = logging.getLogger("merchant_callback")
    payload = {
        "event": event,
        "uuid": order.uuid,
        "client_transaction_id": order.client_transaction_id,
        "amount": int(order.amount_rub),
        "status": order.status.value if hasattr(order.status, "value") else str(order.status),
        "bill": order.bill,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)
    except Exception as e:
        log.warning("callback failed order=%s url=%s: %s", order.uuid, url, e)


_CHECK_MAX_BYTES = 10 * 1024 * 1024


async def fetch_check_bytes(file_url: str) -> tuple[bytes, str]:
    """Download partner-supplied receipt. Returns (content, mime)."""
    url = (file_url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "file must be an http(s) URL")
    import httpx

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url)
    except Exception as exc:
        raise HTTPException(400, "failed to download file") from exc
    if response.status_code >= 400:
        raise HTTPException(400, "failed to download file")
    content = response.content or b""
    if len(content) > _CHECK_MAX_BYTES:
        raise HTTPException(400, "file too large")
    mime = (response.headers.get("content-type") or "application/pdf").split(";")[0].strip().lower()
    if content[:4] == b"%PDF":
        mime = "application/pdf"
    elif content[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif content[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    return content, mime


async def payin_set_check(
    db: AsyncSession,
    partner: MerchantPartner,
    *,
    uuid_value: str,
    file_url: str,
) -> dict:
    """Attach PDF/image check to merchant order as a zaliv on the card session."""
    result = await db.execute(
        select(MerchantOrder).where(
            MerchantOrder.uuid == uuid_value,
            MerchantOrder.partner_id == partner.id,
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status in (
        MerchantOrderStatus.cancelled,
        MerchantOrderStatus.failed,
        MerchantOrderStatus.expired,
    ):
        raise HTTPException(400, "order is closed")
    if not order.requisite_id:
        raise HTTPException(400, "order has no card session")

    if order.zaliv_id:
        return {**_order_payload(order), "zaliv_id": order.zaliv_id, "check": "already_set"}

    sess_row = await db.execute(
        select(Requisite)
        .options(selectinload(Requisite.zalivs), selectinload(Requisite.trader))
        .where(Requisite.id == order.requisite_id)
    )
    sess = sess_row.scalar_one_or_none()
    if not sess:
        raise HTTPException(400, "card session not found")
    if sess.status not in OPEN_STATUSES:
        raise HTTPException(400, "card session is closed")

    content, mime = await fetch_check_bytes(file_url)
    from app.services.files import save_receipt_bytes
    from app.services.trader_profit import resolve_trader_profit_percent
    from app.services import float_ledger

    receipt_path = save_receipt_bytes(sess.id, content, mime=mime)
    profit_percent = Decimal("12")
    if sess.trader:
        profit_percent = await resolve_trader_profit_percent(db, sess.trader)
    rate = Decimal(sess.target_rate or 0)
    if rate <= 0:
        raise HTTPException(400, "session has no rate")

    zaliv = Zaliv(
        requisite_id=sess.id,
        amount=Decimal(order.amount_rub),
        rate=rate,
        profit_percent=profit_percent,
        receipt_path=receipt_path,
    )
    db.add(zaliv)
    await db.flush()
    await float_ledger.confirm_payment(
        db,
        sess,
        Decimal(order.amount_rub),
        zaliv_id=zaliv.id,
        actor_id=sess.trader_id,
    )
    if sess.status == RequisiteStatus.active:
        sess.status = RequisiteStatus.in_work
    order.zaliv_id = zaliv.id
    await db.flush()
    return {**_order_payload(order), "zaliv_id": zaliv.id, "check": "ok"}
