"""Trader cards inventory, accept-limit sessions, and operating expenses."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import require_role
from app.core.database import get_db
from app.models import (
    CardStatus,
    ExpenseCategory,
    Requisite,
    RequisiteStatus,
    TraderCard,
    TraderExpense,
    User,
    UserRole,
    Zaliv,
)
from app.schemas import (
    AdminCardTrafficUpdate,
    DisplayCurrencyUpdate,
    PaymentBand,
    TraderCardAccepting,
    TraderCardBulkRequest,
    TraderCardCreate,
    TraderCardGoOnline,
    TraderCardListResponse,
    TraderCardResponse,
    TraderCardUpdate,
    TraderExpenseCreate,
    TraderExpenseResponse,
    TraderNetSummary,
)
from app.services import token_ledger
from app.services import working_rate as wr_svc
from app.services.office_day import day_start_utc as _day_start_utc
from app.services.payment_bands import bands_minmax, normalize_bands
from app.services.payment_channel import (
    assert_channel_ready_for_online,
    normalize_card_number,
    normalize_phone,
    parse_channel,
    session_display_name,
)
from app.services.rapira import exposure_usdt, get_rapira_usdt_rub_rate

router = APIRouter(tags=["cards-expenses"])


async def _expense_rate(db: AsyncSession, explicit: Decimal | None) -> Decimal:
    if explicit is not None:
        return explicit
    try:
        return await wr_svc.require_active_rate_value(db)
    except HTTPException:
        return await get_rapira_usdt_rub_rate()


def _resolve_session_limit(card: TraderCard, override: Decimal | None) -> Decimal:
    if override is not None:
        return override
    if card.daily_limit_rub is not None:
        return card.daily_limit_rub
    if card.accept_limit_rub is not None:
        return card.accept_limit_rub
    raise HTTPException(400, "daily_limit_rub (or accept_limit_rub) required to go online")

CATEGORY_LABELS = {
    ExpenseCategory.card_purchase: "Закупка карты",
    ExpenseCategory.warm: "Прогрев",
    ExpenseCategory.block_loss: "Блок / потеря",
    ExpenseCategory.other: "Прочее",
}

OPEN_SESSION_STATUSES = (
    RequisiteStatus.active,
    RequisiteStatus.in_work,
    RequisiteStatus.awaiting_doliv,
    RequisiteStatus.doliv_in_progress,
)


def _q_rub(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q_usdt(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _parse_status(raw: str) -> CardStatus:
    try:
        return CardStatus(raw)
    except ValueError as e:
        raise HTTPException(400, f"Invalid card status: {raw}") from e


def _parse_category(raw: str) -> ExpenseCategory:
    try:
        return ExpenseCategory(raw)
    except ValueError as e:
        raise HTTPException(400, f"Invalid expense category: {raw}") from e


async def _assert_trader_access(actor: User, trader_id: int, db: AsyncSession) -> User:
    trader = await db.get(User, trader_id)
    if not trader or trader.role != UserRole.trader:
        raise HTTPException(404, "Trader not found")
    if actor.role == UserRole.admin:
        return trader
    if actor.role == UserRole.trader and actor.id == trader_id:
        return trader
    if actor.role == UserRole.teamlead and trader.teamlead_id == actor.id:
        return trader
    raise HTTPException(403, "No access to this trader")


async def _open_session_for_card(db: AsyncSession, card_id: int) -> Requisite | None:
    result = await db.execute(
        select(Requisite)
        .options(selectinload(Requisite.zalivs))
        .where(
            Requisite.card_id == card_id,
            Requisite.status.in_(OPEN_SESSION_STATUSES),
        )
        .order_by(Requisite.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _assert_no_open_session(db: AsyncSession, card_id: int) -> None:
    existing = await _open_session_for_card(db, card_id)
    if existing:
        raise HTTPException(
            400,
            f"Card already has open session #{existing.id} ({existing.status.value})",
        )


async def _start_session(
    db: AsyncSession,
    *,
    trader: User,
    actor: User,
    card: TraderCard,
    accept_limit_rub: Decimal,
    target_rate: Decimal,
    comment: str | None = None,
) -> Requisite:
    await _assert_no_open_session(db, card.id)
    accept_limit_rub = _q_rub(accept_limit_rub)
    if accept_limit_rub <= 0:
        raise HTTPException(400, "accept_limit_rub must be > 0")

    token = await token_ledger.require_token_for_trader(db, trader)
    hold_amount = None
    work_token_id = None
    if token and not (trader.deposit_exempt or token.deposit_exempt):
        work_token_id = token.id
        hold_amount = exposure_usdt(accept_limit_rub, target_rate)

    card.accept_limit_rub = accept_limit_rub
    card.target_rate = target_rate
    assert_channel_ready_for_online(card)

    req = Requisite(
        trader_id=trader.id,
        card_id=card.id,
        name=session_display_name(card),
        total_amount=accept_limit_rub,
        target_rate=target_rate,
        comment=comment,
        status=RequisiteStatus.active,
        float_rub=Decimal("0"),
        work_token_id=work_token_id,
        hold_usdt=hold_amount,
    )
    db.add(req)
    await db.flush()

    if token and hold_amount is not None:
        await token_ledger.hold_for_requisite(
            db, token, req.id, hold_amount, actor_id=actor.id
        )

    card.linked_requisite_id = req.id
    card.accepting_enabled = True
    card.paused_at = None
    await db.flush()
    return req


async def _received_today_map(db: AsyncSession, card_ids: list[int], day_start: datetime) -> dict[int, Decimal]:
    if not card_ids:
        return {}
    result = await db.execute(
        select(Requisite.card_id, func.coalesce(func.sum(Zaliv.amount), 0))
        .join(Zaliv, Zaliv.requisite_id == Requisite.id)
        .where(Requisite.card_id.in_(card_ids), Zaliv.created_at >= day_start)
        .group_by(Requisite.card_id)
    )
    return {int(cid): _q_rub(Decimal(str(total))) for cid, total in result.all() if cid is not None}


def _not_accepting_reason(
    card: TraderCard,
    *,
    session: Requisite | None,
    session_remaining: Decimal | None,
    daily_remaining: Decimal | None,
) -> str | None:
    status = card.status.value if hasattr(card.status, "value") else str(card.status)
    if status == CardStatus.blocked.value:
        return "blocked"
    if status == CardStatus.warming.value:
        return "warming"
    if status == CardStatus.archived.value:
        return "disabled"
    if not card.accepting_enabled:
        return "disabled"
    if session is None:
        return "no_session"
    if daily_remaining is not None and daily_remaining <= 0:
        return "daily_limit_reached"
    if session_remaining is not None and session_remaining <= 0:
        return "session_filled"
    return None


def _card_to_response(
    card: TraderCard,
    *,
    expenses_rub: Decimal,
    expenses_usdt: Decimal,
    session: Requisite | None,
    session_remaining: Decimal | None,
    received_today: Decimal,
) -> TraderCardResponse:
    daily_remaining = None
    if card.daily_limit_rub is not None:
        daily_remaining = _q_rub(Decimal(str(card.daily_limit_rub)) - received_today)
        if daily_remaining < 0:
            daily_remaining = Decimal("0.00")

    reason = _not_accepting_reason(
        card,
        session=session,
        session_remaining=session_remaining,
        daily_remaining=daily_remaining,
    )
    accepting = reason is None
    bands_raw = card.payment_bands
    bands = None
    if bands_raw:
        bands = [PaymentBand(min_rub=Decimal(str(b["min_rub"])), max_rub=Decimal(str(b["max_rub"]))) for b in bands_raw]

    return TraderCardResponse(
        id=card.id,
        trader_id=card.trader_id,
        name=card.name,
        last4=card.last4,
        bank=card.bank,
        status=card.status.value if hasattr(card.status, "value") else str(card.status),
        purchase_cost_rub=card.purchase_cost_rub,
        recipient_name=card.recipient_name,
        card_number=card.card_number,
        phone=card.phone,
        channel=card.channel or "c2c",
        daily_limit_rub=card.daily_limit_rub,
        min_payment_rub=card.min_payment_rub,
        max_payment_rub=card.max_payment_rub,
        payment_bands=bands,
        accept_limit_rub=card.accept_limit_rub,
        target_rate=card.target_rate,
        linked_requisite_id=card.linked_requisite_id,
        notes=card.notes,
        expenses_rub=_q_rub(expenses_rub),
        expenses_usdt=_q_usdt(expenses_usdt),
        session_id=session.id if session else None,
        session_status=session.status.value if session else None,
        session_total_rub=session.total_amount if session else None,
        session_remaining_rub=session_remaining,
        session_hold_usdt=session.hold_usdt if session else None,
        session_float_rub=session.float_rub if session else None,
        accepting_enabled=bool(card.accepting_enabled),
        paused_at=card.paused_at,
        received_today_rub=received_today,
        daily_remaining_rub=daily_remaining,
        accepting=accepting,
        not_accepting_reason=reason,
        traffic_min_orders=card.traffic_min_orders,
        traffic_max_orders=card.traffic_max_orders,
        traffic_min_volume_rub=card.traffic_min_volume_rub,
        traffic_max_volume_rub=card.traffic_max_volume_rub,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


async def _card_response(db: AsyncSession, card: TraderCard) -> TraderCardResponse:
    await db.refresh(card)
    result = await db.execute(
        select(
            func.coalesce(func.sum(TraderExpense.amount_rub), 0),
            func.coalesce(func.sum(TraderExpense.amount_usdt), 0),
        ).where(TraderExpense.card_id == card.id)
    )
    rub, usdt = result.one()
    session = await _open_session_for_card(db, card.id)
    session_remaining = None
    if session:
        zaliv_total = sum((z.amount for z in session.zalivs), Decimal("0"))
        session_remaining = _q_rub(session.total_amount - zaliv_total)
    day_start = await _day_start_utc(db)
    received_map = await _received_today_map(db, [card.id], day_start)
    return _card_to_response(
        card,
        expenses_rub=Decimal(str(rub)),
        expenses_usdt=Decimal(str(usdt)),
        session=session,
        session_remaining=session_remaining,
        received_today=received_map.get(card.id, Decimal("0.00")),
    )


async def _set_accepting(
    db: AsyncSession,
    *,
    trader: User,
    actor: User,
    card: TraderCard,
    enabled: bool,
) -> TraderCard:
    if not enabled:
        card.accepting_enabled = False
        card.paused_at = datetime.now(timezone.utc)
        await db.flush()
        return card
    if card.status == CardStatus.blocked:
        raise HTTPException(400, "Blocked card cannot accept")
    if card.status == CardStatus.archived:
        raise HTTPException(400, "Archived card cannot accept")
    if card.status != CardStatus.active:
        raise HTTPException(400, "Only active cards can accept payments")
    session = await _open_session_for_card(db, card.id)
    if not session:
        rate = await wr_svc.require_active_rate_value(db)
        limit = _resolve_session_limit(card, None)
        await _start_session(
            db,
            trader=trader,
            actor=actor,
            card=card,
            accept_limit_rub=limit,
            target_rate=rate,
        )
    else:
        card.accepting_enabled = True
        card.paused_at = None
        await db.flush()
    return card


async def _create_expense_row(
    db: AsyncSession,
    *,
    trader: User,
    actor: User,
    category: ExpenseCategory,
    amount_rub: Decimal,
    rate: Decimal,
    card_id: int | None = None,
    requisite_id: int | None = None,
    comment: str | None = None,
) -> TraderExpense:
    amount_rub = _q_rub(amount_rub)
    amount_usdt = _q_usdt(amount_rub / rate)
    exp = TraderExpense(
        trader_id=trader.id,
        category=category,
        amount_rub=amount_rub,
        rate=rate,
        amount_usdt=amount_usdt,
        card_id=card_id,
        requisite_id=requisite_id,
        comment=comment,
        actor_id=actor.id,
        debited=False,
    )
    db.add(exp)
    await db.flush()

    token = await token_ledger.get_active_token_for_user(db, trader.id)
    if token:
        await token_ledger.debit(
            db,
            token.id,
            amount_usdt,
            actor_id=actor.id,
            idempotency_key=f"expense-{exp.id}",
            requisite_id=requisite_id,
            comment=comment or f"Expense {category.value}",
        )
        exp.debited = True
        await db.flush()
    return exp


# ── Cards ────────────────────────────────────────────────────────────────────

@router.get("/trader/cards", response_model=TraderCardListResponse)
async def list_my_cards(
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = Query(None),
    status: str | None = Query(None),
    bank: str | None = Query(None),
    channel: str | None = Query(None),
    accepting: bool | None = Query(None),
    sort: str = Query("id"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    stmt = select(TraderCard).where(TraderCard.trader_id == user.id)
    if status:
        stmt = stmt.where(TraderCard.status == _parse_status(status))
    if bank:
        stmt = stmt.where(TraderCard.bank.ilike(f"%{bank}%"))
    if channel:
        stmt = stmt.where(TraderCard.channel == channel)
    if accepting is True:
        stmt = stmt.where(TraderCard.accepting_enabled.is_(True), TraderCard.status == CardStatus.active)
    elif accepting is False:
        stmt = stmt.where(
            or_(TraderCard.accepting_enabled.is_(False), TraderCard.status != CardStatus.active)
        )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                TraderCard.name.ilike(like),
                TraderCard.bank.ilike(like),
                TraderCard.last4.ilike(like),
                TraderCard.phone.ilike(like),
                TraderCard.card_number.ilike(like),
                TraderCard.recipient_name.ilike(like),
            )
        )
    cards = list((await db.execute(stmt.order_by(TraderCard.id.desc()))).scalars().all())
    items = [await _card_response(db, c) for c in cards]
    sort_key = sort.lstrip("-")
    reverse = sort.startswith("-") or sort == "id"

    def _sort_val(row: TraderCardResponse):
        if sort_key == "name":
            return row.name.lower()
        if sort_key == "bank":
            return (row.bank or "").lower()
        if sort_key == "daily_remaining":
            return float(row.daily_remaining_rub or 0)
        if sort_key == "received_today":
            return float(row.received_today_rub or 0)
        return row.id

    items.sort(key=_sort_val, reverse=reverse if sort_key != "name" else sort.startswith("-"))
    if sort_key == "name" and sort.startswith("-"):
        items.reverse()
    total = len(items)
    return TraderCardListResponse(items=items[offset : offset + limit], total=total)


@router.post("/trader/cards", response_model=TraderCardResponse, status_code=201)
async def create_my_card(
    data: TraderCardCreate,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _create_card(db, user, user, data)


@router.patch("/trader/cards/{card_id}", response_model=TraderCardResponse)
async def update_my_card(
    card_id: int,
    data: TraderCardUpdate,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    card = await db.get(TraderCard, card_id)
    if not card or card.trader_id != user.id:
        raise HTTPException(404, "Card not found")
    return await _update_card(db, card, data)


@router.post("/trader/cards/{card_id}/go-online", response_model=TraderCardResponse)
async def go_online_my_card(
    card_id: int,
    data: TraderCardGoOnline,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    card = await db.get(TraderCard, card_id)
    if not card or card.trader_id != user.id:
        raise HTTPException(404, "Card not found")
    if card.status == CardStatus.blocked:
        raise HTTPException(400, "Blocked card cannot go online")
    # Office working rate only — trader-supplied target_rate is ignored
    rate = await wr_svc.require_active_rate_value(db)
    limit = _resolve_session_limit(card, data.accept_limit_rub)
    await _start_session(
        db,
        trader=user,
        actor=user,
        card=card,
        accept_limit_rub=limit,
        target_rate=rate,
        comment=data.comment,
    )
    return await _card_response(db, card)


@router.post("/trader/cards/{card_id}/accepting", response_model=TraderCardResponse)
async def set_card_accepting(
    card_id: int,
    data: TraderCardAccepting,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    card = await db.get(TraderCard, card_id)
    if not card or card.trader_id != user.id:
        raise HTTPException(404, "Card not found")
    await _set_accepting(db, trader=user, actor=user, card=card, enabled=data.enabled)
    return await _card_response(db, card)


@router.post("/trader/cards/bulk")
async def bulk_cards(
    data: TraderCardBulkRequest,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    action = (data.action or "").strip().lower()
    if action not in {"enable", "disable", "set_daily_limit", "set_status"}:
        raise HTTPException(400, "Unknown bulk action")
    result = await db.execute(
        select(TraderCard).where(TraderCard.id.in_(data.ids), TraderCard.trader_id == user.id)
    )
    cards = {c.id: c for c in result.scalars().all()}
    ok: list[int] = []
    errors: list[dict] = []
    for card_id in data.ids:
        card = cards.get(card_id)
        if not card:
            errors.append({"id": card_id, "detail": "Card not found"})
            continue
        try:
            if action == "enable":
                await _set_accepting(db, trader=user, actor=user, card=card, enabled=True)
            elif action == "disable":
                await _set_accepting(db, trader=user, actor=user, card=card, enabled=False)
            elif action == "set_daily_limit":
                if not data.value:
                    raise HTTPException(400, "value required")
                card.daily_limit_rub = _q_rub(Decimal(data.value))
                card.accept_limit_rub = card.daily_limit_rub
                await db.flush()
            elif action == "set_status":
                if not data.value:
                    raise HTTPException(400, "value required")
                card.status = _parse_status(data.value)
                if card.status in {CardStatus.blocked, CardStatus.archived}:
                    card.accepting_enabled = False
                    card.paused_at = datetime.now(timezone.utc)
                await db.flush()
            ok.append(card_id)
        except HTTPException as e:
            errors.append({"id": card_id, "detail": str(e.detail)})
        except Exception as e:  # noqa: BLE001
            errors.append({"id": card_id, "detail": str(e)})
    return {"ok": ok, "errors": errors}


@router.get("/admin/cards", response_model=list[TraderCardResponse])
async def admin_list_cards(
    user: Annotated[User, Depends(require_role(UserRole.admin, UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
    trader_id: int | None = Query(None),
):
    q = select(TraderCard).order_by(TraderCard.id.desc())
    if user.role == UserRole.teamlead:
        traders = (
            await db.execute(select(User.id).where(User.teamlead_id == user.id, User.role == UserRole.trader))
        ).scalars().all()
        q = q.where(TraderCard.trader_id.in_(list(traders) or [-1]))
    if trader_id is not None:
        await _assert_trader_access(user, trader_id, db)
        q = q.where(TraderCard.trader_id == trader_id)
    result = await db.execute(q)
    return [await _card_response(db, c) for c in result.scalars().all()]


@router.post("/admin/cards", response_model=TraderCardResponse, status_code=201)
async def admin_create_card(
    data: TraderCardCreate,
    user: Annotated[User, Depends(require_role(UserRole.admin, UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
    trader_id: int = Query(...),
):
    trader = await _assert_trader_access(user, trader_id, db)
    return await _create_card(db, trader, user, data)


def _apply_traffic(card: TraderCard, data: AdminCardTrafficUpdate) -> None:
    fields = data.model_fields_set
    min_o = data.traffic_min_orders if "traffic_min_orders" in fields else card.traffic_min_orders
    max_o = data.traffic_max_orders if "traffic_max_orders" in fields else card.traffic_max_orders
    if min_o is not None and max_o is not None and min_o > max_o:
        raise HTTPException(400, "traffic_min_orders cannot exceed traffic_max_orders")
    min_v = data.traffic_min_volume_rub if "traffic_min_volume_rub" in fields else card.traffic_min_volume_rub
    max_v = data.traffic_max_volume_rub if "traffic_max_volume_rub" in fields else card.traffic_max_volume_rub
    if min_v is not None and max_v is not None and Decimal(min_v) > Decimal(max_v):
        raise HTTPException(400, "traffic_min_volume_rub cannot exceed traffic_max_volume_rub")
    if "traffic_min_orders" in fields:
        card.traffic_min_orders = data.traffic_min_orders
    if "traffic_max_orders" in fields:
        card.traffic_max_orders = data.traffic_max_orders
    if "traffic_min_volume_rub" in fields:
        card.traffic_min_volume_rub = (
            _q_rub(data.traffic_min_volume_rub) if data.traffic_min_volume_rub is not None else None
        )
    if "traffic_max_volume_rub" in fields:
        card.traffic_max_volume_rub = (
            _q_rub(data.traffic_max_volume_rub) if data.traffic_max_volume_rub is not None else None
        )


@router.patch("/admin/cards/{card_id}", response_model=TraderCardResponse)
async def admin_update_card_traffic(
    card_id: int,
    data: AdminCardTrafficUpdate,
    _user: Annotated[User, Depends(require_role(UserRole.admin))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    card = await db.get(TraderCard, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    _apply_traffic(card, data)
    await db.flush()
    return await _card_response(db, card)


async def _create_card(
    db: AsyncSession, trader: User, actor: User, data: TraderCardCreate
) -> TraderCardResponse:
    daily = data.daily_limit_rub or data.accept_limit_rub
    channel = parse_channel(data.channel)
    card_number = normalize_card_number(data.card_number) if data.card_number else None
    phone = normalize_phone(data.phone) if data.phone else None
    last4 = data.last4
    if not last4 and card_number and len(card_number) >= 4:
        last4 = card_number[-4:]
    bands = normalize_bands(data.payment_bands)
    band_min, band_max = bands_minmax(bands)
    min_pay = data.min_payment_rub
    max_pay = data.max_payment_rub
    if bands:
        min_pay = band_min
        max_pay = band_max
    card = TraderCard(
        trader_id=trader.id,
        name=data.name,
        last4=last4,
        bank=data.bank,
        status=_parse_status(data.status),
        purchase_cost_rub=_q_rub(data.purchase_cost_rub),
        recipient_name=data.recipient_name,
        card_number=card_number,
        phone=phone,
        channel=channel.value,
        daily_limit_rub=_q_rub(daily) if daily else None,
        min_payment_rub=_q_rub(min_pay) if min_pay else None,
        max_payment_rub=_q_rub(max_pay) if max_pay else None,
        payment_bands=bands,
        accept_limit_rub=_q_rub(daily) if daily else None,
        linked_requisite_id=data.linked_requisite_id,
        notes=data.notes,
    )
    db.add(card)
    await db.flush()

    if data.record_purchase_expense and data.purchase_cost_rub > 0:
        rate = await _expense_rate(db, data.rate)
        await _create_expense_row(
            db,
            trader=trader,
            actor=actor,
            category=ExpenseCategory.card_purchase,
            amount_rub=data.purchase_cost_rub,
            rate=rate,
            card_id=card.id,
            comment=f"Закупка карты {card.name}",
        )

    if data.go_online:
        limit = _resolve_session_limit(card, data.accept_limit_rub or data.daily_limit_rub)
        rate = await wr_svc.require_active_rate_value(db)
        await _start_session(
            db,
            trader=trader,
            actor=actor,
            card=card,
            accept_limit_rub=limit,
            target_rate=rate,
        )

    return await _card_response(db, card)


async def _update_card(db: AsyncSession, card: TraderCard, data: TraderCardUpdate) -> TraderCardResponse:
    if data.name is not None:
        card.name = data.name
    if data.last4 is not None:
        card.last4 = data.last4
    if data.bank is not None:
        card.bank = data.bank
    if data.status is not None:
        card.status = _parse_status(data.status)
        if card.status in {CardStatus.blocked, CardStatus.archived}:
            card.accepting_enabled = False
            card.paused_at = datetime.now(timezone.utc)
    if data.purchase_cost_rub is not None:
        card.purchase_cost_rub = _q_rub(data.purchase_cost_rub)
    if data.linked_requisite_id is not None:
        card.linked_requisite_id = data.linked_requisite_id
    if data.notes is not None:
        card.notes = data.notes
    if data.recipient_name is not None:
        card.recipient_name = data.recipient_name
    if data.channel is not None:
        card.channel = parse_channel(data.channel).value
    if data.phone is not None:
        card.phone = normalize_phone(data.phone)
    if data.card_number is not None:
        card.card_number = normalize_card_number(data.card_number)
        if card.card_number and len(card.card_number) >= 4:
            card.last4 = card.card_number[-4:]
    if data.daily_limit_rub is not None:
        card.daily_limit_rub = _q_rub(data.daily_limit_rub)
        card.accept_limit_rub = card.daily_limit_rub
    if data.payment_bands is not None:
        bands = normalize_bands(data.payment_bands)
        card.payment_bands = bands
        band_min, band_max = bands_minmax(bands)
        card.min_payment_rub = band_min
        card.max_payment_rub = band_max
    else:
        if data.min_payment_rub is not None:
            card.min_payment_rub = _q_rub(data.min_payment_rub)
        if data.max_payment_rub is not None:
            card.max_payment_rub = _q_rub(data.max_payment_rub)
    if data.accept_limit_rub is not None:
        card.accept_limit_rub = _q_rub(data.accept_limit_rub)
        if card.daily_limit_rub is None:
            card.daily_limit_rub = card.accept_limit_rub
    await db.flush()
    return await _card_response(db, card)


# ── Expenses ─────────────────────────────────────────────────────────────────

@router.get("/trader/expenses", response_model=list[TraderExpenseResponse])
async def list_my_expenses(
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(TraderExpense).where(TraderExpense.trader_id == user.id).order_by(TraderExpense.id.desc())
    )
    return [_expense_resp(e) for e in result.scalars().all()]


@router.post("/trader/expenses", response_model=TraderExpenseResponse, status_code=201)
async def create_my_expense(
    data: TraderExpenseCreate,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if data.card_id:
        card = await db.get(TraderCard, data.card_id)
        if not card or card.trader_id != user.id:
            raise HTTPException(404, "Card not found")
    rate = await _expense_rate(db, data.rate)
    exp = await _create_expense_row(
        db,
        trader=user,
        actor=user,
        category=_parse_category(data.category),
        amount_rub=data.amount_rub,
        rate=rate,
        card_id=data.card_id,
        requisite_id=data.requisite_id,
        comment=data.comment,
    )
    return _expense_resp(exp)


@router.get("/admin/expenses", response_model=list[TraderExpenseResponse])
async def admin_list_expenses(
    user: Annotated[User, Depends(require_role(UserRole.admin, UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
    trader_id: int | None = Query(None),
):
    q = select(TraderExpense).order_by(TraderExpense.id.desc())
    if user.role == UserRole.teamlead:
        traders = (
            await db.execute(select(User.id).where(User.teamlead_id == user.id, User.role == UserRole.trader))
        ).scalars().all()
        q = q.where(TraderExpense.trader_id.in_(list(traders) or [-1]))
    if trader_id is not None:
        await _assert_trader_access(user, trader_id, db)
        q = q.where(TraderExpense.trader_id == trader_id)
    result = await db.execute(q)
    return [_expense_resp(e) for e in result.scalars().all()]


@router.post("/admin/expenses", response_model=TraderExpenseResponse, status_code=201)
async def admin_create_expense(
    data: TraderExpenseCreate,
    user: Annotated[User, Depends(require_role(UserRole.admin, UserRole.teamlead))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not data.trader_id:
        raise HTTPException(400, "trader_id required")
    trader = await _assert_trader_access(user, data.trader_id, db)
    if data.card_id:
        card = await db.get(TraderCard, data.card_id)
        if not card or card.trader_id != trader.id:
            raise HTTPException(404, "Card not found")
    rate = await _expense_rate(db, data.rate)
    exp = await _create_expense_row(
        db,
        trader=trader,
        actor=user,
        category=_parse_category(data.category),
        amount_rub=data.amount_rub,
        rate=rate,
        card_id=data.card_id,
        requisite_id=data.requisite_id,
        comment=data.comment,
    )
    return _expense_resp(exp)


def _expense_resp(e: TraderExpense) -> TraderExpenseResponse:
    return TraderExpenseResponse(
        id=e.id,
        trader_id=e.trader_id,
        category=e.category.value,
        amount_rub=e.amount_rub,
        rate=e.rate,
        amount_usdt=e.amount_usdt,
        card_id=e.card_id,
        requisite_id=e.requisite_id,
        comment=e.comment,
        actor_id=e.actor_id,
        debited=e.debited,
        created_at=e.created_at,
    )


# ── Net / display currency ───────────────────────────────────────────────────

@router.get("/trader/net", response_model=TraderNetSummary)
async def trader_net(
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.models import TokenLedger, TokenLedgerType

    token = await token_ledger.get_active_token_for_user(db, user.id)
    commissions = Decimal("0")
    if token:
        result = await db.execute(
            select(func.coalesce(func.sum(TokenLedger.amount), 0)).where(
                TokenLedger.work_token_id == token.id,
                TokenLedger.entry_type.in_([TokenLedgerType.credit, TokenLedgerType.payout_bonus]),
            )
        )
        commissions = _q_usdt(Decimal(result.scalar() or 0))

    exp_row = await db.execute(
        select(
            func.coalesce(func.sum(TraderExpense.amount_usdt), 0),
            func.coalesce(func.sum(TraderExpense.amount_rub), 0),
        ).where(TraderExpense.trader_id == user.id)
    )
    exp_usdt, exp_rub = exp_row.one()
    exp_usdt = _q_usdt(Decimal(exp_usdt))
    exp_rub = _q_rub(Decimal(exp_rub))
    return TraderNetSummary(
        commissions_usdt=commissions,
        expenses_usdt=exp_usdt,
        expenses_rub=exp_rub,
        net_usdt=_q_usdt(commissions - exp_usdt),
        display_currency=user.display_currency or "RUB",
    )


@router.patch("/trader/settings/display-currency")
async def set_display_currency(
    data: DisplayCurrencyUpdate,
    user: Annotated[User, Depends(require_role(UserRole.trader))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user.display_currency = data.display_currency
    await db.flush()
    return {"display_currency": user.display_currency}


@router.get("/trader/expense-categories")
async def expense_categories(
    _user: Annotated[User, Depends(require_role(UserRole.trader, UserRole.admin, UserRole.teamlead))],
):
    return [{"id": c.value, "label": CATEGORY_LABELS[c]} for c in ExpenseCategory]
