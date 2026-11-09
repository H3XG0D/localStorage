"""Work tokens, deposits, holds, payouts, API keys, float settle, chargeback."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import hash_password, require_role
from app.core.database import get_db
from app.models import (
    ApiKey,
    AppSettings,
    Requisite,
    TokenLedger,
    TokenLedgerType,
    TokenMember,
    User,
    UserRole,
    WorkToken,
    WorkingRateMode,
)
from app.schemas import (
    ApiKeyCreate,
    ApiKeyResponse,
    ChargebackRequest,
    FloatSettleRequest,
    PayoutRequest,
    RateResponse,
    TeamleadMeResponse,
    TeamleadSummaryResponse,
    TeamleadTraderCreate,
    TeamleadTraderRow,
    TeamleadTraderUpdate,
    TokenAmountRequest,
    TokenLedgerEntryResponse,
    TraderWalletAmountRequest,
    WorkTokenCreate,
    WorkTokenResponse,
    WorkingRateFromRapiraRequest,
    WorkingRateResponse,
    WorkingRateSetRequest,
)
from app.services import float_ledger, token_ledger
from app.services import working_rate as wr_svc
from app.services.rapira import fetch_rapira_usdt_rub
from app.services.teamlead_pool import assert_trader_percent_within_pool, resolve_pool_percent


router = APIRouter(tags=["tokens"])


async def _token_response(
    db: AsyncSession,
    token: WorkToken,
    *,
    withdraw_fee_usdt: Decimal | None = None,
) -> WorkTokenResponse:
    bals = await token_ledger.compute_token_balances(db, token.id)
    members = await db.execute(
        select(TokenMember.user_id).where(
            TokenMember.work_token_id == token.id,
            TokenMember.is_active == True,  # noqa: E712
        )
    )
    return WorkTokenResponse(
        id=token.id,
        name=token.name,
        owner_id=token.owner_id,
        deposit_exempt=token.deposit_exempt,
        is_active=token.is_active,
        created_at=token.created_at,
        balance=bals["balance"],
        held=bals["held"],
        available=bals["available"],
        member_ids=list(members.scalars().all()),
        withdraw_fee_usdt=withdraw_fee_usdt,
    )


def _wr_resp(row) -> WorkingRateResponse:
    return WorkingRateResponse(
        id=row.id,
        rate=row.rate,
        mode=row.mode.value if hasattr(row.mode, "value") else str(row.mode),
        valid_until=row.valid_until,
        comment=row.comment,
        set_by_id=row.set_by_id,
        created_at=row.created_at,
    )


@router.get("/rates/rapira", response_model=RateResponse)
async def rapira_rate(
    _user: Annotated[User, Depends(require_role(UserRole.trader, UserRole.admin, UserRole.teamlead, UserRole.dolivshchik))],
):
    rate, source = await fetch_rapira_usdt_rub()
    return RateResponse(rate=rate, source=source)


@router.get("/rates/working", response_model=WorkingRateResponse)
async def get_working_rate(
    _user: Annotated[User, Depends(require_role(UserRole.trader, UserRole.admin, UserRole.teamlead, UserRole.dolivshchik))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = await wr_svc.get_active_working_rate(db)
    return _wr_resp(row)


@router.get("/admin/rates/working/history", response_model=list[WorkingRateResponse])
async def working_rate_history(
    _user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.models import WorkingRate

    result = await db.execute(select(WorkingRate).order_by(WorkingRate.id.desc()).limit(50))
    return [_wr_resp(r) for r in result.scalars().all()]


@router.post("/admin/rates/working", response_model=WorkingRateResponse, status_code=201)
async def set_working_rate(
    data: WorkingRateSetRequest,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        mode = WorkingRateMode(data.mode)
    except ValueError as e:
        raise HTTPException(400, f"Invalid mode: {data.mode}") from e
    if mode == WorkingRateMode.fixed and data.valid_until is None:
        raise HTTPException(400, "valid_until required for fixed mode")
    row = await wr_svc.set_working_rate(
        db,
        rate=data.rate,
        mode=mode,
        actor=user,
        valid_until=data.valid_until,
        comment=data.comment,
    )
    return _wr_resp(row)


@router.post("/admin/rates/working/from-rapira", response_model=WorkingRateResponse, status_code=201)
async def set_working_rate_from_rapira(
    data: WorkingRateFromRapiraRequest,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = await wr_svc.set_from_rapira(
        db,
        actor=user,
        comment=data.comment,
        valid_until=data.valid_until,
    )
    return _wr_resp(row)


@router.get("/admin/work-tokens", response_model=list[WorkTokenResponse])
async def list_work_tokens(
    _user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(WorkToken).order_by(WorkToken.id.desc()))
    return [await _token_response(db, t) for t in result.scalars().all()]


@router.post("/admin/work-tokens", response_model=WorkTokenResponse, status_code=201)
async def create_work_token(
    data: WorkTokenCreate,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    token = WorkToken(
        name=data.name,
        owner_id=data.owner_id,
        deposit_exempt=data.deposit_exempt,
        is_active=True,
    )
    db.add(token)
    await db.flush()
    for uid in data.member_user_ids:
        await token_ledger.ensure_membership(db, token.id, uid)
    return await _token_response(db, token)


@router.post("/admin/work-tokens/{token_id}/members/{user_id}", response_model=WorkTokenResponse)
async def add_token_member(
    token_id: int,
    user_id: int,
    _user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    token = await db.get(WorkToken, token_id)
    if not token:
        raise HTTPException(404, "Work token not found")
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    await token_ledger.ensure_membership(db, token_id, user_id)
    return await _token_response(db, token)


@router.post("/admin/work-tokens/{token_id}/deposit", response_model=TokenLedgerEntryResponse)
async def admin_deposit(
    token_id: int,
    data: TokenAmountRequest,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    token = await db.get(WorkToken, token_id)
    if not token:
        raise HTTPException(404, "Work token not found")
    key = data.idempotency_key or f"deposit-{token_id}-{uuid.uuid4().hex}"
    entry = await token_ledger.deposit(
        db, token_id, data.amount, actor_id=user.id, idempotency_key=key, comment=data.comment
    )
    return TokenLedgerEntryResponse(
        id=entry.id,
        work_token_id=entry.work_token_id,
        entry_type=entry.entry_type.value,
        amount=entry.amount,
        idempotency_key=entry.idempotency_key,
        requisite_id=entry.requisite_id,
        actor_id=entry.actor_id,
        comment=entry.comment,
        created_at=entry.created_at,
    )


@router.post("/admin/work-tokens/{token_id}/withdraw", response_model=TokenLedgerEntryResponse)
async def admin_withdraw(
    token_id: int,
    data: TokenAmountRequest,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    token = await db.get(WorkToken, token_id)
    if not token:
        raise HTTPException(404, "Work token not found")
    key = data.idempotency_key or f"withdraw-{token_id}-{uuid.uuid4().hex}"
    entry = await token_ledger.withdraw(
        db, token_id, data.amount, actor_id=user.id, idempotency_key=key, comment=data.comment
    )
    return TokenLedgerEntryResponse(
        id=entry.id,
        work_token_id=entry.work_token_id,
        entry_type=entry.entry_type.value,
        amount=entry.amount,
        idempotency_key=entry.idempotency_key,
        requisite_id=entry.requisite_id,
        actor_id=entry.actor_id,
        comment=entry.comment,
        created_at=entry.created_at,
    )


@router.post("/admin/requisites/{requisite_id}/chargeback", response_model=TokenLedgerEntryResponse)
async def chargeback(
    requisite_id: int,
    data: ChargebackRequest,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    requisite = await db.get(Requisite, requisite_id)
    if not requisite:
        raise HTTPException(404, "Requisite not found")
    if not requisite.work_token_id:
        raise HTTPException(400, "Requisite has no work token")
    key = data.idempotency_key or f"chargeback-req-{requisite_id}-{uuid.uuid4().hex}"
    # Release remaining hold first so available covers debit path cleanly
    if requisite.hold_usdt and requisite.hold_usdt > 0:
        await token_ledger.release_for_requisite(
            db, requisite.work_token_id, requisite.id, Decimal(requisite.hold_usdt), actor_id=user.id
        )
        requisite.hold_usdt = Decimal("0")
    entry = await token_ledger.debit(
        db,
        requisite.work_token_id,
        data.amount_usdt,
        actor_id=user.id,
        idempotency_key=key,
        requisite_id=requisite_id,
        comment=data.comment or f"Chargeback float≈{requisite.float_rub}",
    )
    return TokenLedgerEntryResponse(
        id=entry.id,
        work_token_id=entry.work_token_id,
        entry_type=entry.entry_type.value,
        amount=entry.amount,
        idempotency_key=entry.idempotency_key,
        requisite_id=entry.requisite_id,
        actor_id=entry.actor_id,
        comment=entry.comment,
        created_at=entry.created_at,
    )


@router.post("/admin/work-tokens/{token_id}/api-keys", response_model=ApiKeyResponse, status_code=201)
async def create_api_key(
    token_id: int,
    data: ApiKeyCreate,
    _user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    token = await db.get(WorkToken, token_id)
    if not token:
        raise HTTPException(404, "Work token not found")
    raw = f"dlv_{secrets.token_urlsafe(32)}"
    prefix = raw[:12]
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    row = ApiKey(
        work_token_id=token_id,
        name=data.name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=data.scopes,
        is_active=True,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return ApiKeyResponse(
        id=row.id,
        work_token_id=row.work_token_id,
        name=row.name,
        key_prefix=row.key_prefix,
        scopes=row.scopes,
        is_active=row.is_active,
        created_at=row.created_at,
        raw_key=raw,
    )


@router.get("/trader/wallet", response_model=WorkTokenResponse)
async def trader_wallet(
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    token = await token_ledger.ensure_personal_token(db, user)
    settings = await db.get(AppSettings, 1)
    fee = (
        Decimal(settings.withdraw_fee_usdt)
        if settings and settings.withdraw_fee_usdt is not None
        else Decimal("3")
    )
    return await _token_response(db, token, withdraw_fee_usdt=fee)


@router.get("/trader/wallet/ledger", response_model=list[TokenLedgerEntryResponse])
async def trader_wallet_ledger(
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    token = await token_ledger.ensure_personal_token(db, user)
    result = await db.execute(
        select(TokenLedger)
        .where(TokenLedger.work_token_id == token.id)
        .order_by(TokenLedger.id.desc())
        .limit(200)
    )
    return [
        TokenLedgerEntryResponse(
            id=e.id,
            work_token_id=e.work_token_id,
            entry_type=e.entry_type.value,
            amount=e.amount,
            idempotency_key=e.idempotency_key,
            requisite_id=e.requisite_id,
            actor_id=e.actor_id,
            comment=e.comment,
            created_at=e.created_at,
        )
        for e in result.scalars().all()
    ]


@router.post("/trader/wallet/deposit", response_model=TokenLedgerEntryResponse)
async def trader_wallet_deposit(
    data: TraderWalletAmountRequest,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Deprecated: use POST /trader/wallet/requests (admin approval)."""
    raise HTTPException(
        400,
        "Self-deposit disabled. Create a deposit request via POST /trader/wallet/requests",
    )


@router.post("/trader/wallet/withdraw")
async def trader_wallet_withdraw(
    data: TraderWalletAmountRequest,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Deprecated: use POST /trader/wallet/requests with kind=withdraw."""
    raise HTTPException(
        400,
        "Self-withdraw disabled. Create a withdraw request via POST /trader/wallet/requests",
    )


@router.get("/trader/float")
async def trader_float(
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await float_ledger.float_summary_for_trader(db, user.id)


@router.post("/trader/requisites/{requisite_id}/settle-float")
async def trader_settle_float(
    requisite_id: int,
    data: FloatSettleRequest,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    requisite = await db.get(Requisite, requisite_id)
    if not requisite or requisite.trader_id != user.id:
        raise HTTPException(404, "Requisite not found")
    entry = await float_ledger.settle_float(
        db,
        requisite,
        data.amount,
        actor_id=user.id,
        idempotency_key=f"settle-{requisite_id}-{uuid.uuid4().hex}",
        comment=data.comment,
    )
    return {"float_rub": str(requisite.float_rub), "entry_id": entry.id}


@router.post("/trader/payout")
async def trader_payout(
    data: PayoutRequest,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Card payout: credit deposit return + payout_bonus_percent."""
    token = await token_ledger.require_token_for_trader(db, user)
    if not token:
        raise HTTPException(400, "No work token for payout")
    settings = await db.get(AppSettings, 1)
    bonus_pct = settings.payout_bonus_percent if settings else Decimal("1")
    bonus = (data.amount_usdt * bonus_pct / Decimal("100")).quantize(Decimal("0.000001"))
    key_base = data.idempotency_key or uuid.uuid4().hex
    await token_ledger.credit(
        db,
        token.id,
        data.amount_usdt,
        actor_id=user.id,
        idempotency_key=f"payout-principal-{key_base}",
        requisite_id=data.requisite_id,
        comment=data.comment or "Payout principal return",
    )
    if bonus > 0:
        await token_ledger.credit(
            db,
            token.id,
            bonus,
            actor_id=user.id,
            idempotency_key=f"payout-bonus-{key_base}",
            requisite_id=data.requisite_id,
            comment=f"Payout bonus {bonus_pct}%",
            entry_type=TokenLedgerType.payout_bonus,
        )
    if data.requisite_id:
        req = await db.get(Requisite, data.requisite_id)
        if req and req.trader_id == user.id and req.float_rub and req.float_rub > 0:
            # Best-effort: settle float by amount*rate approximation is not here;
            # trader should settle float separately in RUB.
            pass
    bals = await token_ledger.compute_token_balances(db, token.id)
    return {
        "credited_principal": str(data.amount_usdt),
        "credited_bonus": str(bonus),
        "available": str(bals["available"]),
    }


# ── Teamlead ────────────────────────────────────────────────────────────────

async def _teamlead_trader_row(db: AsyncSession, t: User, pool: Decimal | None = None) -> TeamleadTraderRow:
    float_sum = await float_ledger.float_summary_for_trader(db, t.id)
    token = await token_ledger.get_active_token_for_user(db, t.id)
    bals = await token_ledger.compute_token_balances(db, token.id) if token else None
    commissions = None
    if token:
        result = await db.execute(
            select(func.coalesce(func.sum(TokenLedger.amount), 0)).where(
                TokenLedger.work_token_id == token.id,
                TokenLedger.entry_type.in_([TokenLedgerType.credit, TokenLedgerType.payout_bonus]),
            )
        )
        commissions = Decimal(str(result.scalar() or 0))
    keep = None
    if pool is not None and t.profit_percent is not None:
        keep = max(Decimal("0"), pool - Decimal(t.profit_percent))
    return TeamleadTraderRow(
        id=t.id,
        login=t.login,
        full_name=t.full_name,
        is_active=t.is_active,
        profit_percent=t.profit_percent,
        teamlead_keep_percent=keep,
        deposit_exempt=t.deposit_exempt,
        total_float_rub=Decimal(str(float_sum["total_float_rub"])),
        token_available=bals["available"] if bals else None,
        token_held=bals["held"] if bals else None,
        commissions_usdt=commissions,
    )


@router.get("/teamlead/me", response_model=TeamleadMeResponse)
async def teamlead_me(
    user: Annotated[User, Depends(require_role(UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    settings = await db.get(AppSettings, 1)
    pool = resolve_pool_percent(user, settings)
    return TeamleadMeResponse(
        id=user.id,
        login=user.login,
        full_name=user.full_name,
        teamlead_percent=pool,
        pool_percent=pool,
        max_trader_percent=pool,
    )


@router.get("/teamlead/summary", response_model=TeamleadSummaryResponse)
async def teamlead_summary(
    user: Annotated[User, Depends(require_role(UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    settings = await db.get(AppSettings, 1)
    pool = resolve_pool_percent(user, settings)
    traders = (
        await db.execute(
            select(User).where(User.teamlead_id == user.id, User.role == UserRole.trader)
        )
    ).scalars().all()
    team_float = Decimal("0")
    for t in traders:
        fs = await float_ledger.float_summary_for_trader(db, t.id)
        team_float += Decimal(str(fs["total_float_rub"]))

    token = await token_ledger.get_active_token_for_user(db, user.id)
    if not token:
        result = await db.execute(
            select(WorkToken).where(WorkToken.owner_id == user.id, WorkToken.is_active == True).limit(1)  # noqa: E712
        )
        token = result.scalar_one_or_none()

    bals = await token_ledger.compute_token_balances(db, token.id) if token else None
    credits = Decimal("0")
    if token:
        result = await db.execute(
            select(func.coalesce(func.sum(TokenLedger.amount), 0)).where(
                TokenLedger.work_token_id == token.id,
                TokenLedger.entry_type == TokenLedgerType.credit,
            )
        )
        credits = Decimal(str(result.scalar() or 0))

    return TeamleadSummaryResponse(
        teamlead_percent=pool,
        pool_percent=pool,
        max_trader_percent=pool,
        traders_count=len(traders),
        token_balance=bals["balance"] if bals else None,
        token_available=bals["available"] if bals else None,
        token_held=bals["held"] if bals else None,
        credits_usdt=credits,
        team_float_rub=team_float,
    )


@router.get("/teamlead/traders", response_model=list[TeamleadTraderRow])
async def teamlead_traders(
    user: Annotated[User, Depends(require_role(UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    settings = await db.get(AppSettings, 1)
    pool = resolve_pool_percent(user, settings)
    result = await db.execute(
        select(User).where(User.teamlead_id == user.id, User.role == UserRole.trader).order_by(User.id)
    )
    traders = result.scalars().all()
    return [await _teamlead_trader_row(db, t, pool) for t in traders]


@router.post("/teamlead/traders", response_model=TeamleadTraderRow, status_code=201)
async def teamlead_create_trader(
    data: TeamleadTraderCreate,
    user: Annotated[User, Depends(require_role(UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing = await db.execute(select(User).where(User.login == data.login))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Login already exists")

    await assert_trader_percent_within_pool(
        db, profit_percent=data.profit_percent, teamlead_id=user.id
    )

    trader = User(
        login=data.login,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=UserRole.trader,
        profit_percent=data.profit_percent,
        teamlead_id=user.id,
        is_active=True,
        deposit_exempt=False,
    )
    db.add(trader)
    await db.flush()

    await token_ledger.ensure_personal_token(db, trader, owner_id=trader.id)
    await db.flush()
    settings = await db.get(AppSettings, 1)
    pool = resolve_pool_percent(user, settings)
    return await _teamlead_trader_row(db, trader, pool)


@router.patch("/teamlead/traders/{trader_id}", response_model=TeamleadTraderRow)
async def teamlead_update_trader(
    trader_id: int,
    data: TeamleadTraderUpdate,
    user: Annotated[User, Depends(require_role(UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    trader = await db.get(User, trader_id)
    if not trader or trader.teamlead_id != user.id or trader.role != UserRole.trader:
        raise HTTPException(404, "Trader not found in your team")
    if data.full_name is not None:
        trader.full_name = data.full_name
    if data.profit_percent is not None:
        await assert_trader_percent_within_pool(
            db, profit_percent=data.profit_percent, teamlead_id=user.id
        )
        trader.profit_percent = data.profit_percent
        from app.services.trader_profit import apply_trader_profit_percent

        await apply_trader_profit_percent(db, trader.id, trader.profit_percent)
    if data.is_active is not None:
        trader.is_active = data.is_active
    await db.flush()
    settings = await db.get(AppSettings, 1)
    pool = resolve_pool_percent(user, settings)
    return await _teamlead_trader_row(db, trader, pool)


@router.post("/teamlead/traders/{trader_id}/pause")
async def teamlead_pause_trader(
    trader_id: int,
    user: Annotated[User, Depends(require_role(UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    trader = await db.get(User, trader_id)
    if not trader or trader.teamlead_id != user.id:
        raise HTTPException(404, "Trader not found in your team")
    trader.is_active = False
    await db.flush()
    return {"id": trader.id, "is_active": False}


@router.post("/teamlead/traders/{trader_id}/resume")
async def teamlead_resume_trader(
    trader_id: int,
    user: Annotated[User, Depends(require_role(UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    trader = await db.get(User, trader_id)
    if not trader or trader.teamlead_id != user.id:
        raise HTTPException(404, "Trader not found in your team")
    trader.is_active = True
    await db.flush()
    return {"id": trader.id, "is_active": True}


@router.get("/teamlead/wallet", response_model=WorkTokenResponse)
async def teamlead_wallet(
    user: Annotated[User, Depends(require_role(UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    token = await token_ledger.ensure_personal_token(db, user)
    settings = await db.get(AppSettings, 1)
    fee = (
        Decimal(settings.withdraw_fee_usdt)
        if settings and settings.withdraw_fee_usdt is not None
        else Decimal("3")
    )
    return await _token_response(db, token, withdraw_fee_usdt=fee)


@router.get("/teamlead/wallet/ledger", response_model=list[TokenLedgerEntryResponse])
async def teamlead_wallet_ledger(
    user: Annotated[User, Depends(require_role(UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    token = await token_ledger.ensure_personal_token(db, user)
    result = await db.execute(
        select(TokenLedger)
        .where(TokenLedger.work_token_id == token.id)
        .order_by(TokenLedger.id.desc())
        .limit(200)
    )
    return [
        TokenLedgerEntryResponse(
            id=e.id,
            work_token_id=e.work_token_id,
            entry_type=e.entry_type.value,
            amount=e.amount,
            idempotency_key=e.idempotency_key,
            requisite_id=e.requisite_id,
            actor_id=e.actor_id,
            comment=e.comment,
            created_at=e.created_at,
        )
        for e in result.scalars().all()
    ]


# ── Integration API (API key) ────────────────────────────────────────────────

async def _api_key_token(
    db: AsyncSession,
    x_api_key: str | None,
) -> WorkToken:
    if not x_api_key:
        raise HTTPException(401, "Missing X-API-Key")
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    result = await db.execute(
        select(ApiKey)
        .options(selectinload(ApiKey.work_token))
        .where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)  # noqa: E712
    )
    row = result.scalar_one_or_none()
    if not row or not row.work_token or not row.work_token.is_active:
        raise HTTPException(401, "Invalid API key")
    from datetime import datetime, timezone

    row.last_used_at = datetime.now(timezone.utc)
    return row.work_token


@router.get("/integration/balance")
async def integration_balance(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_api_key: Annotated[str | None, Header()] = None,
):
    token = await _api_key_token(db, x_api_key)
    bals = await token_ledger.compute_token_balances(db, token.id)
    return {"work_token_id": token.id, "name": token.name, **{k: str(v) for k, v in bals.items()}}


@router.get("/integration/holds")
async def integration_holds(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_api_key: Annotated[str | None, Header()] = None,
):
    token = await _api_key_token(db, x_api_key)
    result = await db.execute(
        select(Requisite).where(
            Requisite.work_token_id == token.id,
            Requisite.hold_usdt.is_not(None),
        )
    )
    items = [
        {
            "requisite_id": r.id,
            "name": r.name,
            "status": r.status.value,
            "hold_usdt": str(r.hold_usdt or 0),
            "float_rub": str(r.float_rub or 0),
        }
        for r in result.scalars().all()
        if r.hold_usdt and r.hold_usdt > 0
    ]
    return {"work_token_id": token.id, "holds": items}


@router.get("/integration/float")
async def integration_float(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_api_key: Annotated[str | None, Header()] = None,
):
    token = await _api_key_token(db, x_api_key)
    result = await db.execute(select(Requisite).where(Requisite.work_token_id == token.id))
    items = []
    total = Decimal("0")
    for r in result.scalars().all():
        fr = r.float_rub or Decimal("0")
        total += fr
        items.append(
            {
                "requisite_id": r.id,
                "name": r.name,
                "trader_id": r.trader_id,
                "status": r.status.value,
                "float_rub": str(fr),
            }
        )
    return {"work_token_id": token.id, "total_float_rub": str(total), "items": items}
