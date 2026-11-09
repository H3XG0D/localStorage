from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import require_role
from app.core.database import get_db
from app.models import AppSettings as AppSettingsModel
from app.models import (
    DolivRequest,
    DolivRequestStatus,
    Doliv,
    DealResult,
    Requisite,
    RequisiteStatus,
    TraderCard,
    User,
    UserRole,
    Zaliv,
)
from app.schemas import (
    DealResultResponse,
    DolivRequestResponse,
    ReceiptResponse,
    RequisiteCreate,
    RequisiteDetail,
    RequisiteResponse,
    ZalivResponse,
)
from app.services.files import safe_file_response, save_receipt
from app.services.profit import (
    calc_avg_rate,
    calc_current_profit,
    calc_remaining,
    calc_required_doliv_amount,
    calc_zaliv_total,
)
from app.services.notifications import notify_roles
from app.services.stats import get_trader_stats
from app.services.trader_profit import MAX_DOLIV_RATE, MIN_DOLIV_RATE, resolve_trader_profit_percent

router = APIRouter(prefix="/trader", tags=["trader"])


async def _get_requisite_detail(db: AsyncSession, requisite: Requisite) -> RequisiteDetail:
    zalivs = sorted(requisite.zalivs, key=lambda z: z.created_at)
    zaliv_total = calc_zaliv_total(zalivs)
    remaining = calc_remaining(requisite, zalivs)
    avg_rate = calc_avg_rate(zalivs)
    current_profit = calc_current_profit(zalivs, requisite.target_rate)

    return RequisiteDetail(
        id=requisite.id,
        trader_id=requisite.trader_id,
        name=requisite.name,
        total_amount=requisite.total_amount,
        target_rate=requisite.target_rate,
        comment=requisite.comment,
        status=requisite.status,
        float_rub=requisite.float_rub or Decimal("0"),
        hold_usdt=requisite.hold_usdt,
        work_token_id=requisite.work_token_id,
        created_at=requisite.created_at,
        updated_at=requisite.updated_at,
        zalivs=[ZalivResponse.model_validate(z) for z in zalivs],
        zaliv_total=zaliv_total,
        remaining=remaining,
        avg_rate=avg_rate,
        current_profit=current_profit,
    )


async def _get_active_doliv_request(db: AsyncSession, requisite_id: int) -> DolivRequest | None:
    result = await db.execute(
        select(DolivRequest).where(
            DolivRequest.requisite_id == requisite_id,
            DolivRequest.status.in_([DolivRequestStatus.pending, DolivRequestStatus.in_progress]),
        )
    )
    return result.scalar_one_or_none()


async def _enrich_trader_request(db: AsyncSession, dr: DolivRequest) -> DolivRequestResponse:
    req = await db.get(Requisite, dr.requisite_id)
    trader = await db.get(User, req.trader_id) if req else None
    assigned = await db.get(User, dr.assigned_dolivshchik_id) if dr.assigned_dolivshchik_id else None
    return DolivRequestResponse(
        id=dr.id,
        requisite_id=dr.requisite_id,
        required_amount=dr.required_amount,
        status=dr.status,
        sent_at=dr.sent_at,
        assigned_dolivshchik_id=dr.assigned_dolivshchik_id,
        assigned_dolivshchik_name=assigned.full_name if assigned else None,
        requisite_name=req.name if req else None,
        target_rate=req.target_rate if req else None,
        trader_name=trader.full_name if trader else None,
        zaliv_total=calc_zaliv_total(req.zalivs) if req and "zalivs" in req.__dict__ else None,
    )


@router.get("/requisites", response_model=list[RequisiteResponse])
async def list_requisites(
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: RequisiteStatus | None = None,
):
    q = select(Requisite).where(Requisite.trader_id == user.id).order_by(Requisite.created_at.desc())
    if status:
        q = q.where(Requisite.status == status)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/doliv-requests", response_model=list[DolivRequestResponse])
async def list_trader_doliv_requests(
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(DolivRequest)
        .join(Requisite, Requisite.id == DolivRequest.requisite_id)
        .options(selectinload(DolivRequest.requisite).selectinload(Requisite.zalivs))
        .where(Requisite.trader_id == user.id)
        .order_by(DolivRequest.sent_at.desc())
    )
    return [await _enrich_trader_request(db, dr) for dr in result.scalars().all()]


@router.get("/receipts", response_model=list[ReceiptResponse])
async def list_trader_receipts(
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    zaliv_result = await db.execute(
        select(Zaliv)
        .options(selectinload(Zaliv.requisite))
        .join(Requisite, Requisite.id == Zaliv.requisite_id)
        .where(Requisite.trader_id == user.id)
        .order_by(Zaliv.created_at.desc())
    )
    doliv_result = await db.execute(
        select(Doliv)
        .options(selectinload(Doliv.request).selectinload(DolivRequest.requisite))
        .options(selectinload(Doliv.dolivshchik))
        .join(DolivRequest, DolivRequest.id == Doliv.request_id)
        .join(Requisite, Requisite.id == DolivRequest.requisite_id)
        .where(Requisite.trader_id == user.id)
        .order_by(Doliv.completed_at.desc())
    )

    receipts: list[ReceiptResponse] = []
    for zaliv in zaliv_result.scalars().all():
        receipts.append(
            ReceiptResponse(
                id=zaliv.id,
                type="zaliv",
                requisite_id=zaliv.requisite.id,
                requisite_name=zaliv.requisite.name,
                uploader_name=user.full_name,
                amount=zaliv.amount,
                rate=zaliv.rate,
                receipt_path=zaliv.receipt_path,
                created_at=zaliv.created_at,
            )
        )

    for doliv in doliv_result.scalars().all():
        requisite = doliv.request.requisite
        receipts.append(
            ReceiptResponse(
                id=doliv.id,
                type="doliv",
                requisite_id=requisite.id,
                requisite_name=requisite.name,
                uploader_name=doliv.dolivshchik.full_name,
                amount=doliv.amount,
                rate=doliv.rate,
                receipt_path=doliv.receipt_path,
                created_at=doliv.completed_at,
            )
        )

    return sorted(receipts, key=lambda r: r.created_at, reverse=True)


@router.post("/requisites", response_model=RequisiteResponse, status_code=status.HTTP_201_CREATED)
async def create_requisite(
    data: RequisiteCreate,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Legacy session create. Prefer POST /trader/cards + go-online (card-first). Kept for tests/compat."""
    from app.services import token_ledger
    from app.services.rapira import exposure_usdt

    token = await token_ledger.require_token_for_trader(db, user)
    hold_amount = None
    work_token_id = None
    if token and not (user.deposit_exempt or token.deposit_exempt):
        work_token_id = token.id
        hold_amount = exposure_usdt(data.total_amount, data.target_rate)

    req = Requisite(
        trader_id=user.id,
        name=data.name,
        total_amount=data.total_amount,
        target_rate=data.target_rate,
        comment=data.comment,
        status=RequisiteStatus.active,
        float_rub=Decimal("0"),
        work_token_id=work_token_id,
        hold_usdt=hold_amount,
    )
    db.add(req)
    await db.flush()

    if token and hold_amount is not None:
        await token_ledger.hold_for_requisite(
            db, token, req.id, hold_amount, actor_id=user.id
        )

    await db.refresh(req)
    return req


@router.get("/requisites/{requisite_id}", response_model=RequisiteDetail)
async def get_requisite(
    requisite_id: int,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Requisite)
        .options(selectinload(Requisite.zalivs))
        .where(Requisite.id == requisite_id, Requisite.trader_id == user.id)
    )
    requisite = result.scalar_one_or_none()
    if not requisite:
        raise HTTPException(status_code=404, detail="Requisite not found")
    return await _get_requisite_detail(db, requisite)


@router.post("/requisites/{requisite_id}/zalivs", response_model=ZalivResponse, status_code=201)
async def add_zaliv(
    requisite_id: int,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
    amount: Annotated[Decimal, Form()],
    rate: Annotated[Decimal, Form()],
    receipt: Annotated[UploadFile, File()],
):
    result = await db.execute(
        select(Requisite)
        .options(selectinload(Requisite.zalivs))
        .where(Requisite.id == requisite_id, Requisite.trader_id == user.id)
        .with_for_update()
    )
    requisite = result.scalar_one_or_none()
    if not requisite:
        raise HTTPException(status_code=404, detail="Requisite not found")
    if requisite.status in (
        RequisiteStatus.closed,
        RequisiteStatus.archive,
        RequisiteStatus.awaiting_doliv,
        RequisiteStatus.doliv_in_progress,
    ):
        raise HTTPException(status_code=400, detail="Cannot add zaliv in current status")
    if amount <= 0 or rate <= 0:
        raise HTTPException(status_code=400, detail="Amount and rate must be positive")
    if rate < MIN_DOLIV_RATE or rate > MAX_DOLIV_RATE:
        raise HTTPException(
            status_code=400,
            detail=f"Rate must be between {MIN_DOLIV_RATE} and {MAX_DOLIV_RATE}",
        )

    profit_percent = await resolve_trader_profit_percent(db, user)
    if profit_percent < 0:
        raise HTTPException(status_code=400, detail="Trader profit percent is not configured")

    current_total = calc_zaliv_total(requisite.zalivs)
    remaining_capacity = requisite.total_amount - current_total

    from app.services.payment_bands import assert_zaliv_payment_allowed

    card = None
    if requisite.card_id:
        card = await db.get(TraderCard, requisite.card_id)
    assert_zaliv_payment_allowed(
        amount,
        bands=card.payment_bands if card else None,
        min_payment_rub=card.min_payment_rub if card else None,
        max_payment_rub=card.max_payment_rub if card else None,
        remaining_capacity=remaining_capacity,
    )

    app_cfg = await db.get(AppSettingsModel, 1)
    receipt_path = await save_receipt(
        requisite_id,
        receipt,
        max_size_bytes=(app_cfg.max_upload_mb * 1024 * 1024) if app_cfg else None,
        allowed_formats=([f.strip() for f in app_cfg.receipt_formats.split(",") if f.strip()] if app_cfg else None),
    )
    zaliv = Zaliv(
        requisite_id=requisite_id,
        amount=amount,
        rate=rate,
        profit_percent=profit_percent,
        receipt_path=receipt_path,
    )
    db.add(zaliv)
    await db.flush()

    from app.services import float_ledger

    await float_ledger.confirm_payment(
        db, requisite, amount, zaliv_id=zaliv.id, actor_id=user.id
    )

    if requisite.status == RequisiteStatus.active:
        requisite.status = RequisiteStatus.in_work

    await db.refresh(zaliv)
    return zaliv


@router.post("/requisites/{requisite_id}/send-to-doliv")
async def send_to_doliv(
    requisite_id: int,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Lock the requisite row to prevent concurrent send_to_doliv creating duplicate requests
    result = await db.execute(
        select(Requisite)
        .options(selectinload(Requisite.zalivs))
        .where(Requisite.id == requisite_id, Requisite.trader_id == user.id)
        .with_for_update()
    )
    requisite = result.scalar_one_or_none()
    if not requisite:
        raise HTTPException(status_code=404, detail="Requisite not found")

    if requisite.status in (
        RequisiteStatus.closed,
        RequisiteStatus.archive,
        RequisiteStatus.doliv_in_progress,
    ):
        raise HTTPException(status_code=400, detail="Cannot send requisite to doliv in current status")

    required_amount = calc_required_doliv_amount(requisite, requisite.zalivs)
    if required_amount <= 0:
        raise HTTPException(status_code=400, detail="No remaining amount for doliv")
    if not requisite.zalivs or calc_zaliv_total(requisite.zalivs) <= 0:
        raise HTTPException(status_code=400, detail="At least one zaliv is required before sending to doliv")

    already_awaiting = requisite.status == RequisiteStatus.awaiting_doliv

    dr = await _get_active_doliv_request(db, requisite_id)
    if not dr:
        dr = DolivRequest(
            requisite_id=requisite_id,
            required_amount=required_amount,
            status=DolivRequestStatus.pending,
        )
        db.add(dr)
        await db.flush()  # populate dr.id before returning
    else:
        dr.required_amount = required_amount
    requisite.status = RequisiteStatus.awaiting_doliv

    if already_awaiting:
        await notify_roles(
            db,
            [UserRole.dolivshchik],
            "Обновлена заявка на долив",
            f"{user.full_name} обновил сумму долива по реквизиту {requisite.name}: {required_amount} ₽",
            kind="doliv_request",
            link="/doliv",
            exclude_user_ids={user.id},
        )
        await notify_roles(
            db,
            [UserRole.admin],
            "Обновлена заявка на долив",
            f"{user.full_name} обновил сумму долива по реквизиту {requisite.name}: {required_amount} ₽",
            kind="doliv_request",
            link="/admin/doliv-requests",
            exclude_user_ids={user.id},
        )
        return {"message": "Sent to doliv queue", "request_id": dr.id, "required_amount": str(required_amount)}

    await notify_roles(
        db,
        [UserRole.dolivshchik],
        "Новая заявка на долив",
        f"{user.full_name} отправил реквизит {requisite.name} на долив: {required_amount} ₽",
        kind="doliv_request",
        link="/doliv",
        exclude_user_ids={user.id},
    )
    await notify_roles(
        db,
        [UserRole.admin],
        "Новая заявка на долив",
        f"{user.full_name} отправил реквизит {requisite.name} на долив: {required_amount} ₽",
        kind="doliv_request",
        link="/admin/doliv-requests",
        exclude_user_ids={user.id},
    )
    return {"message": "Sent to doliv queue", "request_id": dr.id, "required_amount": str(required_amount)}


@router.get("/requisites/{requisite_id}/deal-result", response_model=DealResultResponse | None)
async def get_trader_deal_result(
    requisite_id: int,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(DealResult)
        .join(Requisite, Requisite.id == DealResult.requisite_id)
        .where(DealResult.requisite_id == requisite_id, Requisite.trader_id == user.id)
    )
    return result.scalar_one_or_none()


@router.get("/requisites/{requisite_id}/receipts.pdf")
async def download_trader_merged_pdf(
    requisite_id: int,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(DealResult)
        .join(Requisite, Requisite.id == DealResult.requisite_id)
        .where(DealResult.requisite_id == requisite_id, Requisite.trader_id == user.id)
    )
    dr = result.scalar_one_or_none()
    if not dr or not dr.merged_receipt_path:
        raise HTTPException(status_code=404, detail="Merged PDF not found")
    return safe_file_response(dr.merged_receipt_path, filename=f"requisite_{requisite_id}.pdf")


@router.get("/receipts/{receipt_type}/{receipt_id}/download")
async def download_trader_receipt(
    receipt_type: str,
    receipt_id: int,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    receipt_path = None
    if receipt_type == "zaliv":
        result = await db.execute(
            select(Zaliv)
            .join(Requisite, Requisite.id == Zaliv.requisite_id)
            .where(Zaliv.id == receipt_id, Requisite.trader_id == user.id)
        )
        zaliv = result.scalar_one_or_none()
        receipt_path = zaliv.receipt_path if zaliv else None
    elif receipt_type == "doliv":
        result = await db.execute(
            select(Doliv)
            .join(DolivRequest, DolivRequest.id == Doliv.request_id)
            .join(Requisite, Requisite.id == DolivRequest.requisite_id)
            .where(Doliv.id == receipt_id, Requisite.trader_id == user.id)
        )
        doliv = result.scalar_one_or_none()
        receipt_path = doliv.receipt_path if doliv else None
    else:
        raise HTTPException(status_code=400, detail="Unknown receipt type")

    if not receipt_path:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return safe_file_response(receipt_path)


@router.post("/requisites/{requisite_id}/archive")
async def archive_requisite(
    requisite_id: int,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.services.requisite_deactivate import deactivate_requisite, get_requisite_for_deactivate

    requisite = await get_requisite_for_deactivate(db, requisite_id, trader_id=user.id)
    if requisite.status != RequisiteStatus.closed:
        raise HTTPException(status_code=400, detail="Only closed requisites can be archived")
    await deactivate_requisite(db, requisite, user)
    return {"message": "Archived"}


@router.post("/requisites/{requisite_id}/deactivate")
async def deactivate_requisite_endpoint(
    requisite_id: int,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.services.requisite_deactivate import deactivate_requisite, get_requisite_for_deactivate

    requisite = await get_requisite_for_deactivate(db, requisite_id, trader_id=user.id)
    await deactivate_requisite(db, requisite, user)
    return {"message": "Deactivated"}


@router.get("/stats")
async def trader_stats(
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await get_trader_stats(db, user.id)


@router.get("/settings")
async def trader_settings(
    _user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Returns trader-relevant settings (fixed profit percent, currency)."""
    settings = await db.get(AppSettingsModel, 1)
    profit_percent = await resolve_trader_profit_percent(db, _user)
    return {
        "profit_percent": str(profit_percent),
        "currency": settings.currency if settings else "RUB",
        "display_currency": _user.display_currency or "RUB",
    }
