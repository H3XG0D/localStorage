"""Настройка зарплаты админа: глобальный P&L и дневные начисления персоналу."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from admin_salary import (
    accrue_due_salaries,
    accrue_recipient_for_date,
    list_accruals,
    list_recipients,
    today_moscow,
    update_recipient_daily_salary,
)
from auth import get_current_finance_viewer
from db import get_pool
from runtime_settings import (
    BUSINESS_KEY,
    _SETTING_KEYS,
    get_settings,
    invalidate_cache,
    merge_settings,
    refresh_settings,
    settings_updated_at,
)

router = APIRouter()


class PayrollSettingsPatch(BaseModel):
    admin_weekly_salary_rub: Optional[float] = Field(None, ge=0, le=1_000_000)


class SalaryRecipientPatch(BaseModel):
    daily_salary_rub: Optional[float] = Field(None, ge=0, le=100_000)
    is_active: Optional[bool] = None


@router.get("/payroll-settings")
async def get_payroll_settings(_admin=Depends(get_current_finance_viewer)):
    s = await get_settings()
    pool = await get_pool()
    async with pool.acquire() as conn:
        recipients = await list_recipients(conn)
        accruals = await list_accruals(conn, limit=14)
    daily_total = sum(r["daily_salary_rub"] for r in recipients if r.get("is_active"))
    return {
        "admin_weekly_salary_rub": float(s["admin_weekly_salary_rub"]),
        "updated_at": settings_updated_at(),
        "salary_recipients": recipients,
        "daily_salary_total_rub": round(daily_total, 2),
        "weekly_salary_total_rub": round(daily_total * 7, 2),
        "recent_accruals": accruals,
    }


@router.patch("/payroll-settings")
async def patch_payroll_settings(
    body: PayrollSettingsPatch,
    _admin=Depends(get_current_finance_viewer),
):
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")

    current = await get_settings()
    merged = {**current, **patch}
    stored = {k: merged[k] for k in _SETTING_KEYS}

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = now()
            """,
            BUSINESS_KEY,
            stored,
        )

    invalidate_cache()
    await refresh_settings(force=True)
    s = merge_settings(stored)
    return {
        "admin_weekly_salary_rub": float(s["admin_weekly_salary_rub"]),
        "updated_at": settings_updated_at(),
    }


@router.patch("/payroll/salary-recipients/{recipient_id}")
async def patch_salary_recipient(
    recipient_id: int,
    body: SalaryRecipientPatch,
    _admin=Depends(get_current_finance_viewer),
):
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")
    row = await update_recipient_daily_salary(recipient_id, **patch)
    if not row:
        raise HTTPException(status_code=404, detail="Recipient not found")
    pool = await get_pool()
    async with pool.acquire() as conn:
        recipients = await list_recipients(conn)
    match = next((r for r in recipients if r["id"] == recipient_id), row)
    return {"recipient": match}


@router.post("/payroll/salary-accrue")
async def accrue_salaries_now(
    recipient_id: Optional[int] = Query(None),
    _admin=Depends(get_current_finance_viewer),
):
    day = today_moscow()
    if recipient_id is not None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                created = await accrue_recipient_for_date(
                    conn, recipient_id, day, created_by_web_user_id=_admin.get("id")
                )
        if not created:
            raise HTTPException(
                status_code=409,
                detail="Already accrued for today or recipient inactive",
            )
        return {"ok": True, "accrual_date": day.isoformat(), "count": 1}

    count = await accrue_due_salaries(
        accrual_date=day,
        created_by_web_user_id=_admin.get("id"),
    )
    return {"ok": True, "accrual_date": day.isoformat(), "count": count}
