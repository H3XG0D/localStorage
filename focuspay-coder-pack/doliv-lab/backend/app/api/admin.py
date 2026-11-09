from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import hash_password, bump_token_version, require_role
from app.core.database import get_db
from app.models import (
    AppSettings,
    DealResult,
    Doliv,
    DolivRequest,
    DolivRequestStatus,
    FakeCheck,
    FakeCheckAuditLog,
    Requisite,
    RequisiteStatus,
    RolePermission,
    User,
    UserRole,
    Zaliv,
)
from app.schemas import (
    AdminDolivResponse,
    AppSettingsResponse,
    AppSettingsUpdate,
    DealResultResponse,
    DolivRequestAssign,
    DolivRequestResponse,
    FakeCheckAuditLogResponse,
    FakeCheckResponse,
    ReceiptResponse,
    RequisiteDetail,
    RequisiteResponse,
    RolePermissionsUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.services.stats import (
    _turnover_usdt_sum,
    export_stats_excel,
    get_all_dolivshchik_stats,
    get_all_trader_stats,
    get_overview_stats,
)
from app.services.fake_checks import log_fake_check_action
from app.services.notifications import notify_roles, notify_user
from app.services.files import safe_file_response, save_receipt, safe_remove_receipt
from app.services.profit import calc_fake_check_loss
from app.services.trader_profit import apply_trader_profit_percent
from app.services.teamlead_pool import assert_trader_percent_within_pool
from app.services.doliv_salary import resolve_doliv_salary_usdt
from app.services import token_ledger
from app.api.stats_handlers import (
    build_dashboard_stats,
    build_employee_stats,
    build_stats_analytics,
    parse_period_bound,
)
from app.api.trader import _get_requisite_detail

router = APIRouter(prefix="/admin", tags=["admin"])


def _money(value) -> Decimal:
    return value or Decimal("0")


def _settings_response(settings: AppSettings) -> AppSettingsResponse:
    return AppSettingsResponse(
        currency=settings.currency,
        timezone=settings.timezone,
        default_profit_percent=settings.default_profit_percent,
        trader_salary_percent=settings.trader_salary_percent,
        doliv_salary_percent=settings.doliv_salary_percent,
        payout_bonus_percent=getattr(settings, "payout_bonus_percent", None) or Decimal("1"),
        default_teamlead_percent=getattr(settings, "default_teamlead_percent", None) or Decimal("12"),
        withdraw_fee_usdt=getattr(settings, "withdraw_fee_usdt", None) or Decimal("3"),
        date_format=settings.date_format,
        receipt_formats=[item for item in settings.receipt_formats.split(",") if item],
        max_upload_mb=settings.max_upload_mb,
    )


DEFAULT_ROLE_PERMISSIONS: dict[UserRole, dict[str, list[str]]] = {
    UserRole.owner: {
        "Администраторы": ["view", "create", "edit"],
        "Статистика": ["view", "export"],
        "Пользователи": [],
        "Настройки": [],
    },
    UserRole.admin: {
        "Реквизиты": ["view", "create", "edit", "delete"],
        "Заявки": ["view", "create", "edit", "delete"],
        "Доливы": ["view", "create", "edit", "delete"],
        "Чеки": ["view", "create", "edit", "delete"],
        "Статистика": ["view", "export"],
        "Пользователи": ["view", "create", "edit", "delete"],
        "Настройки": ["view", "edit"],
    },
    UserRole.trader: {
        "Реквизиты": ["view", "create", "edit"],
        "Заявки": ["view", "create"],
        "Доливы": ["view"],
        "Чеки": ["view", "create"],
        "Статистика": ["view"],
        "Депозит": ["view"],
        "Пользователи": [],
        "Настройки": [],
    },
    UserRole.teamlead: {
        "Команда": ["view", "edit"],
        "Реквизиты": ["view"],
        "Депозит": ["view"],
        "Статистика": ["view"],
        "Пользователи": [],
        "Настройки": [],
    },
    UserRole.dolivshchik: {
        "Реквизиты": ["view"],
        "Заявки": ["view", "edit"],
        "Доливы": ["view", "create"],
        "Чеки": ["view", "create"],
        "Статистика": ["view"],
        "Пользователи": [],
        "Настройки": [],
    },
}


def _resolve_fake_check_amounts(
    rate: Decimal,
    amount_rub: Decimal | None,
    amount_usdt: Decimal | None,
) -> tuple[Decimal, Decimal]:
    if amount_rub is None and amount_usdt is None:
        raise HTTPException(status_code=400, detail="Either amount_rub or amount_usdt must be provided")
    if amount_rub is not None and amount_usdt is None:
        amount_usdt = (amount_rub / rate).quantize(Decimal("0.01"))
    elif amount_usdt is not None and amount_rub is None:
        amount_rub = (amount_usdt * rate).quantize(Decimal("0.01"))
    else:
        expected_usdt = (amount_rub / rate).quantize(Decimal("0.01"))
        if abs(amount_usdt - expected_usdt) > Decimal("0.02"):
            raise HTTPException(
                status_code=400,
                detail="amount_rub and amount_usdt are inconsistent with the given rate",
            )
    return amount_rub, amount_usdt


async def _ensure_role_permissions(db: AsyncSession) -> None:
    existing = {
        (row.role, row.section)
        for row in (await db.execute(select(RolePermission))).scalars().all()
    }
    for role, sections in DEFAULT_ROLE_PERMISSIONS.items():
        for section, actions in sections.items():
            if (role, section) in existing:
                continue
            db.add(RolePermission(role=role, section=section, actions=",".join(actions)))
    await db.flush()


async def _get_or_create_settings(db: AsyncSession) -> AppSettings:
    settings = await db.get(AppSettings, 1)
    if settings:
        return settings
    settings = AppSettings(id=1)
    db.add(settings)
    await db.flush()
    await db.refresh(settings)
    return settings


async def _enrich_admin_doliv_request(db: AsyncSession, dr: DolivRequest) -> DolivRequestResponse:
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
    )


@router.get("/requisites", response_model=list[RequisiteResponse])
async def list_all_requisites(
    user: Annotated[User, Depends(require_role(UserRole.admin, UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: RequisiteStatus | None = None,
    trader_id: int | None = None,
    search: str | None = Query(None, description="Search by ID, name/mask, or trader name"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    q = (
        select(Requisite)
        .join(User, User.id == Requisite.trader_id)
        .order_by(Requisite.created_at.desc())
    )
    if user.role == UserRole.teamlead:
        q = q.where(User.teamlead_id == user.id)
    if status:
        q = q.where(Requisite.status == status)
    if trader_id:
        if user.role == UserRole.teamlead:
            trader = await db.get(User, trader_id)
            if not trader or trader.teamlead_id != user.id:
                raise HTTPException(403, "No access to this trader")
        q = q.where(Requisite.trader_id == trader_id)
    if search:
        search_stripped = search.strip()
        # Try numeric match for ID
        id_filter = None
        try:
            search_id = int(search_stripped)
            id_filter = Requisite.id == search_id
        except ValueError:
            pass
        text_filter = or_(
            Requisite.name.ilike(f"%{search_stripped}%"),
            User.full_name.ilike(f"%{search_stripped}%"),
        )
        q = q.where(or_(id_filter, text_filter) if id_filter is not None else text_filter)
    if date_from:
        dt_from = parse_period_bound(date_from)
        if dt_from:
            q = q.where(Requisite.created_at >= dt_from)
    if date_to:
        dt_to = parse_period_bound(date_to, end_of_day=True)
        if dt_to:
            q = q.where(Requisite.created_at <= dt_to)
    result = await db.execute(q)
    rows = list(result.scalars().all())
    trader_ids = {r.trader_id for r in rows}
    names: dict[int, str] = {}
    if trader_ids:
        users = (await db.execute(select(User).where(User.id.in_(trader_ids)))).scalars().all()
        names = {u.id: u.full_name for u in users}
    out = []
    for r in rows:
        item = RequisiteResponse.model_validate(r)
        item.trader_name = names.get(r.trader_id)
        out.append(item)
    return out


@router.get("/requisites/{requisite_id}", response_model=RequisiteDetail)
async def get_requisite_admin(
    requisite_id: int,
    user: Annotated[User, Depends(require_role(UserRole.admin, UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Requisite)
        .options(
            selectinload(Requisite.zalivs),
            selectinload(Requisite.fake_checks).selectinload(FakeCheck.created_by),
        )
        .where(Requisite.id == requisite_id)
    )
    requisite = result.scalar_one_or_none()
    if not requisite:
        raise HTTPException(status_code=404, detail="Requisite not found")
    trader = await db.get(User, requisite.trader_id)
    if user.role == UserRole.teamlead:
        if not trader or trader.teamlead_id != user.id:
            raise HTTPException(status_code=403, detail="No access to this trader")
    detail = await _get_requisite_detail(db, requisite)
    detail.trader_name = trader.full_name if trader else None

    fake_checks = sorted(requisite.fake_checks, key=lambda fc: fc.created_at, reverse=True)
    detail.fake_checks = [
        FakeCheckResponse(
            id=fc.id,
            requisite_id=fc.requisite_id,
            amount_rub=fc.amount_rub,
            rate=fc.rate,
            amount_usdt=fc.amount_usdt,
            comment=fc.comment,
            file_path=Path(fc.file_path).name if fc.file_path else None,
            operation_date=fc.operation_date,
            created_by_id=fc.created_by_id,
            created_by_name=fc.created_by.full_name if fc.created_by else None,
            created_at=fc.created_at,
        )
        for fc in fake_checks
    ]

    fc_loss = calc_fake_check_loss(requisite.fake_checks)
    detail.fake_check_loss = fc_loss
    detail.gross_profit = detail.current_profit
    detail.doliv_loss = Decimal("0")
    detail.net_profit = (detail.current_profit - fc_loss).quantize(Decimal("0.01"))

    dr_result = await db.execute(select(DealResult).where(DealResult.requisite_id == requisite_id))
    dr = dr_result.scalar_one_or_none()
    if dr:
        doliv_loss = abs(min(dr.doliv_profit_loss, Decimal("0")))
        detail.doliv_loss = doliv_loss
        detail.gross_profit = dr.zaliv_profit
        detail.net_profit = (dr.zaliv_profit + dr.doliv_profit_loss - fc_loss).quantize(Decimal("0.01"))

    return detail


@router.get("/requisites/{requisite_id}/deal-result", response_model=DealResultResponse | None)
async def get_deal_result(
    requisite_id: int,
    user: Annotated[User, Depends(require_role(UserRole.admin, UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if user.role == UserRole.teamlead:
        req = await db.get(Requisite, requisite_id)
        if not req:
            raise HTTPException(404, "Requisite not found")
        trader = await db.get(User, req.trader_id)
        if not trader or trader.teamlead_id != user.id:
            raise HTTPException(403, "No access to this trader")
    result = await db.execute(select(DealResult).where(DealResult.requisite_id == requisite_id))
    dr = result.scalar_one_or_none()
    return dr


@router.post("/requisites/{requisite_id}/deactivate")
async def admin_deactivate_requisite(
    requisite_id: int,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.services.requisite_deactivate import deactivate_requisite, get_requisite_for_deactivate

    requisite = await get_requisite_for_deactivate(db, requisite_id)
    await deactivate_requisite(db, requisite, user)
    return {"message": "Deactivated"}


@router.get("/requisites/{requisite_id}/receipts.pdf")
async def download_merged_pdf(
    requisite_id: int,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(DealResult).where(DealResult.requisite_id == requisite_id))
    dr = result.scalar_one_or_none()
    if not dr or not dr.merged_receipt_path:
        raise HTTPException(status_code=404, detail="Merged PDF not found")
    return safe_file_response(dr.merged_receipt_path, filename=f"requisite_{requisite_id}.pdf")


@router.post("/requisites/{requisite_id}/fake-checks", response_model=FakeCheckResponse, status_code=201)
async def add_fake_check(
    requisite_id: int,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
    rate: Annotated[Decimal, Form()],
    operation_date: Annotated[str, Form()],
    amount_rub: Annotated[Decimal | None, Form()] = None,
    amount_usdt: Annotated[Decimal | None, Form()] = None,
    comment: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
):
    requisite = await db.get(Requisite, requisite_id)
    if not requisite:
        raise HTTPException(status_code=404, detail="Requisite not found")
    _ensure_fake_check_editable(requisite)
    if rate <= 0:
        raise HTTPException(status_code=400, detail="Rate must be positive")
    amount_rub, amount_usdt = _resolve_fake_check_amounts(rate, amount_rub, amount_usdt)

    try:
        op_date = date_type.fromisoformat(operation_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid operation_date format (use YYYY-MM-DD)")

    file_path = None
    if file and file.filename:
        app_cfg = await db.get(AppSettings, 1)
        file_path = await save_receipt(
            requisite_id,
            file,
            max_size_bytes=(app_cfg.max_upload_mb * 1024 * 1024) if app_cfg else None,
            allowed_formats=([f.strip() for f in app_cfg.receipt_formats.split(",") if f.strip()] if app_cfg else None),
        )

    fc = FakeCheck(
        requisite_id=requisite_id,
        amount_rub=amount_rub,
        rate=rate,
        amount_usdt=amount_usdt,
        comment=comment,
        file_path=file_path,
        operation_date=op_date,
        created_by_id=user.id,
    )
    db.add(fc)
    await db.flush()
    await db.refresh(fc)

    total_fc_loss_raw = (
        await db.execute(
            select(func.coalesce(func.sum(FakeCheck.amount_usdt), 0)).where(
                FakeCheck.requisite_id == requisite_id
            )
        )
    ).scalar()
    total_fc_loss = Decimal(str(total_fc_loss_raw or 0))

    await notify_roles(
        db,
        [UserRole.admin],
        "Фейк-чек добавлен",
        f"Фейк-чек добавлен. Потеря по реквизиту составила -{amount_usdt} USDT.",
        kind="fake_check",
        link=f"/admin/requisites/{requisite_id}",
        exclude_user_ids={user.id},
    )

    await log_fake_check_action(
        db,
        "created",
        requisite_id=requisite_id,
        user=user,
        fake_check_id=fc.id,
        amount_rub=fc.amount_rub,
        rate=fc.rate,
        amount_usdt=fc.amount_usdt,
        comment=fc.comment,
        file_path=fc.file_path,
    )

    dr_result = await db.execute(select(DealResult).where(DealResult.requisite_id == requisite_id))
    dr = dr_result.scalar_one_or_none()
    if dr:
        net_before = dr.final_profit - (total_fc_loss - amount_usdt)
        net_after = dr.final_profit - total_fc_loss
        if net_before >= 0 and net_after < 0:
            await notify_roles(
                db,
                [UserRole.admin],
                "Внимание: реквизит стал убыточным",
                f"Реквизит «{requisite.name}» стал убыточным после добавления фейк-чека",
                kind="warning",
                link=f"/admin/requisites/{requisite_id}",
            )

    return FakeCheckResponse(
        id=fc.id,
        requisite_id=fc.requisite_id,
        amount_rub=fc.amount_rub,
        rate=fc.rate,
        amount_usdt=fc.amount_usdt,
        comment=fc.comment,
        file_path=Path(fc.file_path).name if fc.file_path else None,
        operation_date=fc.operation_date,
        created_by_id=fc.created_by_id,
        created_by_name=user.full_name,
        created_at=fc.created_at,
    )


def _ensure_fake_check_editable(requisite: Requisite) -> None:
    if requisite.status in (RequisiteStatus.closed, RequisiteStatus.archive):
        raise HTTPException(
            status_code=400,
            detail="Cannot modify fake checks on closed or archived requisites",
        )


@router.put("/fake-checks/{fc_id}", response_model=FakeCheckResponse)
async def update_fake_check(
    fc_id: int,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
    rate: Annotated[Decimal, Form()],
    operation_date: Annotated[str, Form()],
    amount_rub: Annotated[Decimal | None, Form()] = None,
    amount_usdt: Annotated[Decimal | None, Form()] = None,
    comment: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
):
    fc = await db.get(FakeCheck, fc_id)
    if not fc:
        raise HTTPException(status_code=404, detail="Fake check not found")
    requisite = await db.get(Requisite, fc.requisite_id)
    if not requisite:
        raise HTTPException(status_code=404, detail="Requisite not found")
    _ensure_fake_check_editable(requisite)
    if rate <= 0:
        raise HTTPException(status_code=400, detail="Rate must be positive")
    amount_rub, amount_usdt = _resolve_fake_check_amounts(rate, amount_rub, amount_usdt)

    try:
        op_date = date_type.fromisoformat(operation_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid operation_date format (use YYYY-MM-DD)")

    if file and file.filename:
        app_cfg = await db.get(AppSettings, 1)
        if fc.file_path:
            safe_remove_receipt(fc.file_path)
        fc.file_path = await save_receipt(
            fc.requisite_id,
            file,
            max_size_bytes=(app_cfg.max_upload_mb * 1024 * 1024) if app_cfg else None,
            allowed_formats=([f.strip() for f in app_cfg.receipt_formats.split(",") if f.strip()] if app_cfg else None),
        )

    fc.amount_rub = amount_rub
    fc.rate = rate
    fc.amount_usdt = amount_usdt
    fc.comment = comment
    fc.operation_date = op_date
    await db.flush()
    await db.refresh(fc)

    await log_fake_check_action(
        db,
        "updated",
        requisite_id=fc.requisite_id,
        user=user,
        fake_check_id=fc.id,
        amount_rub=fc.amount_rub,
        rate=fc.rate,
        amount_usdt=fc.amount_usdt,
        comment=fc.comment,
        file_path=fc.file_path,
    )

    creator = await db.get(User, fc.created_by_id)
    return FakeCheckResponse(
        id=fc.id,
        requisite_id=fc.requisite_id,
        amount_rub=fc.amount_rub,
        rate=fc.rate,
        amount_usdt=fc.amount_usdt,
        comment=fc.comment,
        file_path=Path(fc.file_path).name if fc.file_path else None,
        operation_date=fc.operation_date,
        created_by_id=fc.created_by_id,
        created_by_name=creator.full_name if creator else None,
        created_at=fc.created_at,
    )


@router.delete("/fake-checks/{fc_id}", status_code=204)
async def delete_fake_check(
    fc_id: int,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    fc = await db.get(FakeCheck, fc_id)
    if not fc:
        raise HTTPException(status_code=404, detail="Fake check not found")
    requisite = await db.get(Requisite, fc.requisite_id)
    if requisite:
        _ensure_fake_check_editable(requisite)

    await log_fake_check_action(
        db,
        "deleted",
        requisite_id=fc.requisite_id,
        user=user,
        fake_check_id=fc.id,
        amount_rub=fc.amount_rub,
        rate=fc.rate,
        amount_usdt=fc.amount_usdt,
        comment=fc.comment,
        file_path=fc.file_path,
    )

    if fc.file_path:
        safe_remove_receipt(fc.file_path)
    await db.delete(fc)


@router.get("/fake-checks/{fc_id}/file")
async def get_fake_check_file(
    fc_id: int,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    fc = await db.get(FakeCheck, fc_id)
    if not fc or not fc.file_path:
        raise HTTPException(status_code=404, detail="File not found")
    return safe_file_response(fc.file_path)


@router.get("/requisites/{requisite_id}/fake-check-history", response_model=list[FakeCheckAuditLogResponse])
async def get_fake_check_history(
    requisite_id: int,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    requisite = await db.get(Requisite, requisite_id)
    if not requisite:
        raise HTTPException(status_code=404, detail="Requisite not found")
    result = await db.execute(
        select(FakeCheckAuditLog)
        .options(selectinload(FakeCheckAuditLog.user))
        .where(FakeCheckAuditLog.requisite_id == requisite_id)
        .order_by(FakeCheckAuditLog.created_at.desc())
    )
    logs = result.scalars().all()
    return [
        FakeCheckAuditLogResponse(
            id=log.id,
            action=log.action,
            requisite_id=log.requisite_id,
            fake_check_id=log.fake_check_id,
            amount_rub=log.amount_rub,
            rate=log.rate,
            amount_usdt=log.amount_usdt,
            comment=log.comment,
            file_path=Path(log.file_path).name if log.file_path else None,
            user_id=log.user_id,
            user_name=log.user.full_name if log.user else None,
            created_at=log.created_at,
        )
        for log in logs
    ]


@router.get("/doliv-requests", response_model=list[DolivRequestResponse])
async def list_admin_doliv_requests(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: DolivRequestStatus | None = Query(None, alias="status"),
):
    query = (
        select(DolivRequest)
        .options(selectinload(DolivRequest.requisite))
        .order_by(DolivRequest.sent_at.desc())
    )
    if status_filter:
        query = query.where(DolivRequest.status == status_filter)
    result = await db.execute(query)
    return [await _enrich_admin_doliv_request(db, request) for request in result.scalars().all()]


@router.post("/doliv-requests/{request_id}/assign", response_model=DolivRequestResponse)
async def assign_doliv_request(
    request_id: int,
    data: DolivRequestAssign,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    request = (
        await db.execute(
            select(DolivRequest).where(DolivRequest.id == request_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.status in (DolivRequestStatus.completed, DolivRequestStatus.cancelled):
        raise HTTPException(status_code=400, detail="Cannot assign completed or cancelled request")
    if request.status == DolivRequestStatus.in_progress:
        raise HTTPException(
            status_code=400,
            detail="Cannot reassign request already in progress; cancel it first",
        )

    dolivshchik = await db.get(User, data.dolivshchik_id)
    if not dolivshchik or dolivshchik.role != UserRole.dolivshchik or not dolivshchik.is_active:
        raise HTTPException(status_code=400, detail="Dolivshchik not found or inactive")

    request.assigned_dolivshchik_id = dolivshchik.id
    request.status = DolivRequestStatus.in_progress
    requisite = await db.get(Requisite, request.requisite_id)
    if requisite and requisite.status not in (RequisiteStatus.closed, RequisiteStatus.archive):
        requisite.status = RequisiteStatus.doliv_in_progress
        await notify_user(
            db,
            dolivshchik.id,
            "Вам назначили долив",
            f"Админ назначил вам заявку #{request.id} по реквизиту {requisite.name}",
            kind="doliv_assigned",
            link="/doliv",
        )
        await notify_user(
            db,
            requisite.trader_id,
            "Доливщик назначен",
            f"На заявку #{request.id} назначен {dolivshchik.full_name}",
            kind="doliv_assigned",
            link=f"/trader/requisites/{requisite.id}",
        )

    await db.flush()
    return await _enrich_admin_doliv_request(db, request)


@router.post("/doliv-requests/{request_id}/cancel", response_model=DolivRequestResponse)
async def cancel_doliv_request(
    request_id: int,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(DolivRequest)
        .options(selectinload(DolivRequest.requisite).selectinload(Requisite.zalivs))
        .where(DolivRequest.id == request_id)
        .with_for_update()
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.status == DolivRequestStatus.completed:
        raise HTTPException(status_code=400, detail="Completed request cannot be cancelled")
    if request.status == DolivRequestStatus.cancelled:
        return await _enrich_admin_doliv_request(db, request)

    request.status = DolivRequestStatus.cancelled
    request.assigned_dolivshchik_id = None
    requisite = request.requisite
    if requisite and requisite.status not in (RequisiteStatus.closed, RequisiteStatus.archive):
        requisite.status = RequisiteStatus.in_work if requisite.zalivs else RequisiteStatus.active
        await notify_user(
            db,
            requisite.trader_id,
            "Заявка на долив отменена",
            f"Админ отменил заявку #{request.id} по реквизиту {requisite.name}",
            kind="doliv_cancelled",
            link=f"/trader/requisites/{requisite.id}",
        )
        await notify_roles(
            db,
            [UserRole.admin],
            "Заявка отменена",
            f"{user.full_name} отменил заявку #{request.id} по реквизиту {requisite.name}",
            kind="doliv_cancelled",
            link=f"/admin/requisites/{requisite.id}",
            exclude_user_ids={user.id},
        )

    await db.flush()
    return await _enrich_admin_doliv_request(db, request)


@router.get("/dolivs", response_model=list[AdminDolivResponse])
async def list_dolivs(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Doliv)
        .options(
            selectinload(Doliv.dolivshchik),
            selectinload(Doliv.request)
            .selectinload(DolivRequest.requisite)
            .selectinload(Requisite.trader),
        )
        .order_by(Doliv.completed_at.desc())
    )
    rows = []
    for doliv in result.scalars().all():
        request = doliv.request
        requisite = request.requisite
        trader = requisite.trader
        rows.append(
            AdminDolivResponse(
                id=doliv.id,
                request_id=request.id,
                requisite_id=requisite.id,
                requisite_name=requisite.name,
                trader_name=trader.full_name,
                dolivshchik_name=doliv.dolivshchik.full_name,
                amount=doliv.amount,
                rate=doliv.rate,
                receipt_path=doliv.receipt_path,
                status=request.status,
                completed_at=doliv.completed_at,
            )
        )
    return rows


@router.get("/receipts", response_model=list[ReceiptResponse])
async def list_receipts(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    zaliv_result = await db.execute(
        select(Zaliv)
        .options(selectinload(Zaliv.requisite).selectinload(Requisite.trader))
        .order_by(Zaliv.created_at.desc())
    )
    doliv_result = await db.execute(
        select(Doliv)
        .options(
            selectinload(Doliv.dolivshchik),
            selectinload(Doliv.request).selectinload(DolivRequest.requisite),
        )
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
                uploader_name=zaliv.requisite.trader.login,
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
                uploader_name=doliv.dolivshchik.login,
                amount=doliv.amount,
                rate=doliv.rate,
                receipt_path=doliv.receipt_path,
                created_at=doliv.completed_at,
            )
        )

    return sorted(receipts, key=lambda r: r.created_at, reverse=True)


@router.get("/receipts/{receipt_type}/{receipt_id}/download")
async def download_receipt(
    receipt_type: str,
    receipt_id: int,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    receipt_path = None
    if receipt_type == "zaliv":
        zaliv = await db.get(Zaliv, receipt_id)
        receipt_path = zaliv.receipt_path if zaliv else None
    elif receipt_type == "doliv":
        doliv = await db.get(Doliv, receipt_id)
        receipt_path = doliv.receipt_path if doliv else None
    else:
        raise HTTPException(status_code=400, detail="Unknown receipt type")

    if not receipt_path:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return safe_file_response(receipt_path)


@router.get("/stats/dashboard")
async def dashboard_stats(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    return await build_dashboard_stats(db, start, end)


@router.get("/activity")
async def activity_feed(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 20,
):
    events = []

    requisites = (
        await db.execute(
            select(Requisite)
            .options(selectinload(Requisite.trader))
            .order_by(Requisite.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    for req in requisites:
        events.append(
            {
                "id": f"req-{req.id}",
                "type": "requisite",
                "text": f"{req.trader.full_name} создал реквизит {req.name}",
                "created_at": req.created_at,
                "requisite_id": req.id,
            }
        )

    zalivs = (
        await db.execute(
            select(Zaliv)
            .options(selectinload(Zaliv.requisite).selectinload(Requisite.trader))
            .order_by(Zaliv.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    for zaliv in zalivs:
        events.append(
            {
                "id": f"zaliv-{zaliv.id}",
                "type": "zaliv",
                "text": f"{zaliv.requisite.trader.full_name} добавил залив {zaliv.amount} ₽",
                "created_at": zaliv.created_at,
                "requisite_id": zaliv.requisite_id,
            }
        )

    dolivs = (
        await db.execute(
            select(Doliv)
            .options(
                selectinload(Doliv.dolivshchik),
                selectinload(Doliv.request).selectinload(DolivRequest.requisite),
            )
            .order_by(Doliv.completed_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    for doliv in dolivs:
        events.append(
            {
                "id": f"doliv-{doliv.id}",
                "type": "doliv",
                "text": f"{doliv.dolivshchik.full_name} выполнил долив {doliv.amount} ₽",
                "created_at": doliv.completed_at,
                "requisite_id": doliv.request.requisite_id,
            }
        )

    return sorted(events, key=lambda e: e["created_at"], reverse=True)[:limit]


@router.get("/employees")
async def employee_stats(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await build_employee_stats(db)


async def _compute_salary_rows(
    db: AsyncSession,
    start_dt: datetime | None,
    end_dt: datetime | None,
    cfg: AppSettings,
) -> list[dict]:
    """Pure salary computation used by both /salaries and /statements endpoints."""
    rows: list[dict] = []
    traders = (
        await db.execute(select(User).where(User.role == UserRole.trader, User.is_active == True))
    ).scalars().all()
    for trader in traders:
        query = (
            select(
                func.count(Requisite.id),
                func.coalesce(func.sum(DealResult.total_turnover), 0),
                _turnover_usdt_sum(),
                func.coalesce(func.sum(DealResult.final_profit), 0),
            )
            .select_from(Requisite)
            .join(DealResult, DealResult.requisite_id == Requisite.id)
            .where(
                Requisite.trader_id == trader.id,
                Requisite.status.in_((RequisiteStatus.closed, RequisiteStatus.archive)),
            )
        )
        if start_dt:
            query = query.where(DealResult.calculated_at >= start_dt)
        if end_dt:
            query = query.where(DealResult.calculated_at <= end_dt)
        count, turnover, turnover_usdt, profit = (await db.execute(query)).one()
        profit_base = max(Decimal("0"), profit or Decimal("0"))
        salary = (profit_base * cfg.trader_salary_percent / Decimal("100")).quantize(Decimal("0.01"))
        rows.append(
            {
                "user_id": trader.id,
                "login": trader.login,
                "full_name": trader.full_name,
                "role": UserRole.trader,
                "method": f"{cfg.trader_salary_percent}% от прибыли",
                "turnover": turnover or Decimal("0"),
                "turnover_usdt": Decimal(str(turnover_usdt or 0)).quantize(Decimal("0.01")),
                "profit": profit or Decimal("0"),
                "salary": salary,
            }
        )
    dolivshchiks = (
        await db.execute(select(User).where(User.role == UserRole.dolivshchik, User.is_active == True))
    ).scalars().all()
    for dolivshchik in dolivshchiks:
        # Doliv volume is in RUB; salary is computed in USDT by converting each
        # doliv via its requisite rate, then applying the percentage.
        query = (
            select(
                func.count(Doliv.id),
                func.coalesce(func.sum(Doliv.amount), 0),
                func.coalesce(func.sum(Doliv.amount / Requisite.target_rate), 0),
            )
            .select_from(Doliv)
            .join(DolivRequest, DolivRequest.id == Doliv.request_id)
            .join(Requisite, Requisite.id == DolivRequest.requisite_id)
            .where(Doliv.dolivshchik_id == dolivshchik.id)
        )
        if start_dt:
            query = query.where(Doliv.completed_at >= start_dt)
        if end_dt:
            query = query.where(Doliv.completed_at <= end_dt)
        count, total_amount, total_usdt = (await db.execute(query)).one()
        rate = await resolve_doliv_salary_usdt(db, dolivshchik)
        salary = (Decimal(str(count)) * rate).quantize(Decimal("0.01"))
        rows.append(
            {
                "user_id": dolivshchik.id,
                "login": dolivshchik.login,
                "full_name": dolivshchik.full_name,
                "role": UserRole.dolivshchik,
                "method": f"{rate} USDT/долив",
                "turnover": total_amount or Decimal("0"),
                "turnover_usdt": Decimal(str(total_usdt or 0)).quantize(Decimal("0.01")),
                "profit": Decimal("0"),
                "salary": salary,
            }
        )
    return rows


@router.get("/salaries")
async def salaries(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    cfg = await _get_or_create_settings(db)
    start_dt = parse_period_bound(start)
    end_dt = parse_period_bound(end, end_of_day=True)
    return await _compute_salary_rows(db, start_dt, end_dt, cfg)


@router.get("/statements")
async def statements(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    start_dt = parse_period_bound(start)
    end_dt = parse_period_bound(end, end_of_day=True)
    overview_query = select(
        func.coalesce(func.sum(DealResult.total_turnover), 0),
        _turnover_usdt_sum(),
        func.coalesce(func.sum(DealResult.final_profit), 0),
    )
    if start_dt:
        overview_query = overview_query.where(DealResult.calculated_at >= start_dt)
    if end_dt:
        overview_query = overview_query.where(DealResult.calculated_at <= end_dt)
    total_turnover, total_turnover_usdt, total_profit = (await db.execute(overview_query)).one()
    total_turnover_usdt = Decimal(str(total_turnover_usdt or 0)).quantize(Decimal("0.01"))

    fc_query = (
        select(func.coalesce(func.sum(FakeCheck.amount_usdt), 0))
        .select_from(FakeCheck)
        .join(DealResult, DealResult.requisite_id == FakeCheck.requisite_id)
    )
    if start_dt:
        fc_query = fc_query.where(DealResult.calculated_at >= start_dt)
    if end_dt:
        fc_query = fc_query.where(DealResult.calculated_at <= end_dt)
    fc_loss = Decimal(str((await db.execute(fc_query)).scalar() or 0)).quantize(Decimal("0.01"))

    cfg = await _get_or_create_settings(db)
    salary_rows = await _compute_salary_rows(db, start_dt, end_dt, cfg)
    salaries_total = sum((row["salary"] for row in salary_rows), Decimal("0"))
    expenses = Decimal("0")
    net_profit = total_profit - salaries_total - expenses - fc_loss
    return {
        "cards": [
            {"label": "Оборот", "value": total_turnover_usdt},
            {"label": "Прибыль", "value": total_profit},
            {"label": "Зарплаты", "value": salaries_total},
            {"label": "Чистая прибыль", "value": net_profit},
        ],
        "items": [
            {"item": "Оборот за период", "amount": total_turnover_usdt, "kind": "income"},
            {"item": "Итоговая прибыль", "amount": total_profit, "kind": "income"},
            {"item": "Зарплаты", "amount": salaries_total, "kind": "expense"},
            {"item": "Фейк-чеки", "amount": fc_loss, "kind": "expense"},
            {"item": "Расходы", "amount": expenses, "kind": "expense"},
            {"item": "Чистая прибыль", "amount": net_profit, "kind": "total"},
        ],
    }


@router.get("/roles")
async def roles_matrix(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _ensure_role_permissions(db)
    rows = (await db.execute(select(RolePermission).order_by(RolePermission.section))).scalars().all()
    matrix: dict[UserRole, dict[str, list[str]]] = {role: {} for role in UserRole}
    for row in rows:
        matrix[row.role][row.section] = [action for action in row.actions.split(",") if action]
    return [{"role": role, "permissions": matrix[role]} for role in UserRole]


@router.patch("/roles/{role}")
async def update_role_permissions(
    role: UserRole,
    data: RolePermissionsUpdate,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    raise HTTPException(
        status_code=403,
        detail="Role permission matrix is read-only; permissions are not enforced at the API level",
    )


@router.get("/settings", response_model=AppSettingsResponse)
async def settings(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return _settings_response(await _get_or_create_settings(db))


@router.patch("/settings", response_model=AppSettingsResponse)
async def update_settings(
    data: AppSettingsUpdate,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    settings = await _get_or_create_settings(db)
    if data.currency is not None:
        settings.currency = data.currency.upper()
    if data.timezone is not None:
        settings.timezone = data.timezone
    if data.default_profit_percent is not None:
        settings.default_profit_percent = data.default_profit_percent
    if data.trader_salary_percent is not None:
        settings.trader_salary_percent = data.trader_salary_percent
    if data.doliv_salary_percent is not None:
        settings.doliv_salary_percent = data.doliv_salary_percent
    if data.payout_bonus_percent is not None:
        settings.payout_bonus_percent = data.payout_bonus_percent
    if data.default_teamlead_percent is not None:
        settings.default_teamlead_percent = data.default_teamlead_percent
    if data.withdraw_fee_usdt is not None:
        settings.withdraw_fee_usdt = data.withdraw_fee_usdt
    if data.date_format is not None:
        settings.date_format = data.date_format
    if data.receipt_formats is not None:
        clean_formats = [fmt.strip().upper() for fmt in data.receipt_formats if fmt.strip()]
        if not clean_formats:
            raise HTTPException(status_code=400, detail="At least one receipt format is required")
        settings.receipt_formats = ",".join(clean_formats)
    if data.max_upload_mb is not None:
        settings.max_upload_mb = data.max_upload_mb
    await db.flush()
    await db.refresh(settings)
    return _settings_response(settings)


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(User).where(User.role != UserRole.owner).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if data.role == UserRole.admin:
        raise HTTPException(status_code=403, detail="Cannot create admin users")
    if data.role == UserRole.owner:
        raise HTTPException(status_code=403, detail="Cannot create owner users")
    existing = await db.execute(select(User).where(User.login == data.login))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Login already exists")

    profit_percent = None
    doliv_salary_usdt = None
    teamlead_percent = None
    if data.role == UserRole.trader:
        if data.profit_percent is not None:
            profit_percent = data.profit_percent
        else:
            settings = await db.get(AppSettings, 1)
            profit_percent = (
                settings.default_profit_percent if settings else Decimal("12")
            )
    elif data.role == UserRole.dolivshchik:
        if data.doliv_salary_usdt is not None:
            doliv_salary_usdt = data.doliv_salary_usdt
        else:
            settings = await db.get(AppSettings, 1)
            doliv_salary_usdt = (
                settings.doliv_salary_percent if settings else Decimal("1")
            )
    elif data.role == UserRole.teamlead:
        settings = await db.get(AppSettings, 1)
        teamlead_percent = data.teamlead_percent
        if teamlead_percent is None:
            teamlead_percent = (
                settings.default_teamlead_percent if settings else Decimal("12")
            )

    if data.role == UserRole.trader and profit_percent is not None:
        await assert_trader_percent_within_pool(
            db,
            profit_percent=profit_percent,
            teamlead_id=data.teamlead_id,
        )

    new_user = User(
        login=data.login,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=data.role,
        profit_percent=profit_percent,
        doliv_salary_usdt=doliv_salary_usdt,
        teamlead_percent=teamlead_percent,
        teamlead_id=data.teamlead_id if data.role == UserRole.trader else None,
        deposit_exempt=data.deposit_exempt,
    )
    db.add(new_user)
    await db.flush()
    if data.role == UserRole.trader and not data.deposit_exempt:
        await token_ledger.ensure_personal_token(db, new_user)
    elif data.role == UserRole.teamlead:
        await token_ledger.ensure_personal_token(db, new_user)
    await db.refresh(new_user)
    return new_user


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    data: UserUpdate,
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target.role == UserRole.owner:
        raise HTTPException(status_code=403, detail="Cannot modify owner users")

    # Protect the last active admin from being demoted or deactivated
    if target.role == UserRole.admin:
        new_role = data.role if data.role is not None else target.role
        new_is_active = data.is_active if data.is_active is not None else target.is_active
        if new_role != UserRole.admin or not new_is_active:
            other_admin_count = (
                await db.execute(
                    select(func.count(User.id)).where(
                        User.role == UserRole.admin,
                        User.is_active == True,
                        User.id != target.id,
                    )
                )
            ).scalar() or 0
            if other_admin_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot demote or deactivate the last active admin",
                )

    if data.role is not None and data.role == UserRole.admin and target.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Cannot assign admin role")

    if data.role is not None and data.role == UserRole.owner:
        raise HTTPException(status_code=403, detail="Cannot assign owner role")

    old_profit = target.profit_percent
    old_role = target.role
    old_is_active = target.is_active
    new_role = data.role if data.role is not None else target.role

    if data.full_name is not None:
        target.full_name = data.full_name
    if data.password is not None:
        target.password_hash = hash_password(data.password)
        bump_token_version(target)
    if data.role is not None:
        target.role = data.role
    if data.is_active is not None:
        target.is_active = data.is_active

    if data.role is not None and data.role != old_role:
        bump_token_version(target)
    if data.is_active is not None and data.is_active != old_is_active and not data.is_active:
        bump_token_version(target)

    if new_role == UserRole.trader:
        target.doliv_salary_usdt = None
        if data.profit_percent is not None:
            target.profit_percent = data.profit_percent
        elif target.profit_percent is None:
            settings = await db.get(AppSettings, 1)
            target.profit_percent = (
                settings.default_profit_percent if settings else Decimal("12")
            )
        if data.teamlead_id is not None:
            target.teamlead_id = data.teamlead_id
        if data.deposit_exempt is not None:
            target.deposit_exempt = data.deposit_exempt
        if target.profit_percent is not None:
            await assert_trader_percent_within_pool(
                db,
                profit_percent=Decimal(target.profit_percent),
                teamlead_id=target.teamlead_id,
            )
    elif new_role == UserRole.dolivshchik:
        target.profit_percent = None
        target.teamlead_id = None
        if data.doliv_salary_usdt is not None:
            target.doliv_salary_usdt = data.doliv_salary_usdt
        elif target.doliv_salary_usdt is None:
            settings = await db.get(AppSettings, 1)
            target.doliv_salary_usdt = (
                settings.doliv_salary_percent if settings else Decimal("1")
            )
    elif new_role == UserRole.teamlead:
        target.profit_percent = None
        target.doliv_salary_usdt = None
        target.teamlead_id = None
        if data.teamlead_percent is not None:
            target.teamlead_percent = data.teamlead_percent
        elif target.teamlead_percent is None:
            settings = await db.get(AppSettings, 1)
            target.teamlead_percent = (
                settings.default_teamlead_percent if settings else Decimal("12")
            )
    else:
        target.profit_percent = None
        target.doliv_salary_usdt = None

    if data.deposit_exempt is not None and new_role == UserRole.trader:
        target.deposit_exempt = data.deposit_exempt

    await db.flush()

    if (
        target.role == UserRole.trader
        and data.profit_percent is not None
        and data.profit_percent != old_profit
    ):
        await apply_trader_profit_percent(db, target.id, target.profit_percent)

    await db.refresh(target)
    return target


@router.get("/stats/overview")
async def stats_overview(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    return await get_overview_stats(db, parse_period_bound(start), parse_period_bound(end, end_of_day=True))


@router.get("/stats/analytics")
async def stats_analytics(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
    start: str | None = Query(None),
    end: str | None = Query(None),
    trader_id: int | None = Query(None),
    requisite_id: int | None = Query(None),
    period: str = Query("day", pattern="^(day|week|month)$"),
):
    return await build_stats_analytics(db, start, end, trader_id, requisite_id, period)


@router.get("/stats/traders")
async def stats_traders(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await get_all_trader_stats(db)


@router.get("/stats/dolivshchiks")
async def stats_dolivshchiks(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await get_all_dolivshchik_stats(db)


@router.get("/export/stats.xlsx")
async def export_excel(
    user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    data = await export_stats_excel(db)
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=stats.xlsx"},
    )
