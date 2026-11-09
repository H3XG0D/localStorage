from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.stats_handlers import (
    build_dashboard_stats,
    build_employee_stats,
    build_stats_analytics,
    parse_period_bound,
)
from app.core.auth import hash_password, bump_token_version, require_owner
from app.core.database import get_db
from app.models import User, UserRole
from app.schemas import AdminCreate, AdminUpdate, OwnerAdminSummary, OwnerDashboardResponse, UserResponse
from app.services.stats import (
    export_stats_excel,
    get_all_dolivshchik_stats,
    get_all_trader_stats,
    get_overview_stats,
)

router = APIRouter(prefix="/owner", tags=["owner"])


async def _admin_summary(db: AsyncSession) -> OwnerAdminSummary:
    admins = (
        await db.execute(
            select(User).where(User.role == UserRole.admin).order_by(User.created_at.desc())
        )
    ).scalars().all()
    active = sum(1 for a in admins if a.is_active)
    return OwnerAdminSummary(
        total=len(admins),
        active=active,
        inactive=len(admins) - active,
        admins=admins,
    )


@router.get("/dashboard", response_model=OwnerDashboardResponse)
async def owner_dashboard(
    user: Annotated[User, Depends(require_owner())],
    db: Annotated[AsyncSession, Depends(get_db)],
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    stats = await build_dashboard_stats(db, start, end)
    summary = await _admin_summary(db)
    return OwnerDashboardResponse(stats=stats, admin_summary=summary)


@router.get("/admins", response_model=list[UserResponse])
async def list_admins(
    user: Annotated[User, Depends(require_owner())],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(User).where(User.role == UserRole.admin).order_by(User.created_at.desc())
    )
    return result.scalars().all()


@router.post("/admins", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_admin(
    data: AdminCreate,
    user: Annotated[User, Depends(require_owner())],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing = await db.execute(select(User).where(User.login == data.login))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Login already exists")

    new_user = User(
        login=data.login,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=UserRole.admin,
    )
    db.add(new_user)
    await db.flush()
    await db.refresh(new_user)
    return new_user


@router.patch("/admins/{admin_id}", response_model=UserResponse)
async def update_admin(
    admin_id: int,
    data: AdminUpdate,
    user: Annotated[User, Depends(require_owner())],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    target = await db.get(User, admin_id)
    if not target or target.role != UserRole.admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    if data.is_active is not None and not data.is_active:
        other_active = (
            await db.execute(
                select(func.count(User.id)).where(
                    User.role == UserRole.admin,
                    User.is_active == True,
                    User.id != target.id,
                )
            )
        ).scalar() or 0
        if other_active == 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot deactivate the last active admin",
            )

    if data.full_name is not None:
        target.full_name = data.full_name
    if data.password is not None:
        target.password_hash = hash_password(data.password)
        bump_token_version(target)
    if data.is_active is not None:
        if not data.is_active and target.is_active:
            bump_token_version(target)
        target.is_active = data.is_active

    await db.flush()
    await db.refresh(target)
    return target


@router.get("/stats/dashboard")
async def dashboard_stats(
    user: Annotated[User, Depends(require_owner())],
    db: Annotated[AsyncSession, Depends(get_db)],
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    return await build_dashboard_stats(db, start, end)


@router.get("/stats/overview")
async def stats_overview(
    user: Annotated[User, Depends(require_owner())],
    db: Annotated[AsyncSession, Depends(get_db)],
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    return await get_overview_stats(db, parse_period_bound(start), parse_period_bound(end, end_of_day=True))


@router.get("/stats/analytics")
async def stats_analytics(
    user: Annotated[User, Depends(require_owner())],
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
    user: Annotated[User, Depends(require_owner())],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await get_all_trader_stats(db)


@router.get("/stats/dolivshchiks")
async def stats_dolivshchiks(
    user: Annotated[User, Depends(require_owner())],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await get_all_dolivshchik_stats(db)


@router.get("/employees")
async def employee_stats(
    user: Annotated[User, Depends(require_owner())],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await build_employee_stats(db)


@router.get("/export/stats.xlsx")
async def export_excel(
    user: Annotated[User, Depends(require_owner())],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    data = await export_stats_excel(db)
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=stats.xlsx"},
    )
