"""CRUD ручных расходов админки (обязательные / рабочие / непредвиденные)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from auth import get_current_finance_viewer
from db import get_pool

router = APIRouter()

ExpenseCategory = Literal["mandatory", "work", "unexpected"]
VALID_CATEGORIES = ("mandatory", "work", "unexpected")


def _serialize_row(row) -> dict:
    d = dict(row)
    amount = d.get("amount_rub")
    if isinstance(amount, Decimal):
        d["amount_rub"] = float(amount)
    elif amount is not None:
        d["amount_rub"] = float(amount)
    for key in ("expense_date", "created_at", "updated_at"):
        val = d.get(key)
        if val is not None and hasattr(val, "isoformat"):
            d[key] = val.isoformat()
    return d


class ExpenseCreate(BaseModel):
    category: ExpenseCategory
    amount_rub: float = Field(..., gt=0, le=1_000_000_000)
    title: str | None = Field(None, min_length=1, max_length=500)
    # Backward-compat alias (старый UI называл поле "operation_type")
    operation_type: str | None = Field(None, min_length=1, max_length=500)
    comment: str | None = Field(None, max_length=2000)
    expense_date: date | None = None

    @field_validator("title", "operation_type", "comment")
    @classmethod
    def strip_optional(cls, v: str | None):
        if v is None:
            return None
        s = v.strip()
        return s or None


class ExpensePatch(BaseModel):
    amount_rub: Optional[float] = Field(None, gt=0, le=1_000_000_000)
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    # Backward-compat alias
    operation_type: Optional[str] = Field(None, min_length=1, max_length=500)
    comment: Optional[str] = Field(None, max_length=2000)
    expense_date: Optional[date] = None

    @field_validator("title", "operation_type", "comment")
    @classmethod
    def strip_optional(cls, v: str | None):
        if v is None:
            return None
        s = v.strip()
        return s or None


@router.get("/manual-expenses")
async def list_manual_expenses(
    category: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    _admin=Depends(get_current_finance_viewer),
):
    if category is not None and category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, category, amount_rub,
                   title, comment, expense_date,
                   operation_type,
                   created_by_web_user_id, created_at, updated_at
            FROM manual_expenses
            WHERE ($1::text IS NULL OR category = $1)
            ORDER BY expense_date DESC, created_at DESC
            LIMIT $2
            """,
            category,
            limit,
        )
    return {"expenses": [_serialize_row(r) for r in rows]}


@router.post("/manual-expenses")
async def create_manual_expense(
    body: ExpenseCreate,
    admin=Depends(get_current_finance_viewer),
):
    pool = await get_pool()
    title = body.title or body.operation_type
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    comment = body.comment or ""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO manual_expenses (
                category,
                amount_rub,
                title,
                comment,
                expense_date,
                operation_type,
                created_by_web_user_id
            )
            VALUES ($1, $2, $3, $4, COALESCE($5, CURRENT_DATE), $3, $6)
            RETURNING id, category, amount_rub,
                      title, comment, expense_date,
                      operation_type,
                      created_by_web_user_id, created_at, updated_at
            """,
            body.category,
            body.amount_rub,
            title,
            comment,
            body.expense_date,
            admin.get("id"),
        )

    # Security alert для крупных расходов (>10k RUB)
    if body.amount_rub > 10_000:
        try:
            import logging
            import html as html_mod
            from runtime_settings import reports_telegram_group_id
            from telegram_notify import send_admin_message

            logger = logging.getLogger("admin_expenses")
            reports_group = await reports_telegram_group_id()
            if reports_group:
                admin_name = html_mod.escape(str(admin.get("username") or admin.get("display_name") or admin.get("id") or ""))
                alert_text = (
                    f"⚠️ <b>Крупный расход</b>\n"
                    f"Админ: {admin_name}\n"
                    f"Категория: {body.category}\n"
                    f"Сумма: <b>{body.amount_rub:,.0f} ₽</b>\n"
                    f"Название: {html_mod.escape(title)}"
                )
                await send_admin_message(alert_text, chat_id=int(reports_group))
        except Exception as e:
            logger.exception("expense security alert failed: %s", e)

    return {"expense": _serialize_row(row)}


@router.patch("/manual-expenses/{expense_id}")
async def patch_manual_expense(
    expense_id: int,
    body: ExpensePatch,
    _admin=Depends(get_current_finance_viewer),
):
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")

    sets: list[str] = ["updated_at = now()"]
    args: list = []
    idx = 1

    if "amount_rub" in patch:
        sets.append(f"amount_rub = ${idx}")
        args.append(patch["amount_rub"])
        idx += 1

    resolved_title = patch.get("title") if "title" in patch else patch.get("operation_type")
    if resolved_title is not None:
        sets.append(f"title = ${idx}")
        args.append(resolved_title)
        idx += 1
        # Alias для совместимости со старым UI
        sets.append(f"operation_type = ${idx - 1}")

    if "comment" in patch:
        comment = patch["comment"] or ""
        sets.append(f"comment = ${idx}")
        args.append(comment)
        idx += 1

    if "expense_date" in patch:
        sets.append(f"expense_date = ${idx}")
        args.append(patch["expense_date"])
        idx += 1

    args.append(expense_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE manual_expenses
            SET {', '.join(sets)}
            WHERE id = ${idx}
            RETURNING id, category, amount_rub,
                      title, comment, expense_date,
                      operation_type,
                      created_by_web_user_id, created_at, updated_at
            """,
            *args,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"expense": _serialize_row(row)}


@router.delete("/manual-expenses/{expense_id}")
async def delete_manual_expense(
    expense_id: int,
    _admin=Depends(get_current_finance_viewer),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM manual_expenses WHERE id = $1 RETURNING id",
            expense_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"ok": True, "id": expense_id}
