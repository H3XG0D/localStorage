"""Wallet requests, payout jobs, bridge + merchant admin helpers."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import require_role
from app.core.database import get_db
from app.models import (
    BridgeServiceKey,
    CryptoNetwork,
    MerchantPartner,
    PayoutClaim,
    PayoutPayMethod,
    User,
    UserRole,
    WalletRequest,
    WalletRequestKind,
)
from app.schemas import (
    MerchantPartnerCreate,
    MerchantPartnerResponse,
    MerchantPartnerUpdate,
    PayoutClaimCreate,
    PayoutClaimResponse,
    PayoutJobCreate,
    PayoutJobResponse,
    WalletRequestCreate,
    WalletRequestResolve,
    WalletRequestResponse,
)
from app.services import merchant_payin, payout_jobs, wallet_requests as wr_svc

router = APIRouter(tags=["bridge-payouts"])


def _wr_resp(r: WalletRequest) -> WalletRequestResponse:
    return WalletRequestResponse(
        id=r.id,
        user_id=r.user_id,
        kind=r.kind.value,
        amount_usdt=r.amount_usdt,
        network=r.network.value if hasattr(r.network, "value") else str(r.network),
        address=r.address,
        fee_usdt=r.fee_usdt,
        status=r.status.value,
        comment=r.comment,
        admin_comment=r.admin_comment,
        created_at=r.created_at,
        resolved_at=r.resolved_at,
    )


def _job_resp(j) -> PayoutJobResponse:
    return PayoutJobResponse(
        id=j.id,
        amount_rub=j.amount_rub,
        remaining_rub=j.remaining_rub,
        pay_method=j.pay_method.value if hasattr(j.pay_method, "value") else str(j.pay_method),
        requisites=j.requisites,
        source=j.source,
        external_ref=j.external_ref,
        status=j.status.value,
        claim_deadline=j.claim_deadline,
        created_at=j.created_at,
        claims=[
            PayoutClaimResponse(
                id=c.id,
                job_id=c.job_id,
                trader_id=c.trader_id,
                amount_rub=c.amount_rub,
                status=c.status.value,
                created_at=c.created_at,
                paid_at=c.paid_at,
            )
            for c in (j.claims or [])
        ],
    )


# ── Trader wallet requests ───────────────────────────────────────────────────

async def _create_wallet_request(data: WalletRequestCreate, user: User, db: AsyncSession):
    try:
        network = CryptoNetwork(data.network)
    except ValueError as e:
        raise HTTPException(400, f"Invalid network: {data.network}") from e
    kind = WalletRequestKind(data.kind)
    row = await wr_svc.create_request(
        db,
        user,
        kind=kind,
        amount_usdt=data.amount_usdt,
        network=network,
        address=data.address,
        comment=data.comment,
    )
    return _wr_resp(row)


@router.post("/trader/wallet/requests", response_model=WalletRequestResponse, status_code=201)
async def trader_create_wallet_request(
    data: WalletRequestCreate,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _create_wallet_request(data, user, db)


@router.get("/trader/wallet/requests", response_model=list[WalletRequestResponse])
async def trader_list_wallet_requests(
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = await wr_svc.list_for_user(db, user.id)
    return [_wr_resp(r) for r in rows]


@router.post("/teamlead/wallet/requests", response_model=WalletRequestResponse, status_code=201)
async def teamlead_create_wallet_request(
    data: WalletRequestCreate,
    user: Annotated[User, Depends(require_role(UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _create_wallet_request(data, user, db)


@router.get("/teamlead/wallet/requests", response_model=list[WalletRequestResponse])
async def teamlead_list_wallet_requests(
    user: Annotated[User, Depends(require_role(UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = await wr_svc.list_for_user(db, user.id)
    return [_wr_resp(r) for r in rows]


@router.get("/admin/wallet-requests", response_model=list[WalletRequestResponse])
async def admin_list_wallet_requests(
    _user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
    pending_only: bool = True,
):
    if pending_only:
        rows = await wr_svc.list_pending(db)
    else:
        result = await db.execute(select(WalletRequest).order_by(WalletRequest.id.desc()).limit(100))
        rows = list(result.scalars().all())
    return [_wr_resp(r) for r in rows]


@router.post("/admin/wallet-requests/{request_id}/resolve", response_model=WalletRequestResponse)
async def admin_resolve_wallet_request(
    request_id: int,
    data: WalletRequestResolve,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    req = await db.get(WalletRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    row = await wr_svc.resolve_request(
        db, req, admin=user, approve=data.approve, admin_comment=data.admin_comment
    )
    return _wr_resp(row)


# ── Payout jobs ──────────────────────────────────────────────────────────────

@router.get("/admin/card-balances")
async def admin_card_balances(
    _user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await payout_jobs.card_float_summary(db)


@router.post("/admin/payout-jobs", response_model=PayoutJobResponse, status_code=201)
async def admin_create_payout_job(
    data: PayoutJobCreate,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.models import PayoutJob

    method = PayoutPayMethod(data.pay_method)
    job = await payout_jobs.create_job(
        db,
        amount_rub=data.amount_rub,
        pay_method=method,
        requisites=data.requisites,
        source=data.source,
        external_ref=data.external_ref,
        created_by_id=user.id,
        ttl_minutes=data.ttl_minutes,
    )
    loaded = (
        await db.execute(
            select(PayoutJob).options(selectinload(PayoutJob.claims)).where(PayoutJob.id == job.id)
        )
    ).scalar_one()
    return _job_resp(loaded)


@router.get("/trader/payout-jobs", response_model=list[PayoutJobResponse])
async def trader_list_payout_jobs(
    _user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    jobs = await payout_jobs.list_open_jobs(db)
    return [_job_resp(j) for j in jobs]


@router.post("/trader/payout-jobs/{job_id}/claim", response_model=PayoutClaimResponse)
async def trader_claim_payout(
    job_id: int,
    data: PayoutClaimCreate,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.models import PayoutJob

    job = await db.get(PayoutJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    claim = await payout_jobs.claim(db, job, user, data.amount_rub)
    return PayoutClaimResponse(
        id=claim.id,
        job_id=claim.job_id,
        trader_id=claim.trader_id,
        amount_rub=claim.amount_rub,
        status=claim.status.value,
        created_at=claim.created_at,
        paid_at=claim.paid_at,
    )


@router.post("/trader/payout-claims/{claim_id}/paid", response_model=PayoutClaimResponse)
async def trader_mark_claim_paid(
    claim_id: int,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    claim = await db.get(PayoutClaim, claim_id)
    if not claim or claim.trader_id != user.id:
        raise HTTPException(404, "Claim not found")
    claim = await payout_jobs.mark_claim_paid(db, claim, user)
    return PayoutClaimResponse(
        id=claim.id,
        job_id=claim.job_id,
        trader_id=claim.trader_id,
        amount_rub=claim.amount_rub,
        status=claim.status.value,
        created_at=claim.created_at,
        paid_at=claim.paid_at,
    )


# ── Bridge (service key) ─────────────────────────────────────────────────────

async def _require_bridge_key(
    db: AsyncSession,
    x_bridge_key: str | None,
) -> BridgeServiceKey:
    if not x_bridge_key:
        raise HTTPException(401, "X-Bridge-Key required")
    key_hash = hashlib.sha256(x_bridge_key.encode()).hexdigest()
    result = await db.execute(
        select(BridgeServiceKey).where(
            BridgeServiceKey.key_hash == key_hash,
            BridgeServiceKey.is_active == True,  # noqa: E712
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(401, "Invalid bridge key")
    return row


@router.post("/admin/bridge-keys", status_code=201)
async def admin_create_bridge_key(
    _user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
    name: str = "focuspay",
):
    raw = secrets.token_hex(24)
    row = BridgeServiceKey(
        name=name,
        key_prefix=raw[:8],
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        is_active=True,
    )
    db.add(row)
    await db.flush()
    return {"id": row.id, "name": row.name, "raw_key": raw, "key_prefix": row.key_prefix}


@router.post("/bridge/payout-jobs", response_model=PayoutJobResponse, status_code=201)
async def bridge_create_payout_job(
    data: PayoutJobCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_bridge_key: Annotated[str | None, Header()] = None,
):
    await _require_bridge_key(db, x_bridge_key)
    method = PayoutPayMethod(data.pay_method)
    job = await payout_jobs.create_job(
        db,
        amount_rub=data.amount_rub,
        pay_method=method,
        requisites=data.requisites,
        source=data.source or "bridge",
        external_ref=data.external_ref,
        created_by_id=None,
        ttl_minutes=data.ttl_minutes,
    )
    from app.models import PayoutJob

    loaded = (
        await db.execute(
            select(PayoutJob).options(selectinload(PayoutJob.claims)).where(PayoutJob.id == job.id)
        )
    ).scalar_one()
    return _job_resp(loaded)


@router.get("/bridge/card-balances")
async def bridge_card_balances(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_bridge_key: Annotated[str | None, Header()] = None,
):
    await _require_bridge_key(db, x_bridge_key)
    return await payout_jobs.card_float_summary(db)


@router.get("/bridge/payout-jobs/{job_id}", response_model=PayoutJobResponse)
async def bridge_get_payout_job(
    job_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_bridge_key: Annotated[str | None, Header()] = None,
):
    await _require_bridge_key(db, x_bridge_key)
    from app.models import PayoutJob

    loaded = (
        await db.execute(
            select(PayoutJob).options(selectinload(PayoutJob.claims)).where(PayoutJob.id == job_id)
        )
    ).scalar_one_or_none()
    if not loaded:
        raise HTTPException(404, "Job not found")
    await payout_jobs.expire_if_needed(db, loaded)
    return _job_resp(loaded)


@router.post("/bridge/payout-jobs/{job_id}/events")
async def bridge_payout_job_events(
    job_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_bridge_key: Annotated[str | None, Header()] = None,
    event: str = "poll",
):
    """FocusPay polls or acknowledges job lifecycle (claimed/partial_paid/completed/expired)."""
    await _require_bridge_key(db, x_bridge_key)
    from app.models import PayoutJob

    loaded = (
        await db.execute(
            select(PayoutJob).options(selectinload(PayoutJob.claims)).where(PayoutJob.id == job_id)
        )
    ).scalar_one_or_none()
    if not loaded:
        raise HTTPException(404, "Job not found")
    await payout_jobs.expire_if_needed(db, loaded)
    body = _job_resp(loaded)
    return {
        "event": event or loaded.status.value,
        "job": body,
        "status": loaded.status.value,
        "remaining_rub": str(loaded.remaining_rub),
    }


# ── Merchant partners (admin) ────────────────────────────────────────────────

@router.post("/admin/merchant-partners", response_model=MerchantPartnerResponse, status_code=201)
async def admin_create_merchant_partner(
    data: MerchantPartnerCreate,
    _user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    partner, secret = await merchant_payin.create_partner(
        db, name=data.name, callback_url_default=data.callback_url_default
    )
    return MerchantPartnerResponse(
        id=partner.id,
        name=partner.name,
        api_key=partner.api_key,
        secret=secret,
        secret_hint=partner.secret_hint,
        is_active=partner.is_active,
        callback_url_default=partner.callback_url_default,
        created_at=partner.created_at,
    )


def _partner_public(partner: MerchantPartner) -> MerchantPartnerResponse:
    return MerchantPartnerResponse(
        id=partner.id,
        name=partner.name,
        api_key=partner.api_key,
        secret=None,
        secret_hint=partner.secret_hint,
        is_active=partner.is_active,
        callback_url_default=partner.callback_url_default,
        created_at=partner.created_at,
    )


@router.get("/admin/merchant-partners", response_model=list[MerchantPartnerResponse])
async def admin_list_merchant_partners(
    _user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(MerchantPartner).order_by(MerchantPartner.id.desc()))
    return [_partner_public(p) for p in result.scalars().all()]


@router.patch("/admin/merchant-partners/{partner_id}", response_model=MerchantPartnerResponse)
async def admin_update_merchant_partner(
    partner_id: int,
    data: MerchantPartnerUpdate,
    _user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    partner = await db.get(MerchantPartner, partner_id)
    if not partner:
        raise HTTPException(404, "Partner not found")
    if data.name is not None:
        partner.name = data.name
    if data.is_active is not None:
        partner.is_active = data.is_active
    if "callback_url_default" in data.model_fields_set:
        partner.callback_url_default = data.callback_url_default
    await db.flush()
    return _partner_public(partner)
