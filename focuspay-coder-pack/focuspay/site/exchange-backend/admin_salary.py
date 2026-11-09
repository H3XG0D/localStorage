"""Ежедневная зарплата админ-персонала → partner_ledger (adjustment)."""
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from db import get_pool

logger = logging.getLogger("admin_salary")

MOSCOW = ZoneInfo("Europe/Moscow")


def today_moscow() -> date:
    return datetime.now(MOSCOW).date()


def _row_to_dict(row) -> dict:
    d = dict(row)
    for k in ("created_at", "updated_at", "accrual_date", "last_accrual_date"):
        v = d.get(k)
        if isinstance(v, date):
            d[k] = v.isoformat()
        elif v is not None and hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    d["daily_salary_rub"] = float(d.get("daily_salary_rub") or 0)
    d["amount_rub"] = float(d.get("amount_rub") or 0) if "amount_rub" in d else None
    d["weekly_salary_rub"] = round(float(d.get("daily_salary_rub") or 0) * 7, 2)
    return d


async def active_daily_salary_total(conn) -> float:
    val = await conn.fetchval(
        """
        SELECT COALESCE(SUM(daily_salary_rub), 0)::float
        FROM admin_salary_recipients
        WHERE is_active = TRUE
        """
    )
    return float(val or 0)


async def list_recipients(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT r.*,
               pa.username,
               pa.display_name,
               pa.promo_campaign_id AS campaign_id,
               (
                   SELECT COALESCE(SUM(pl.amount_rub), 0)::float
                   FROM partner_ledger pl
                   WHERE pl.campaign_id = pa.promo_campaign_id
               ) AS partner_balance_rub,
               (
                   SELECT MAX(a.accrual_date)
                   FROM admin_salary_accruals a
                   WHERE a.recipient_id = r.id
               ) AS last_accrual_date
        FROM admin_salary_recipients r
        JOIN partner_accounts pa ON pa.id = r.partner_account_id
        ORDER BY r.id
        """
    )
    return [_row_to_dict(r) for r in rows]


async def accrue_recipient_for_date(
    conn,
    recipient_id: int,
    accrual_date: date,
    *,
    created_by_web_user_id: int | None = None,
) -> dict | None:
    recipient = await conn.fetchrow(
        """
        SELECT r.*, pa.promo_campaign_id AS campaign_id, pa.username
        FROM admin_salary_recipients r
        JOIN partner_accounts pa ON pa.id = r.partner_account_id
        WHERE r.id = $1
        FOR UPDATE OF r
        """,
        recipient_id,
    )
    if not recipient or not recipient["is_active"]:
        return None

    exists = await conn.fetchval(
        """
        SELECT 1 FROM admin_salary_accruals
        WHERE recipient_id = $1 AND accrual_date = $2
        """,
        recipient_id,
        accrual_date,
    )
    if exists:
        return None

    amount = round(float(recipient["daily_salary_rub"]), 2)
    if amount <= 0:
        return None

    label = recipient["label"] or recipient["username"] or f"#{recipient_id}"
    note = f"Зарплата админа за {accrual_date.isoformat()} · {label}"

    ledger_id = await conn.fetchval(
        """
        INSERT INTO partner_ledger (
            campaign_id, type, amount_rub, note, created_by_web_user_id
        )
        VALUES ($1, 'adjustment', $2, $3, $4)
        RETURNING id
        """,
        recipient["campaign_id"],
        amount,
        note,
        created_by_web_user_id,
    )

    accrual = await conn.fetchrow(
        """
        INSERT INTO admin_salary_accruals (
            recipient_id, accrual_date, amount_rub, partner_ledger_id
        )
        VALUES ($1, $2, $3, $4)
        RETURNING *
        """,
        recipient_id,
        accrual_date,
        amount,
        ledger_id,
    )

    logger.info(
        "Admin salary accrual %.2f RUB recipient=%s date=%s ledger=%s",
        amount,
        recipient_id,
        accrual_date,
        ledger_id,
    )
    return _row_to_dict(accrual)


async def accrue_due_salaries(
    *,
    accrual_date: date | None = None,
    created_by_web_user_id: int | None = None,
) -> int:
    """Начислить зарплату всем активным получателям за день (идемпотентно)."""
    day = accrual_date or today_moscow()
    pool = await get_pool()
    n = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            ids = await conn.fetch(
                "SELECT id FROM admin_salary_recipients WHERE is_active = TRUE ORDER BY id"
            )
            for row in ids:
                if await accrue_recipient_for_date(
                    conn,
                    int(row["id"]),
                    day,
                    created_by_web_user_id=created_by_web_user_id,
                ):
                    n += 1
    return n


async def update_recipient_daily_salary(
    recipient_id: int,
    *,
    daily_salary_rub: float | None = None,
    is_active: bool | None = None,
) -> dict | None:
    fields = []
    values: list = []
    idx = 1
    if daily_salary_rub is not None:
        fields.append(f"daily_salary_rub = ${idx}")
        values.append(round(float(daily_salary_rub), 2))
        idx += 1
    if is_active is not None:
        fields.append(f"is_active = ${idx}")
        values.append(is_active)
        idx += 1
    if not fields:
        return None

    fields.append("updated_at = now()")
    values.append(recipient_id)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE admin_salary_recipients
            SET {", ".join(fields)}
            WHERE id = ${idx}
            RETURNING *
            """,
            *values,
        )
    return _row_to_dict(row) if row else None


async def list_accruals(conn, *, recipient_id: int | None = None, limit: int = 30) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT a.*, r.label, pa.username
        FROM admin_salary_accruals a
        JOIN admin_salary_recipients r ON r.id = a.recipient_id
        JOIN partner_accounts pa ON pa.id = r.partner_account_id
        WHERE ($1::int IS NULL OR a.recipient_id = $1)
        ORDER BY a.accrual_date DESC, a.id DESC
        LIMIT $2
        """,
        recipient_id,
        limit,
    )
    return [_row_to_dict(r) for r in rows]


async def salary_month_stats(conn, *, year: int, month: int) -> dict:
    """
    Статистика начислений админ зарплат за календарный месяц (МСК).

    Возвращает:
    - фонд (сумма месячных окладов активных получателей)
    - начислено сегодня / за месяц
    - по каждому получателю: месячная зарплата, начислено за месяц, осталось, статус
    """
    recipients = await list_recipients(conn)
    days_in_month = calendar.monthrange(year, month)[1]

    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)
    today = today_moscow()

    month_accruals_rows = await conn.fetch(
        """
        SELECT recipient_id, COALESCE(SUM(amount_rub), 0)::float AS accrued
        FROM admin_salary_accruals
        WHERE accrual_date BETWEEN $1 AND $2
        GROUP BY 1
        """,
        month_start,
        month_end,
    )
    accrued_month_by_recipient = {
        int(r["recipient_id"]): float(r["accrued"] or 0)
        for r in month_accruals_rows
    }

    accrued_today_by_recipient: dict[int, float] = {}
    if today.year == year and today.month == month:
        today_rows = await conn.fetch(
            """
            SELECT recipient_id, COALESCE(SUM(amount_rub), 0)::float AS accrued
            FROM admin_salary_accruals
            WHERE accrual_date = $1
            GROUP BY 1
            """,
            today,
        )
        accrued_today_by_recipient = {
            int(r["recipient_id"]): float(r["accrued"] or 0)
            for r in today_rows
        }

    total_fund = 0.0
    total_accrued_today = 0.0
    total_accrued_month = 0.0

    recipients_out: list[dict] = []
    for r in recipients:
        daily = float(r.get("daily_salary_rub") or 0)
        monthly = round(daily * days_in_month, 2)
        accrued_month = float(accrued_month_by_recipient.get(int(r["id"]), 0.0) or 0.0)
        accrued_today = float(accrued_today_by_recipient.get(int(r["id"]), 0.0) or 0.0)

        if r.get("is_active"):
            total_fund += monthly
            total_accrued_today += accrued_today
            total_accrued_month += accrued_month

        remaining = round(monthly - accrued_month, 2)

        if not r.get("is_active"):
            status = "Неактивен"
        elif accrued_today > 0.009:
            status = "Начислено сегодня"
        elif monthly > 0.009 and accrued_month >= monthly - 0.009:
            status = "Месяц закрыт"
        else:
            status = "Ожидает"

        recipients_out.append(
            {
                "id": int(r["id"]),
                "label": r.get("label"),
                "username": r.get("username"),
                "is_active": bool(r.get("is_active")),
                "daily_salary_rub": daily,
                "monthly_salary_rub": monthly,
                "accrued_month_rub": round(accrued_month, 2),
                "remaining_month_rub": remaining,
                "status": status,
                "last_accrual_date": r.get("last_accrual_date"),
            }
        )

    return {
        "year": year,
        "month": month,
        "totals": {
            "fund_monthly_rub": round(total_fund, 2),
            "accrued_today_rub": round(total_accrued_today, 2),
            "accrued_month_rub": round(total_accrued_month, 2),
            "remaining_rub": round(total_fund - total_accrued_month, 2),
        },
        "recipients": recipients_out,
    }
