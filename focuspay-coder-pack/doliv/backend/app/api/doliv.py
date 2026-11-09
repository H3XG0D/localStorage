from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import require_role
from app.core.database import get_db
from app.models import (
    DealResult,
    Doliv,
    DolivRequest,
    DolivRequestStatus,
    Requisite,
    RequisiteStatus,
    User,
    UserRole,
)
from app.schemas import DolivRequestResponse, DolivResponse, ReceiptResponse
from app.models import AppSettings as AppSettingsModel
from app.services.files import merge_receipts_to_pdf_async, safe_file_response, save_receipt
from app.services.notifications import notify_roles, notify_user
from app.services.profit import build_deal_result, calc_zaliv_total
from app.services.doliv_salary import resolve_doliv_salary_usdt
from app.services.stats import get_dolivshchik_stats

router = APIRouter(prefix="/doliv", tags=["doliv"])


async def _enrich_request(db: AsyncSession, dr: DolivRequest) -> DolivRequestResponse:
    req_result = await db.execute(
        select(Requisite)
        .options(selectinload(Requisite.zalivs))
        .where(Requisite.id == dr.requisite_id)
    )
    req = req_result.scalar_one_or_none()
    trader = await db.get(User, req.trader_id) if req else None
    assigned = await db.get(User, dr.assigned_dolivshchik_id) if dr.assigned_dolivshchik_id else None
    zaliv_total = calc_zaliv_total(req.zalivs) if req else None
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
        zaliv_total=zaliv_total,
    )


@router.get("/requests", response_model=list[DolivRequestResponse])
async def list_requests(
    user: Annotated[User, Depends(require_role(UserRole.dolivshchik))],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: DolivRequestStatus | None = Query(None, alias="status"),
):
    q = select(DolivRequest).order_by(DolivRequest.sent_at.desc())
    if status_filter:
        q = q.where(DolivRequest.status == status_filter)
        if status_filter != DolivRequestStatus.pending:
            q = q.where(DolivRequest.assigned_dolivshchik_id == user.id)
    else:
        q = q.where(
            or_(
                DolivRequest.status == DolivRequestStatus.pending,
                (
                    (DolivRequest.status == DolivRequestStatus.in_progress)
                    & (DolivRequest.assigned_dolivshchik_id == user.id)
                ),
            )
        )
    result = await db.execute(q)
    requests = result.scalars().all()
    return [await _enrich_request(db, dr) for dr in requests]


@router.post("/requests/{request_id}/take")
async def take_request(
    request_id: int,
    user: Annotated[User, Depends(require_role(UserRole.dolivshchik))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # with_for_update prevents two dolivshchiks from taking the same request simultaneously
    result = await db.execute(
        select(DolivRequest).where(DolivRequest.id == request_id).with_for_update()
    )
    dr = result.scalar_one_or_none()
    if not dr:
        raise HTTPException(status_code=404, detail="Request not found")
    if dr.status != DolivRequestStatus.pending:
        raise HTTPException(status_code=400, detail="Request not available")
    if dr.required_amount <= 0:
        raise HTTPException(status_code=400, detail="Request has no amount to process")

    dr.status = DolivRequestStatus.in_progress
    dr.assigned_dolivshchik_id = user.id

    req = await db.get(Requisite, dr.requisite_id)
    if req:
        req.status = RequisiteStatus.doliv_in_progress
        await notify_user(
            db,
            req.trader_id,
            "Заявка взята в работу",
            f"{user.full_name} взял в работу долив по реквизиту {req.name}",
            kind="doliv_taken",
            link=f"/trader/requisites/{req.id}",
        )
        await notify_roles(
            db,
            [UserRole.admin],
            "Доливщик взял заявку",
            f"{user.full_name} взял заявку #{dr.id} по реквизиту {req.name}",
            kind="doliv_taken",
            link=f"/admin/requisites/{req.id}",
            exclude_user_ids={user.id},
        )
    return {"message": "Request taken"}


@router.post("/requests/{request_id}/complete", response_model=DolivResponse)
async def complete_doliv(
    request_id: int,
    user: Annotated[User, Depends(require_role(UserRole.dolivshchik))],
    db: Annotated[AsyncSession, Depends(get_db)],
    amount: Annotated[Decimal, Form()],
    rate: Annotated[Decimal, Form()],
    receipt: Annotated[UploadFile, File()],
):
    result = await db.execute(
        select(DolivRequest)
        .options(selectinload(DolivRequest.doliv))
        .where(DolivRequest.id == request_id)
        .with_for_update()
    )
    dr = result.scalar_one_or_none()
    if not dr:
        raise HTTPException(status_code=404, detail="Request not found")
    if dr.status != DolivRequestStatus.in_progress:
        raise HTTPException(status_code=400, detail="Request not in progress")
    if dr.assigned_dolivshchik_id != user.id:
        raise HTTPException(status_code=403, detail="Not assigned to you")
    if amount <= 0 or rate <= 0:
        raise HTTPException(status_code=400, detail="Amount and rate must be positive")
    if rate < Decimal("50") or rate > Decimal("200"):
        raise HTTPException(status_code=400, detail="Rate must be between 50 and 200")
    if amount != dr.required_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Doliv amount must equal required amount ({dr.required_amount} ₽)",
        )
    # Prevent double-completion (e.g. two concurrent requests by same user)
    if dr.doliv is not None:
        raise HTTPException(status_code=409, detail="Doliv already completed for this request")

    req_result = await db.execute(
        select(Requisite)
        .options(selectinload(Requisite.zalivs), selectinload(Requisite.deal_result))
        .where(Requisite.id == dr.requisite_id)
    )
    requisite = req_result.scalar_one_or_none()
    if not requisite:
        raise HTTPException(status_code=404, detail="Requisite not found")

    app_cfg = await db.get(AppSettingsModel, 1)
    receipt_path = await save_receipt(
        requisite.id,
        receipt,
        max_size_bytes=(app_cfg.max_upload_mb * 1024 * 1024) if app_cfg else None,
        allowed_formats=([f.strip() for f in app_cfg.receipt_formats.split(",") if f.strip()] if app_cfg else None),
    )
    doliv = Doliv(
        request_id=dr.id,
        dolivshchik_id=user.id,
        amount=amount,
        rate=rate,
        receipt_path=receipt_path,
    )
    db.add(doliv)
    dr.status = DolivRequestStatus.completed
    requisite.status = RequisiteStatus.closed

    merged_path = await merge_receipts_to_pdf_async(requisite, doliv, "")
    deal = build_deal_result(requisite, requisite.zalivs, doliv, merged_path)
    if requisite.deal_result:
        await db.delete(requisite.deal_result)
    db.add(deal)

    await notify_user(
        db,
        requisite.trader_id,
        "Долив выполнен",
        f"{user.full_name} завершил долив по реквизиту {requisite.name}: {amount} ₽",
        kind="doliv_completed",
        link=f"/trader/requisites/{requisite.id}",
    )
    await notify_roles(
        db,
        [UserRole.admin],
        "Долив завершен",
        f"{user.full_name} завершил долив #{dr.id} по реквизиту {requisite.name}",
        kind="doliv_completed",
        link=f"/admin/requisites/{requisite.id}",
        exclude_user_ids={user.id},
    )

    await db.flush()
    await db.refresh(doliv)
    return DolivResponse(
        id=doliv.id,
        amount=doliv.amount,
        rate=doliv.rate,
        receipt_path=doliv.receipt_path,
        completed_at=doliv.completed_at,
        dolivshchik_name=user.full_name,
    )


@router.get("/receipts", response_model=list[ReceiptResponse])
async def list_doliv_receipts(
    user: Annotated[User, Depends(require_role(UserRole.dolivshchik))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Doliv)
        .options(selectinload(Doliv.request).selectinload(DolivRequest.requisite))
        .where(Doliv.dolivshchik_id == user.id)
        .order_by(Doliv.completed_at.desc())
    )
    receipts: list[ReceiptResponse] = []
    for doliv in result.scalars().all():
        requisite = doliv.request.requisite
        receipts.append(
            ReceiptResponse(
                id=doliv.id,
                type="doliv",
                requisite_id=requisite.id,
                requisite_name=requisite.name,
                uploader_name=user.full_name,
                amount=doliv.amount,
                rate=doliv.rate,
                receipt_path=doliv.receipt_path,
                created_at=doliv.completed_at,
            )
        )
    return receipts


@router.get("/receipts/{receipt_id}/download")
async def download_doliv_receipt(
    receipt_id: int,
    user: Annotated[User, Depends(require_role(UserRole.dolivshchik))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Doliv).where(Doliv.id == receipt_id, Doliv.dolivshchik_id == user.id)
    )
    doliv = result.scalar_one_or_none()
    if not doliv:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return safe_file_response(doliv.receipt_path)


@router.get("/settings")
async def doliv_settings(
    user: Annotated[User, Depends(require_role(UserRole.dolivshchik))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Returns dolivshchik-relevant settings (fixed salary rate, currency)."""
    settings = await db.get(AppSettingsModel, 1)
    salary_per_doliv_usdt = await resolve_doliv_salary_usdt(db, user)
    return {
        "salary_per_doliv_usdt": str(salary_per_doliv_usdt),
        "currency": settings.currency if settings else "RUB",
    }


@router.get("/stats")
async def doliv_stats(
    user: Annotated[User, Depends(require_role(UserRole.dolivshchik))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await get_dolivshchik_stats(db, user.id)


@router.get("/history", response_model=list[DolivResponse])
async def doliv_history(
    user: Annotated[User, Depends(require_role(UserRole.dolivshchik))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Doliv).where(Doliv.dolivshchik_id == user.id).order_by(Doliv.completed_at.desc())
    )
    dolivs = result.scalars().all()
    return [
        DolivResponse(
            id=d.id,
            amount=d.amount,
            rate=d.rate,
            receipt_path=d.receipt_path,
            completed_at=d.completed_at,
            dolivshchik_name=user.full_name,
        )
        for d in dolivs
    ]
