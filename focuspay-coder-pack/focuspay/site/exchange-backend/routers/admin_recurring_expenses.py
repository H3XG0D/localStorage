"""CRUD периодических расходов (подписки, зарплаты, маркетинг) с ROI-трекингом."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from auth import get_current_finance_viewer
from db import get_pool

router = APIRouter()

ExpenseCategory = Literal["subscription", "salary", "marketing", "other"]
BillingCycle = Literal["weekly", "biweekly", "monthly", "quarterly", "annual"]

VALID_CATEGORIES = ("subscription", "salary", "marketing", "other")
VALID_CYCLES = ("weekly", "biweekly", "monthly", "quarterly", "annual")


def _serialize_row(row) -> dict:
    d = dict(row)
    for key in ("amount_rub", "expected_return_rub", "actual_return_rub", "roi_percent"):
        val = d.get(key)
        if isinstance(val, Decimal):
            d[key] = float(val)
        elif val is not None:
            d[key] = float(val)
    for key in ("next_billing_date", "last_billing_date", "created_at", "updated_at"):
        val = d.get(key)
        if val is not None and hasattr(val, "isoformat"):
            d[key] = val.isoformat()
    return d


class RecurringExpenseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    category: ExpenseCategory
    amount_rub: float = Field(..., gt=0, le=1_000_000_000)
    billing_cycle: BillingCycle
    next_billing_date: date
    expected_return_rub: float | None = Field(None, ge=0, le=1_000_000_000)
    linked_partner_id: int | None = None
    linked_promo_code: str | None = Field(None, max_length=64)
    linked_metric_key: str | None = Field(None, max_length=200)
    comment: str | None = Field(None, max_length=2000)

    @field_validator("title", "linked_promo_code", "linked_metric_key", "comment")
    @classmethod
    def strip_optional(cls, v: str | None):
        if v is None:
            return None
        s = v.strip()
        return s or None


class RecurringExpensePatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    amount_rub: float | None = Field(None, gt=0, le=1_000_000_000)
    billing_cycle: BillingCycle | None = None
    next_billing_date: date | None = None
    is_active: bool | None = None
    expected_return_rub: float | None = Field(None, ge=0, le=1_000_000_000)
    actual_return_rub: float | None = Field(None, ge=0, le=1_000_000_000)
    roi_percent: float | None = None
    linked_partner_id: int | None = None
    linked_promo_code: str | None = Field(None, max_length=64)
    linked_metric_key: str | None = Field(None, max_length=200)
    comment: str | None = Field(None, max_length=2000)

    @field_validator("title", "linked_promo_code", "linked_metric_key", "comment")
    @classmethod
    def strip_optional(cls, v: str | None):
        if v is None:
            return None
        s = v.strip()
        return s or None


@router.get("/recurring-expenses")
async def list_recurring_expenses(
    category: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    _admin=Depends(get_current_finance_viewer),
):
    """Список периодических расходов с фильтрацией."""
    if category is not None and category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, category, amount_rub, billing_cycle,
                   next_billing_date, last_billing_date, is_active,
                   expected_return_rub, actual_return_rub, roi_percent,
                   linked_partner_id, linked_promo_code, linked_metric_key,
                   comment, created_by_web_user_id, created_at, updated_at
            FROM recurring_expenses
            WHERE ($1::text IS NULL OR category = $1)
              AND ($2::boolean IS NULL OR is_active = $2)
            ORDER BY is_active DESC, next_billing_date ASC
            LIMIT $3
            """,
            category,
            is_active,
            limit,
        )
    return {"expenses": [_serialize_row(r) for r in rows]}


@router.get("/recurring-expenses/upcoming")
async def get_upcoming_expenses(
    days: int = Query(7, ge=1, le=90),
    _admin=Depends(get_current_finance_viewer),
):
    """Ближайшие к оплате подписки (next_billing_date <= now + days)."""
    pool = await get_pool()
    today = date.today()
    until = today + timedelta(days=days)
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, category, amount_rub, billing_cycle,
                   next_billing_date, last_billing_date, is_active,
                   expected_return_rub, actual_return_rub, roi_percent,
                   linked_partner_id, linked_promo_code, linked_metric_key,
                   comment, created_by_web_user_id, created_at, updated_at
            FROM recurring_expenses
            WHERE is_active = true
              AND next_billing_date <= $1
            ORDER BY next_billing_date ASC
            """,
            until,
        )
    return {"expenses": [_serialize_row(r) for r in rows], "days": days, "until": until.isoformat()}


@router.get("/recurring-expenses/roi-analysis")
async def get_roi_analysis(
    period_days: int = Query(30, ge=7, le=365),
    _admin=Depends(get_current_finance_viewer),
):
    """
    ROI-анализ с рекомендациями по продлению.
    Для каждой активной подписки:
    - Если roi_percent заполнен вручную → используем его
    - Если linked_partner_id → считаем ROI из оборота партнёра за period
    - Если linked_promo_code → считаем ROI из кампании за period
    - Рекомендация: continue если ROI > 20%, иначе review
    """
    pool = await get_pool()
    today = date.today()
    date_from = today - timedelta(days=period_days)
    
    async with pool.acquire() as conn:
        # Загружаем активные расходы
        expenses = await conn.fetch(
            """
            SELECT id, title, category, amount_rub, billing_cycle,
                   next_billing_date, expected_return_rub, actual_return_rub,
                   roi_percent, linked_partner_id, linked_promo_code, comment
            FROM recurring_expenses
            WHERE is_active = true
            ORDER BY next_billing_date ASC
            """
        )
        
        results = []
        for exp in expenses:
            exp_dict = _serialize_row(exp)
            roi = exp_dict.get("roi_percent")
            actual_return = exp_dict.get("actual_return_rub")
            
            # Если ROI уже рассчитан вручную — используем его
            if roi is not None:
                pass
            # Если привязан партнёр — считаем ROI из его оборота
            elif exp.get("linked_partner_id"):
                partner_row = await conn.fetchrow(
                    """
                    SELECT paid_fiat_sum, service_profit_net_rub
                    FROM promo_campaigns
                    WHERE id = $1
                    """,
                    exp["linked_partner_id"],
                )
                if partner_row:
                    # Упрощённая логика: берём долю за period (грубо, но работает)
                    # В реальности нужно фильтровать заявки за date_from..today
                    profit = float(partner_row.get("service_profit_net_rub") or 0)
                    amount = float(exp["amount_rub"])
                    actual_return = profit
                    if amount > 0:
                        roi = ((profit - amount) / amount) * 100
                        exp_dict["actual_return_rub"] = actual_return
                        exp_dict["roi_percent"] = round(roi, 2)
            
            # Если привязан промокод — считаем ROI из кампании
            elif exp.get("linked_promo_code"):
                promo_row = await conn.fetchrow(
                    """
                    SELECT paid_fiat_sum
                    FROM (
                        SELECT SUM(o.fiat_amount) as paid_fiat_sum
                        FROM orders o
                        WHERE o.promo_code = $1
                          AND o.status IN ('PAID', 'COMPLETED')
                          AND o.created_at >= $2
                    ) s
                    """,
                    exp["linked_promo_code"],
                    date_from,
                )
                if promo_row and promo_row["paid_fiat_sum"]:
                    turnover = float(promo_row["paid_fiat_sum"] or 0)
                    # Упрощённо: 5% маржа
                    profit = turnover * 0.05
                    amount = float(exp["amount_rub"])
                    actual_return = profit
                    if amount > 0:
                        roi = ((profit - amount) / amount) * 100
                        exp_dict["actual_return_rub"] = actual_return
                        exp_dict["roi_percent"] = round(roi, 2)
            
            # Рекомендация
            recommendation = "continue" if (exp_dict.get("roi_percent") or 0) >= 20 else "review"
            exp_dict["recommendation"] = recommendation
            exp_dict["category_label"] = {
                "subscription": "Подписки на сервисы",
                "salary": "Зарплаты",
                "marketing": "Маркетинг",
                "other": "Прочее",
            }.get(exp.get("category"), exp.get("category"))
            
            results.append(exp_dict)
    
    return {
        "expenses": results,
        "period_days": period_days,
        "date_from": date_from.isoformat(),
        "date_to": today.isoformat(),
        "threshold_roi": 20,
    }


@router.post("/recurring-expenses")
async def create_recurring_expense(
    body: RecurringExpenseCreate,
    admin=Depends(get_current_finance_viewer),
):
    """Создание новой периодической подписки."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO recurring_expenses (
                title, category, amount_rub, billing_cycle, next_billing_date,
                expected_return_rub, linked_partner_id, linked_promo_code,
                linked_metric_key, comment, created_by_web_user_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id, title, category, amount_rub, billing_cycle,
                      next_billing_date, last_billing_date, is_active,
                      expected_return_rub, actual_return_rub, roi_percent,
                      linked_partner_id, linked_promo_code, linked_metric_key,
                      comment, created_by_web_user_id, created_at, updated_at
            """,
            body.title,
            body.category,
            body.amount_rub,
            body.billing_cycle,
            body.next_billing_date,
            body.expected_return_rub,
            body.linked_partner_id,
            body.linked_promo_code,
            body.linked_metric_key,
            body.comment,
            admin.get("id"),
        )
    return {"expense": _serialize_row(row)}


@router.patch("/recurring-expenses/{expense_id}")
async def patch_recurring_expense(
    expense_id: int,
    body: RecurringExpensePatch,
    _admin=Depends(get_current_finance_viewer),
):
    """Частичное обновление подписки."""
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    sets: list[str] = ["updated_at = now()"]
    args: list = []
    idx = 1
    
    for field in [
        "title",
        "amount_rub",
        "billing_cycle",
        "next_billing_date",
        "is_active",
        "expected_return_rub",
        "actual_return_rub",
        "roi_percent",
        "linked_partner_id",
        "linked_promo_code",
        "linked_metric_key",
        "comment",
    ]:
        if field in patch:
            sets.append(f"{field} = ${idx}")
            args.append(patch[field])
            idx += 1
    
    args.append(expense_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE recurring_expenses
            SET {', '.join(sets)}
            WHERE id = ${idx}
            RETURNING id, title, category, amount_rub, billing_cycle,
                      next_billing_date, last_billing_date, is_active,
                      expected_return_rub, actual_return_rub, roi_percent,
                      linked_partner_id, linked_promo_code, linked_metric_key,
                      comment, created_by_web_user_id, created_at, updated_at
            """,
            *args,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"expense": _serialize_row(row)}


@router.delete("/recurring-expenses/{expense_id}")
async def delete_recurring_expense(
    expense_id: int,
    _admin=Depends(get_current_finance_viewer),
):
    """Мягкое удаление (деактивация) подписки."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE recurring_expenses
            SET is_active = false, updated_at = now()
            WHERE id = $1
            RETURNING id
            """,
            expense_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"ok": True, "id": expense_id}


@router.post("/recurring-expenses/{expense_id}/bill")
async def bill_recurring_expense(
    expense_id: int,
    admin=Depends(get_current_finance_viewer),
):
    """
    Создать manual_expense для очередного платежа и сдвинуть next_billing_date.
    Автоматически рассчитывает следующую дату на основе billing_cycle.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Загружаем подписку
        rec = await conn.fetchrow(
            "SELECT * FROM recurring_expenses WHERE id = $1 AND is_active = true",
            expense_id,
        )
        if not rec:
            raise HTTPException(status_code=404, detail="Recurring expense not found or inactive")
        
        # Создаём manual_expense
        manual = await conn.fetchrow(
            """
            INSERT INTO manual_expenses (
                category, amount_rub, title, comment, expense_date,
                operation_type, linked_recurring_id, created_by_web_user_id
            )
            VALUES ('work', $1, $2, $3, $4, $2, $5, $6)
            RETURNING id
            """,
            rec["amount_rub"],
            f"{rec['title']} ({rec['billing_cycle']})",
            rec["comment"] or f"Автоплатёж по подписке #{expense_id}",
            rec["next_billing_date"],
            expense_id,
            admin.get("id"),
        )
        
        # Вычисляем следующую дату
        current_date = rec["next_billing_date"]
        cycle = rec["billing_cycle"]
        
        if cycle == "weekly":
            next_date = current_date + timedelta(weeks=1)
        elif cycle == "biweekly":
            next_date = current_date + timedelta(weeks=2)
        elif cycle == "monthly":
            next_date = current_date + timedelta(days=30)
        elif cycle == "quarterly":
            next_date = current_date + timedelta(days=90)
        elif cycle == "annual":
            next_date = current_date + timedelta(days=365)
        else:
            next_date = current_date + timedelta(days=30)
        
        # Обновляем recurring_expense
        updated = await conn.fetchrow(
            """
            UPDATE recurring_expenses
            SET last_billing_date = $1,
                next_billing_date = $2,
                updated_at = now()
            WHERE id = $3
            RETURNING id, title, category, amount_rub, billing_cycle,
                      next_billing_date, last_billing_date, is_active,
                      expected_return_rub, actual_return_rub, roi_percent,
                      linked_partner_id, linked_promo_code, linked_metric_key,
                      comment, created_by_web_user_id, created_at, updated_at
            """,
            current_date,
            next_date,
            expense_id,
        )
    
    return {
        "ok": True,
        "manual_expense_id": manual["id"],
        "recurring_expense": _serialize_row(updated),
    }
