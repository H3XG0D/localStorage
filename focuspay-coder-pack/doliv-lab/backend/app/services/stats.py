from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AppSettings, DealResult, Doliv, DolivRequest, FakeCheck, Requisite, RequisiteStatus, User, UserRole, Zaliv
from app.services.doliv_salary import resolve_doliv_salary_usdt
from app.schemas import (
    AnalyticsChartPoint,
    DolivshchikStats,
    FakeCheckTopRequisite,
    FakeCheckTopTrader,
    StatsOverview,
    TraderStats,
)


def _turnover_usdt_sum():
    """Sum USDT turnover per deal; prefer stored turnover_usdt, fallback to legacy formula."""
    return func.coalesce(
        func.sum(
            case(
                (DealResult.turnover_usdt.isnot(None), DealResult.turnover_usdt),
                (DealResult.avg_rate > 0, DealResult.total_turnover / DealResult.avg_rate),
                else_=0,
            )
        ),
        0,
    )


_CLOSED_STATUSES = (RequisiteStatus.closed, RequisiteStatus.archive)


async def get_trader_stats(db: AsyncSession, trader_id: int) -> TraderStats:
    user = await db.get(User, trader_id)
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())
    month_start = day_start.replace(day=1)

    q = (
        select(
            func.count(Requisite.id),
            func.coalesce(func.sum(DealResult.total_turnover), 0),
            _turnover_usdt_sum(),
            func.coalesce(func.sum(DealResult.final_profit), 0),
            func.coalesce(
                func.sum(DealResult.final_profit).filter(DealResult.calculated_at >= day_start), 0
            ),
            func.coalesce(
                func.sum(DealResult.final_profit).filter(DealResult.calculated_at >= week_start), 0
            ),
            func.coalesce(
                func.sum(DealResult.final_profit).filter(DealResult.calculated_at >= month_start), 0
            ),
        )
        .select_from(Requisite)
        .outerjoin(DealResult, DealResult.requisite_id == Requisite.id)
        .where(Requisite.trader_id == trader_id, Requisite.status.in_(_CLOSED_STATUSES))
    )
    row = (await db.execute(q)).one()
    count, turnover, turnover_usdt, profit, p_day, p_week, p_month = row
    avg = (profit / count) if count else Decimal("0")

    active_profit_q = (
        select(
            func.coalesce(
                func.sum(Zaliv.amount * Zaliv.profit_percent / 100 / Requisite.target_rate), 0
            )
        )
        .select_from(Zaliv)
        .join(Requisite, Requisite.id == Zaliv.requisite_id)
        .where(
            Requisite.trader_id == trader_id,
            Requisite.status.not_in([RequisiteStatus.closed, RequisiteStatus.archive]),
        )
    )
    active_profit_raw = (await db.execute(active_profit_q)).scalar() or 0

    return TraderStats(
        user_id=trader_id,
        login=user.login if user else "",
        full_name=user.full_name if user else "",
        requisites_count=count or 0,
        total_turnover=turnover or Decimal("0"),
        total_turnover_usdt=Decimal(str(turnover_usdt or 0)).quantize(Decimal("0.01")),
        total_profit=profit or Decimal("0"),
        avg_profit_per_requisite=avg.quantize(Decimal("0.01")),
        profit_day=p_day or Decimal("0"),
        profit_week=p_week or Decimal("0"),
        profit_month=p_month or Decimal("0"),
        active_profit=Decimal(str(active_profit_raw)).quantize(Decimal("0.01")),
    )


async def get_dolivshchik_stats(db: AsyncSession, dolivshchik_id: int) -> DolivshchikStats:
    user = await db.get(User, dolivshchik_id)
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    q = select(
        func.count(Doliv.id),
        func.coalesce(func.sum(Doliv.amount), 0),
        func.coalesce(
            func.sum(case((Doliv.rate > 0, Doliv.amount / Doliv.rate), else_=0)),
            0,
        ),
        func.coalesce(func.avg(Doliv.rate), 0),
        func.coalesce(func.sum(Doliv.amount), 0),
        func.coalesce(
            func.count(Doliv.id).filter(Doliv.completed_at >= day_start),
            0,
        ),
    ).where(Doliv.dolivshchik_id == dolivshchik_id)
    row = (await db.execute(q)).one()
    count, total_amt, total_amt_usdt, avg_rate, processed, dolivs_today = row

    # Losses on dolivs in USDT, attributed to this dolivshchik via the deal result.
    loss_q = (
        select(func.coalesce(func.sum(DealResult.doliv_profit_loss), 0))
        .select_from(Doliv)
        .join(DolivRequest, DolivRequest.id == Doliv.request_id)
        .join(DealResult, DealResult.requisite_id == DolivRequest.requisite_id)
        .where(Doliv.dolivshchik_id == dolivshchik_id, DealResult.doliv_profit_loss < 0)
    )
    loss_raw = (await db.execute(loss_q)).scalar() or 0
    total_doliv_loss = abs(Decimal(str(loss_raw))).quantize(Decimal("0.01"))

    salary_per_doliv = Decimal("0")
    if user:
        salary_per_doliv = await resolve_doliv_salary_usdt(db, user)
    earnings_today = (Decimal(str(dolivs_today or 0)) * salary_per_doliv).quantize(Decimal("0.01"))

    return DolivshchikStats(
        user_id=dolivshchik_id,
        login=user.login if user else "",
        full_name=user.full_name if user else "",
        dolivs_count=count or 0,
        total_doliv_amount=total_amt or Decimal("0"),
        total_doliv_amount_usdt=Decimal(str(total_amt_usdt or 0)).quantize(Decimal("0.01")),
        avg_doliv_rate=Decimal(str(avg_rate or 0)).quantize(Decimal("0.0001")),
        total_processed=processed or Decimal("0"),
        total_doliv_loss=total_doliv_loss,
        salary_per_doliv_usdt=salary_per_doliv,
        dolivs_today=int(dolivs_today or 0),
        earnings_today=earnings_today,
    )


async def get_overview_stats(
    db: AsyncSession,
    start: datetime | None = None,
    end: datetime | None = None,
) -> StatsOverview:
    def _apply_date(q, col):
        if start:
            q = q.where(col >= start)
        if end:
            q = q.where(col <= end)
        return q

    main_q = _apply_date(
        select(
            func.coalesce(func.sum(DealResult.total_turnover), 0),
            _turnover_usdt_sum(),
            func.coalesce(func.sum(DealResult.final_profit), 0),
        ).select_from(DealResult),
        DealResult.calculated_at,
    )
    row = (await db.execute(main_q)).one()
    turnover, turnover_usdt, total_profit = row

    req_count_q = _apply_date(
        select(func.count(Requisite.id))
        .join(DealResult, DealResult.requisite_id == Requisite.id)
        .where(Requisite.status.in_(_CLOSED_STATUSES)),
        DealResult.calculated_at,
    ) if (start or end) else select(func.count(Requisite.id)).where(Requisite.status == RequisiteStatus.closed)
    req_count = (await db.execute(req_count_q)).scalar() or 0

    doliv_count_q = _apply_date(
        select(func.count(Doliv.id))
        .join(DolivRequest, DolivRequest.id == Doliv.request_id)
        .join(DealResult, DealResult.requisite_id == DolivRequest.requisite_id),
        DealResult.calculated_at,
    ) if (start or end) else select(func.count(Doliv.id))
    doliv_count = (await db.execute(doliv_count_q)).scalar() or 0

    all_days_q = _apply_date(
        select(
            func.date(DealResult.calculated_at).label("day"),
            func.sum(DealResult.final_profit).label("profit"),
        )
        .group_by(func.date(DealResult.calculated_at))
        .order_by(func.date(DealResult.calculated_at).desc()),
        DealResult.calculated_at,
    )
    all_rows = (await db.execute(all_days_q)).all()

    days = [{"day": str(r.day), "profit": float(r.profit)} for r in all_rows[:30]]

    # Daily doliv losses and fake-check losses for chart overlays
    doliv_days_q = _apply_date(
        select(
            func.date(DealResult.calculated_at).label("day"),
            func.coalesce(
                func.sum(DealResult.doliv_profit_loss).filter(DealResult.doliv_profit_loss < 0),
                0,
            ).label("doliv_loss"),
        )
        .group_by(func.date(DealResult.calculated_at))
        .order_by(func.date(DealResult.calculated_at).desc()),
        DealResult.calculated_at,
    )
    doliv_day_rows = (await db.execute(doliv_days_q)).all()
    doliv_by_day = {str(r.day): abs(float(r.doliv_loss or 0)) for r in doliv_day_rows}

    fc_days_q = select(
        func.date(FakeCheck.operation_date).label("day"),
        func.coalesce(func.sum(FakeCheck.amount_usdt), 0).label("fc_loss"),
    ).group_by(func.date(FakeCheck.operation_date)).order_by(func.date(FakeCheck.operation_date).desc())
    if start:
        fc_days_q = fc_days_q.where(FakeCheck.operation_date >= start.date())
    if end:
        fc_days_q = fc_days_q.where(FakeCheck.operation_date <= end.date())
    fc_day_rows = (await db.execute(fc_days_q)).all()
    fc_by_day = {str(r.day): float(r.fc_loss or 0) for r in fc_day_rows}

    days = []
    for r in all_rows[:30]:
        day_key = str(r.day)
        day_profit = float(r.profit)
        doliv_loss = doliv_by_day.get(day_key, 0.0)
        fc_loss = fc_by_day.get(day_key, 0.0)
        days.append({
            "day": day_key,
            "profit": day_profit,
            "doliv_loss": doliv_loss,
            "fake_check_loss": fc_loss,
            "net_profit": round(day_profit - fc_loss, 2),
        })

    week_map: dict[str, float] = {}
    month_map: dict[str, float] = {}
    doliv_week_map: dict[str, float] = {}
    doliv_month_map: dict[str, float] = {}
    fc_week_map: dict[str, float] = {}
    fc_month_map: dict[str, float] = {}
    for r in all_rows:
        dt = date_type.fromisoformat(str(r.day))
        yr, wk, _ = dt.isocalendar()
        week_key = f"{yr}-W{wk:02d}"
        month_key = dt.strftime("%Y-%m")
        profit_val = float(r.profit)
        week_map[week_key] = week_map.get(week_key, 0.0) + profit_val
        month_map[month_key] = month_map.get(month_key, 0.0) + profit_val
        doliv_val = doliv_by_day.get(str(r.day), 0.0)
        doliv_week_map[week_key] = doliv_week_map.get(week_key, 0.0) + doliv_val
        doliv_month_map[month_key] = doliv_month_map.get(month_key, 0.0) + doliv_val
        fc_val = fc_by_day.get(str(r.day), 0.0)
        fc_week_map[week_key] = fc_week_map.get(week_key, 0.0) + fc_val
        fc_month_map[month_key] = fc_month_map.get(month_key, 0.0) + fc_val

    profit_by_week = [
        {
            "week": k,
            "profit": round(v, 2),
            "doliv_loss": round(doliv_week_map.get(k, 0.0), 2),
            "fake_check_loss": round(fc_week_map.get(k, 0.0), 2),
            "net_profit": round(v - fc_week_map.get(k, 0.0), 2),
        }
        for k, v in sorted(week_map.items())
    ]
    profit_by_month = [
        {
            "month": k,
            "profit": round(v, 2),
            "doliv_loss": round(doliv_month_map.get(k, 0.0), 2),
            "fake_check_loss": round(fc_month_map.get(k, 0.0), 2),
            "net_profit": round(v - fc_month_map.get(k, 0.0), 2),
        }
        for k, v in sorted(month_map.items())
    ]

    fc_q = select(
        func.count(FakeCheck.id),
        func.coalesce(func.sum(FakeCheck.amount_rub), 0),
        func.coalesce(func.sum(FakeCheck.amount_usdt), 0),
        func.coalesce(func.avg(FakeCheck.rate), 0),
    )
    if start:
        fc_q = fc_q.where(FakeCheck.operation_date >= start.date())
    if end:
        fc_q = fc_q.where(FakeCheck.operation_date <= end.date())
    fc_row = (await db.execute(fc_q)).one()
    fc_count, fc_rub, fc_usdt, fc_avg_rate = fc_row

    top_req_q = (
        select(
            Requisite.id,
            Requisite.name,
            func.coalesce(func.sum(FakeCheck.amount_usdt), 0),
            func.count(FakeCheck.id),
        )
        .join(FakeCheck, FakeCheck.requisite_id == Requisite.id)
        .group_by(Requisite.id, Requisite.name)
        .order_by(func.coalesce(func.sum(FakeCheck.amount_usdt), 0).desc())
        .limit(10)
    )
    if start:
        top_req_q = top_req_q.where(FakeCheck.operation_date >= start.date())
    if end:
        top_req_q = top_req_q.where(FakeCheck.operation_date <= end.date())
    top_req_rows = (await db.execute(top_req_q)).all()

    top_trader_q = (
        select(
            User.id,
            User.full_name,
            func.coalesce(func.sum(FakeCheck.amount_usdt), 0),
            func.count(FakeCheck.id),
        )
        .join(Requisite, Requisite.trader_id == User.id)
        .join(FakeCheck, FakeCheck.requisite_id == Requisite.id)
        .group_by(User.id, User.full_name)
        .order_by(func.coalesce(func.sum(FakeCheck.amount_usdt), 0).desc())
        .limit(10)
    )
    if start:
        top_trader_q = top_trader_q.where(FakeCheck.operation_date >= start.date())
    if end:
        top_trader_q = top_trader_q.where(FakeCheck.operation_date <= end.date())
    top_trader_rows = (await db.execute(top_trader_q)).all()

    return StatsOverview(
        total_turnover=turnover or Decimal("0"),
        total_turnover_usdt=Decimal(str(turnover_usdt or 0)).quantize(Decimal("0.01")),
        total_profit=total_profit or Decimal("0"),
        requisites_count=req_count or 0,
        dolivs_count=doliv_count or 0,
        profit_by_day=days,
        profit_by_week=profit_by_week,
        profit_by_month=profit_by_month,
        fake_check_count=int(fc_count or 0),
        fake_check_loss_rub=Decimal(str(fc_rub or 0)).quantize(Decimal("0.01")),
        fake_check_loss_usdt=Decimal(str(fc_usdt or 0)).quantize(Decimal("0.01")),
        fake_check_avg_rate=Decimal(str(fc_avg_rate or 0)).quantize(Decimal("0.0001")),
        fake_check_top_requisites=[
            FakeCheckTopRequisite(
                requisite_id=r[0],
                name=r[1],
                loss_usdt=Decimal(str(r[2] or 0)).quantize(Decimal("0.01")),
                count=int(r[3] or 0),
            )
            for r in top_req_rows
        ],
        fake_check_top_traders=[
            FakeCheckTopTrader(
                trader_id=r[0],
                name=r[1],
                loss_usdt=Decimal(str(r[2] or 0)).quantize(Decimal("0.01")),
                count=int(r[3] or 0),
            )
            for r in top_trader_rows
        ],
    )


async def get_all_trader_stats(db: AsyncSession) -> list[TraderStats]:
    result = await db.execute(select(User.id).where(User.role == UserRole.trader, User.is_active == True))
    ids = [r[0] for r in result.all()]
    return [await get_trader_stats(db, uid) for uid in ids]


async def get_all_dolivshchik_stats(db: AsyncSession) -> list[DolivshchikStats]:
    result = await db.execute(
        select(User.id).where(User.role == UserRole.dolivshchik, User.is_active == True)
    )
    ids = [r[0] for r in result.all()]
    return [await get_dolivshchik_stats(db, uid) for uid in ids]


async def get_analytics_chart(
    db: AsyncSession,
    start: datetime | None = None,
    end: datetime | None = None,
    trader_id: int | None = None,
    requisite_id: int | None = None,
    period: str = "day",
) -> list[AnalyticsChartPoint]:
    def _apply_dr_date(q, col):
        if start:
            q = q.where(col >= start)
        if end:
            q = q.where(col <= end)
        return q

    dr_q = _apply_dr_date(
        select(
            func.date(DealResult.calculated_at).label("day"),
            func.coalesce(func.sum(DealResult.final_profit), 0).label("profit"),
            func.coalesce(
                func.sum(DealResult.doliv_profit_loss).filter(DealResult.doliv_profit_loss < 0),
                0,
            ).label("doliv_loss"),
        )
        .select_from(DealResult)
        .join(Requisite, Requisite.id == DealResult.requisite_id)
        .group_by(func.date(DealResult.calculated_at))
        .order_by(func.date(DealResult.calculated_at).desc()),
        DealResult.calculated_at,
    )
    if trader_id:
        dr_q = dr_q.where(Requisite.trader_id == trader_id)
    if requisite_id:
        dr_q = dr_q.where(DealResult.requisite_id == requisite_id)

    dr_rows = (await db.execute(dr_q)).all()
    day_map: dict[str, dict[str, float]] = {}
    for r in dr_rows:
        key = str(r.day)
        day_map[key] = {
            "profit": float(r.profit or 0),
            "doliv_loss": abs(float(r.doliv_loss or 0)),
            "fake_check_loss": 0.0,
        }

    fc_q = (
        select(
            func.date(FakeCheck.operation_date).label("day"),
            func.coalesce(func.sum(FakeCheck.amount_usdt), 0).label("fc_loss"),
        )
        .select_from(FakeCheck)
        .join(Requisite, Requisite.id == FakeCheck.requisite_id)
        .group_by(func.date(FakeCheck.operation_date))
        .order_by(func.date(FakeCheck.operation_date).desc())
    )
    if start:
        fc_q = fc_q.where(FakeCheck.operation_date >= start.date())
    if end:
        fc_q = fc_q.where(FakeCheck.operation_date <= end.date())
    if trader_id:
        fc_q = fc_q.where(Requisite.trader_id == trader_id)
    if requisite_id:
        fc_q = fc_q.where(FakeCheck.requisite_id == requisite_id)

    fc_rows = (await db.execute(fc_q)).all()
    for r in fc_rows:
        key = str(r.day)
        if key not in day_map:
            day_map[key] = {"profit": 0.0, "doliv_loss": 0.0, "fake_check_loss": 0.0}
        day_map[key]["fake_check_loss"] = float(r.fc_loss or 0)

    if period == "week":
        agg: dict[str, dict[str, float]] = {}
        for day_key, vals in day_map.items():
            dt = date_type.fromisoformat(day_key)
            yr, wk, _ = dt.isocalendar()
            label = f"{yr}-W{wk:02d}"
            if label not in agg:
                agg[label] = {"profit": 0.0, "doliv_loss": 0.0, "fake_check_loss": 0.0}
            for k in ("profit", "doliv_loss", "fake_check_loss"):
                agg[label][k] += vals[k]
        day_map = agg
    elif period == "month":
        agg = {}
        for day_key, vals in day_map.items():
            dt = date_type.fromisoformat(day_key)
            label = dt.strftime("%Y-%m")
            if label not in agg:
                agg[label] = {"profit": 0.0, "doliv_loss": 0.0, "fake_check_loss": 0.0}
            for k in ("profit", "doliv_loss", "fake_check_loss"):
                agg[label][k] += vals[k]
        day_map = agg

    points = []
    for label in sorted(day_map.keys()):
        vals = day_map[label]
        profit = round(vals["profit"], 2)
        doliv_loss = round(vals["doliv_loss"], 2)
        fc_loss = round(vals["fake_check_loss"], 2)
        points.append(
            AnalyticsChartPoint(
                label=label,
                profit=profit,
                doliv_loss=doliv_loss,
                fake_check_loss=fc_loss,
                net_profit=round(profit - fc_loss, 2),
            )
        )
    return points[-30:]


async def get_analytics_summary(
    db: AsyncSession,
    start: datetime | None = None,
    end: datetime | None = None,
    trader_id: int | None = None,
    requisite_id: int | None = None,
) -> dict[str, Decimal | int]:
    dr_q = select(
        func.coalesce(func.sum(DealResult.final_profit), 0),
        func.coalesce(
            func.sum(DealResult.doliv_profit_loss).filter(DealResult.doliv_profit_loss < 0),
            0,
        ),
    ).select_from(DealResult).join(Requisite, Requisite.id == DealResult.requisite_id)
    if start:
        dr_q = dr_q.where(DealResult.calculated_at >= start)
    if end:
        dr_q = dr_q.where(DealResult.calculated_at <= end)
    if trader_id:
        dr_q = dr_q.where(Requisite.trader_id == trader_id)
    if requisite_id:
        dr_q = dr_q.where(DealResult.requisite_id == requisite_id)
    profit, doliv_loss_raw = (await db.execute(dr_q)).one()

    fc_q = (
        select(
            func.count(FakeCheck.id),
            func.coalesce(func.sum(FakeCheck.amount_usdt), 0),
        )
        .select_from(FakeCheck)
        .join(Requisite, Requisite.id == FakeCheck.requisite_id)
    )
    if start:
        fc_q = fc_q.where(FakeCheck.operation_date >= start.date())
    if end:
        fc_q = fc_q.where(FakeCheck.operation_date <= end.date())
    if trader_id:
        fc_q = fc_q.where(Requisite.trader_id == trader_id)
    if requisite_id:
        fc_q = fc_q.where(FakeCheck.requisite_id == requisite_id)
    fc_count, fc_loss = (await db.execute(fc_q)).one()

    doliv_loss = abs(Decimal(str(doliv_loss_raw or 0))).quantize(Decimal("0.01"))
    fc_loss_usdt = Decimal(str(fc_loss or 0)).quantize(Decimal("0.01"))
    return {
        "total_profit": Decimal(str(profit or 0)).quantize(Decimal("0.01")),
        "doliv_loss": doliv_loss,
        "fake_check_count": int(fc_count or 0),
        "fake_check_loss_usdt": fc_loss_usdt,
    }


async def export_stats_excel(db: AsyncSession) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Overview"
    overview = await get_overview_stats(db)
    ws.append(["Total Turnover (RUB)", float(overview.total_turnover)])
    ws.append(["Total Profit (USDT)", float(overview.total_profit)])
    ws.append(["Closed Requisites", overview.requisites_count])
    ws.append(["Total Dolivs", overview.dolivs_count])

    ws2 = wb.create_sheet("Traders")
    ws2.append([
        "ID", "Name", "Requisites", "Turnover (RUB)", "Profit (USDT)",
        "Avg Profit (USDT)", "Day (USDT)", "Week (USDT)", "Month (USDT)",
    ])
    for s in await get_all_trader_stats(db):
        ws2.append([
            s.user_id, s.full_name, s.requisites_count,
            float(s.total_turnover), float(s.total_profit), float(s.avg_profit_per_requisite),
            float(s.profit_day), float(s.profit_week), float(s.profit_month),
        ])

    ws3 = wb.create_sheet("Dolivshchiks")
    ws3.append(["ID", "Name", "Dolivs", "Total Amount (RUB)", "Avg Rate", "Processed (RUB)", "Doliv Loss (USDT)"])
    for s in await get_all_dolivshchik_stats(db):
        ws3.append([
            s.user_id, s.full_name, s.dolivs_count,
            float(s.total_doliv_amount), float(s.avg_doliv_rate), float(s.total_processed),
            float(s.total_doliv_loss),
        ])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
