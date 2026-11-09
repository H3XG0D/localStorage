"""Trader wallet deposit/withdraw requests — admin approval required."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CryptoNetwork,
    User,
    WalletRequest,
    WalletRequestKind,
    WalletRequestStatus,
)
from app.services import token_ledger
from app.services.wallet_fees import fee_for_network


async def create_request(
    db: AsyncSession,
    user: User,
    *,
    kind: WalletRequestKind,
    amount_usdt: Decimal,
    network: CryptoNetwork = CryptoNetwork.usdt_trc20,
    address: str | None = None,
    comment: str | None = None,
) -> WalletRequest:
    if user.deposit_exempt:
        raise HTTPException(400, "Deposit-exempt traders do not use working deposit")
    if amount_usdt <= 0:
        raise HTTPException(400, "Amount must be positive")
    if kind == WalletRequestKind.withdraw and not (address or "").strip():
        raise HTTPException(400, "Wallet address required for withdraw")

    token = await token_ledger.ensure_personal_token(db, user)
    fee = fee_for_network(network) if kind == WalletRequestKind.withdraw else Decimal("0")
    if kind == WalletRequestKind.withdraw:
        bals = await token_ledger.compute_token_balances(db, token.id)
        needed = amount_usdt + fee
        if needed > bals["available"]:
            raise HTTPException(
                400,
                f"Insufficient available: need {needed} (amount+fee), have {bals['available']}",
            )

    row = WalletRequest(
        user_id=user.id,
        work_token_id=token.id,
        kind=kind,
        amount_usdt=amount_usdt,
        network=network,
        address=(address or "").strip() or None,
        fee_usdt=fee,
        status=WalletRequestStatus.pending,
        comment=comment,
    )
    db.add(row)
    await db.flush()
    return row


async def resolve_request(
    db: AsyncSession,
    req: WalletRequest,
    *,
    admin: User,
    approve: bool,
    admin_comment: str | None = None,
) -> WalletRequest:
    if req.status != WalletRequestStatus.pending:
        raise HTTPException(400, "Request already resolved")
    req.resolved_by_id = admin.id
    req.resolved_at = datetime.now(timezone.utc)
    req.admin_comment = admin_comment

    if not approve:
        req.status = WalletRequestStatus.rejected
        await db.flush()
        return req

    token_id = req.work_token_id
    if not token_id:
        raise HTTPException(400, "Request has no work token")

    if req.kind == WalletRequestKind.deposit:
        await token_ledger.deposit(
            db,
            token_id,
            req.amount_usdt,
            actor_id=admin.id,
            idempotency_key=f"wallet-req-deposit-{req.id}",
            comment=f"Approved deposit request #{req.id}",
        )
        req.status = WalletRequestStatus.approved
    else:
        await token_ledger.withdraw_with_fee(
            db,
            token_id,
            req.amount_usdt,
            fee=req.fee_usdt or Decimal("0"),
            actor_id=admin.id,
            idempotency_key=f"wallet-req-wd-{req.id}",
            comment=f"Approved withdraw #{req.id} → {req.network.value} {req.address}",
        )
        req.status = WalletRequestStatus.approved

    await db.flush()
    return req


async def list_for_user(db: AsyncSession, user_id: int, limit: int = 50) -> list[WalletRequest]:
    result = await db.execute(
        select(WalletRequest)
        .where(WalletRequest.user_id == user_id)
        .order_by(WalletRequest.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_pending(db: AsyncSession, limit: int = 100) -> list[WalletRequest]:
    result = await db.execute(
        select(WalletRequest)
        .where(WalletRequest.status == WalletRequestStatus.pending)
        .order_by(WalletRequest.id.asc())
        .limit(limit)
    )
    return list(result.scalars().all())
