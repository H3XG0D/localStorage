from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DealResult,
    Doliv,
    Requisite,
    RequisiteStatus,
    User,
    UserRole,
    Zaliv,
)
from app.services.stats import (
    get_all_dolivshchik_stats,
    get_all_trader_stats,
    get_analytics_chart,
    get_analytics_summary,
    get_overview_stats,
)


def _money(value) -> Decimal:
    return value or Decimal("0")


def parse_period_bound(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format: '{value}'. Use ISO 8601, e.g. 2024-01-31 or 2024-01-31T00:00:00.",
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if end_of_day and len(value) == 10:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed


async def build_dashboard_stats(
    db: AsyncSession,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = parse_period_bound(start)
    end_dt = parse_period_bound(end, end_of_day=True)

    overview = await get_overview_stats(db, start_dt, end_dt)
    status_counts = dict(
        (await db.execute(select(Requisite.status, func.count(Requisite.id)).group_by(Requisite.status))).all()
    )

    result_q = select(
        func.coalesce(func.sum(DealResult.zaliv_profit), 0),
        func.coalesce(func.sum(DealResult.doliv_profit_loss), 0),
        func.coalesce(func.sum(DealResult.doliv_profit_loss).filter(DealResult.doliv_profit_loss < 0), 0),
    )
    if start_dt:
        result_q = result_q.where(DealResult.calculated_at >= start_dt)
    if end_dt:
        result_q = result_q.where(DealResult.calculated_at <= end_dt)
    result_row = (await db.execute(result_q)).one()
    zaliv_profit, doliv_profit_loss, doliv_loss = map(_money, result_row)
    loss_abs = abs(doliv_loss)

    fc_count = overview.fake_check_count
    fc_loss_usdt = overview.fake_check_loss_usdt

    new_requisites_today = (
        await db.execute(select(func.count(Requisite.id)).where(Requisite.created_at >= day_start))
    ).scalar() or 0
    zalivs_today = (
        await db.execute(select(func.count(Zaliv.id)).where(Zaliv.created_at >= day_start))
    ).scalar() or 0
    dolivs_today = (
        await db.execute(select(func.count(Doliv.id)).where(Doliv.completed_at >= day_start))
    ).scalar() or 0
    closed_today = (
        await db.execute(
            select(func.count(Requisite.id)).where(
                Requisite.status == RequisiteStatus.closed,
                Requisite.updated_at >= day_start,
            )
        )
    ).scalar() or 0

    distribution_total = abs(zaliv_profit) + abs(doliv_profit_loss) + abs(fc_loss_usdt)
    if distribution_total == 0:
        distribution = [
            {"name": "Трейдеры", "value": 0, "amount": "0"},
            {"name": "Доливы", "value": 0, "amount": "0"},
            {"name": "Фейк-чеки", "value": 0, "amount": "0"},
        ]
    else:
        distribution = [
            {
                "name": "Трейдеры",
                "value": float((abs(zaliv_profit) / distribution_total * 100).quantize(Decimal("0.01"))),
                "amount": str(zaliv_profit),
            },
            {
                "name": "Доливы",
                "value": float((abs(doliv_profit_loss) / distribution_total * 100).quantize(Decimal("0.01"))),
                "amount": str(doliv_profit_loss),
            },
            {
                "name": "Фейк-чеки",
                "value": float((abs(fc_loss_usdt) / distribution_total * 100).quantize(Decimal("0.01"))),
                "amount": str(-abs(fc_loss_usdt)),
            },
        ]

    return {
        "total_turnover": overview.total_turnover,
        "total_turnover_usdt": overview.total_turnover_usdt,
        "total_profit": overview.total_profit,
        "doliv_loss": loss_abs,
        "fake_check_count": fc_count,
        "fake_check_loss_usdt": fc_loss_usdt,
        "active_requisites": (status_counts.get(RequisiteStatus.active) or 0)
        + (status_counts.get(RequisiteStatus.in_work) or 0),
        "awaiting_doliv": status_counts.get(RequisiteStatus.awaiting_doliv) or 0,
        "closed_requisites": status_counts.get(RequisiteStatus.closed) or 0,
        "dolivs_count": overview.dolivs_count,
        "profit_by_day": overview.profit_by_day,
        "profit_distribution": distribution,
        "operations_today": {
            "new_requisites": new_requisites_today,
            "zalivs": zalivs_today,
            "dolivs": dolivs_today,
            "closed_requisites": closed_today,
        },
    }


async def build_stats_analytics(
    db: AsyncSession,
    start: str | None = None,
    end: str | None = None,
    trader_id: int | None = None,
    requisite_id: int | None = None,
    period: str = "day",
) -> dict:
    overview = await get_overview_stats(
        db, parse_period_bound(start), parse_period_bound(end, end_of_day=True)
    )
    start_dt = parse_period_bound(start)
    end_dt = parse_period_bound(end, end_of_day=True)
    summary = await get_analytics_summary(db, start_dt, end_dt, trader_id, requisite_id)
    chart = await get_analytics_chart(
        db,
        start_dt,
        end_dt,
        trader_id,
        requisite_id,
        period,
    )
    traders = (
        await db.execute(
            select(User.id, User.full_name)
            .where(User.role == UserRole.trader, User.is_active == True)
            .order_by(User.full_name)
        )
    ).all()
    requisites = (
        await db.execute(select(Requisite.id, Requisite.name).order_by(Requisite.name))
    ).all()
    return {
        "total_profit": summary["total_profit"],
        "doliv_loss": summary["doliv_loss"],
        "fake_check_count": summary["fake_check_count"],
        "fake_check_loss_usdt": summary["fake_check_loss_usdt"],
        "fake_check_top_requisites": overview.fake_check_top_requisites,
        "fake_check_top_traders": overview.fake_check_top_traders,
        "chart": chart,
        "traders": [{"id": t[0], "name": t[1]} for t in traders],
        "requisites": [{"id": r[0], "name": r[1]} for r in requisites],
    }


async def build_employee_stats(db: AsyncSession) -> list[dict]:
    users = (
        await db.execute(
            select(User)
            .where(User.role.in_([UserRole.trader, UserRole.dolivshchik]))
            .order_by(User.created_at.desc())
        )
    ).scalars().all()
    trader_stats = {s.user_id: s for s in await get_all_trader_stats(db)}
    doliv_stats = {s.user_id: s for s in await get_all_dolivshchik_stats(db)}

    rows = []
    for employee in users:
        if employee.role == UserRole.trader:
            stats = trader_stats.get(employee.id)
            turnover = stats.total_turnover if stats else Decimal("0")
            turnover_usdt = stats.total_turnover_usdt if stats else Decimal("0")
            profit = stats.total_profit if stats else Decimal("0")
            transactions = stats.requisites_count if stats else 0
        elif employee.role == UserRole.dolivshchik:
            stats = doliv_stats.get(employee.id)
            turnover = stats.total_processed if stats else Decimal("0")
            turnover_usdt = stats.total_doliv_amount_usdt if stats else Decimal("0")
            profit = Decimal("0")
            transactions = stats.dolivs_count if stats else 0
        else:
            turnover = Decimal("0")
            turnover_usdt = Decimal("0")
            profit = Decimal("0")
            transactions = 0

        efficiency = (profit / turnover_usdt * 100).quantize(Decimal("0.01")) if turnover_usdt else Decimal("0")
        rows.append(
            {
                "id": employee.id,
                "full_name": employee.full_name,
                "login": employee.login,
                "role": employee.role,
                "is_active": employee.is_active,
                "created_at": employee.created_at,
                "last_login": employee.last_login,
                "turnover": turnover,
                "turnover_usdt": turnover_usdt,
                "profit": profit,
                "transactions": transactions,
                "efficiency": efficiency,
            }
        )
    return rows
