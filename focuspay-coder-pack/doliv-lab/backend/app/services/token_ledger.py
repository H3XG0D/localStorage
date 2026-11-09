"""Work-token USDT ledger: deposit / hold / release / credit / debit / withdraw."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    TokenLedger,
    TokenLedgerType,
    TokenMember,
    User,
    WorkToken,
)

USDT_Q = Decimal("0.000001")
CREDIT_TYPES = {TokenLedgerType.deposit, TokenLedgerType.credit, TokenLedgerType.payout_bonus}
DEBIT_TYPES = {TokenLedgerType.debit, TokenLedgerType.withdraw}
HOLD_TYPES = {TokenLedgerType.hold}
RELEASE_TYPES = {TokenLedgerType.release}


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(USDT_Q, rounding=ROUND_HALF_UP)


async def get_active_token_for_user(db: AsyncSession, user_id: int) -> WorkToken | None:
    result = await db.execute(
        select(WorkToken)
        .join(TokenMember, TokenMember.work_token_id == WorkToken.id)
        .where(
            TokenMember.user_id == user_id,
            TokenMember.is_active == True,  # noqa: E712
            WorkToken.is_active == True,  # noqa: E712
        )
        .order_by(TokenMember.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def ensure_membership(db: AsyncSession, work_token_id: int, user_id: int) -> TokenMember:
    existing = await db.execute(
        select(TokenMember).where(
            TokenMember.work_token_id == work_token_id,
            TokenMember.user_id == user_id,
        )
    )
    member = existing.scalar_one_or_none()
    if member:
        member.is_active = True
        return member
    member = TokenMember(work_token_id=work_token_id, user_id=user_id, is_active=True)
    db.add(member)
    await db.flush()
    return member


async def ensure_personal_token(
    db: AsyncSession,
    user: User,
    *,
    owner_id: int | None = None,
    name: str | None = None,
) -> WorkToken:
    """1 user → 1 active personal WorkToken (sole member = user)."""
    existing = await get_active_token_for_user(db, user.id)
    if existing:
        return existing
    token = WorkToken(
        name=name or f"token-{user.login}",
        owner_id=owner_id if owner_id is not None else user.id,
        deposit_exempt=bool(user.deposit_exempt),
        is_active=True,
    )
    db.add(token)
    await db.flush()
    await ensure_membership(db, token.id, user.id)
    return token


async def withdraw_with_fee(
    db: AsyncSession,
    work_token_id: int,
    amount: Decimal,
    *,
    fee: Decimal,
    actor_id: int | None,
    idempotency_key: str,
    comment: str | None = None,
) -> tuple[TokenLedger, TokenLedger | None]:
    """Withdraw principal + flat fee. Requires available >= amount + fee."""
    amount = _q(amount)
    fee = _q(fee)
    bals = await compute_token_balances(db, work_token_id)
    needed = amount + fee
    if needed > bals["available"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient available balance: need {needed} USDT "
                f"(amount {amount} + fee {fee}), available {bals['available']} USDT"
            ),
        )
    w = await _add_entry(
        db,
        work_token_id=work_token_id,
        entry_type=TokenLedgerType.withdraw,
        amount=amount,
        idempotency_key=f"withdraw-{idempotency_key}",
        actor_id=actor_id,
        comment=comment or "Trader withdraw",
    )
    fee_entry = None
    if fee > 0:
        fee_entry = await _add_entry(
            db,
            work_token_id=work_token_id,
            entry_type=TokenLedgerType.debit,
            amount=fee,
            idempotency_key=f"withdraw-fee-{idempotency_key}",
            actor_id=actor_id,
            comment="Withdraw fee",
        )
    return w, fee_entry


async def compute_token_balances(db: AsyncSession, work_token_id: int) -> dict[str, Decimal]:
    result = await db.execute(select(TokenLedger).where(TokenLedger.work_token_id == work_token_id))
    entries = result.scalars().all()
    balance = Decimal("0")
    held = Decimal("0")
    for e in entries:
        if e.entry_type in CREDIT_TYPES:
            balance += e.amount
        elif e.entry_type in DEBIT_TYPES:
            balance -= e.amount
        elif e.entry_type in HOLD_TYPES:
            held += e.amount
        elif e.entry_type in RELEASE_TYPES:
            held -= e.amount
    balance = _q(balance)
    held = _q(max(held, Decimal("0")))
    available = _q(balance - held)
    return {"balance": balance, "held": held, "available": available}


async def _add_entry(
    db: AsyncSession,
    *,
    work_token_id: int,
    entry_type: TokenLedgerType,
    amount: Decimal,
    idempotency_key: str,
    actor_id: int | None = None,
    requisite_id: int | None = None,
    comment: str | None = None,
) -> TokenLedger:
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    amount = _q(amount)
    existing = await db.execute(
        select(TokenLedger).where(TokenLedger.idempotency_key == idempotency_key)
    )
    found = existing.scalar_one_or_none()
    if found:
        return found

    entry = TokenLedger(
        work_token_id=work_token_id,
        entry_type=entry_type,
        amount=amount,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
        requisite_id=requisite_id,
        comment=comment,
    )
    db.add(entry)
    await db.flush()
    return entry


async def deposit(
    db: AsyncSession,
    work_token_id: int,
    amount: Decimal,
    *,
    actor_id: int | None,
    idempotency_key: str,
    comment: str | None = None,
) -> TokenLedger:
    return await _add_entry(
        db,
        work_token_id=work_token_id,
        entry_type=TokenLedgerType.deposit,
        amount=amount,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
        comment=comment,
    )


async def credit(
    db: AsyncSession,
    work_token_id: int,
    amount: Decimal,
    *,
    actor_id: int | None,
    idempotency_key: str,
    requisite_id: int | None = None,
    comment: str | None = None,
    entry_type: TokenLedgerType = TokenLedgerType.credit,
) -> TokenLedger:
    if entry_type not in (TokenLedgerType.credit, TokenLedgerType.payout_bonus):
        raise ValueError("Invalid credit entry type")
    return await _add_entry(
        db,
        work_token_id=work_token_id,
        entry_type=entry_type,
        amount=amount,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
        requisite_id=requisite_id,
        comment=comment,
    )


async def debit(
    db: AsyncSession,
    work_token_id: int,
    amount: Decimal,
    *,
    actor_id: int | None,
    idempotency_key: str,
    requisite_id: int | None = None,
    comment: str | None = None,
) -> TokenLedger:
    bals = await compute_token_balances(db, work_token_id)
    if amount > bals["available"] + bals["held"]:
        # allow chargeback up to full balance (including held) for loss events
        if amount > bals["balance"]:
            raise HTTPException(status_code=400, detail="Insufficient token balance for debit")
    return await _add_entry(
        db,
        work_token_id=work_token_id,
        entry_type=TokenLedgerType.debit,
        amount=amount,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
        requisite_id=requisite_id,
        comment=comment,
    )


async def withdraw(
    db: AsyncSession,
    work_token_id: int,
    amount: Decimal,
    *,
    actor_id: int | None,
    idempotency_key: str,
    comment: str | None = None,
) -> TokenLedger:
    bals = await compute_token_balances(db, work_token_id)
    if amount > bals["available"]:
        raise HTTPException(status_code=400, detail="Insufficient available balance")
    return await _add_entry(
        db,
        work_token_id=work_token_id,
        entry_type=TokenLedgerType.withdraw,
        amount=amount,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
        comment=comment,
    )


async def hold_for_requisite(
    db: AsyncSession,
    work_token: WorkToken,
    requisite_id: int,
    exposure_usdt: Decimal,
    *,
    actor_id: int | None,
) -> TokenLedger | None:
    if work_token.deposit_exempt:
        return None
    bals = await compute_token_balances(db, work_token.id)
    exposure = _q(exposure_usdt)
    if exposure > bals["available"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient working deposit: need {exposure} USDT, "
                f"available {bals['available']} USDT"
            ),
        )
    return await _add_entry(
        db,
        work_token_id=work_token.id,
        entry_type=TokenLedgerType.hold,
        amount=exposure,
        idempotency_key=f"hold-req-{requisite_id}",
        actor_id=actor_id,
        requisite_id=requisite_id,
        comment="Hold for open traffic",
    )


async def release_for_requisite(
    db: AsyncSession,
    work_token_id: int,
    requisite_id: int,
    amount: Decimal,
    *,
    actor_id: int | None,
) -> TokenLedger | None:
    if amount <= 0:
        return None
    return await _add_entry(
        db,
        work_token_id=work_token_id,
        entry_type=TokenLedgerType.release,
        amount=amount,
        idempotency_key=f"release-req-{requisite_id}",
        actor_id=actor_id,
        requisite_id=requisite_id,
        comment="Release hold on close/cancel",
    )


async def require_token_for_trader(db: AsyncSession, trader: User) -> WorkToken | None:
    """Return active token; None only when trader is deposit_exempt."""
    if trader.deposit_exempt:
        token = await get_active_token_for_user(db, trader.id)
        return token
    token = await get_active_token_for_user(db, trader.id)
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Trader has no work token / working deposit. Ask admin to assign a token and deposit.",
        )
    return token
