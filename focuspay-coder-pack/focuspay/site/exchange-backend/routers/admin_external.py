"""Внештатные обмены: CRUD внештатников, ввод сделок, вывод баланса.

Гейты доступа:
  - Список / создание / редактирование внештатников — get_current_admin
  - Балансы, сделки, история — get_current_admin
  - Выплаты / подтверждение / отклонение — get_current_finance_viewer
"""
from __future__ import annotations

import secrets
from datetime import date, datetime

from admin_salary import today_moscow
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from auth import (
    get_current_admin,
    get_current_finance_viewer,
    hash_password,
    validate_username,
)
from config import settings
from db import get_pool
from receipt_serve import receipt_file_response
from external_exchange_calc import calc_payout_with_crypto, preview_deal, preview_payout
from external_exchange_service import create_external_deal, resolve_exchanger_markup, search_exchangers
from external_exchange_payout import (
    complete_pending_payout,
    min_payout_gross_usd,
    update_pending_payout_fee,
    withdraw_fee_usd,
    withdraw_fees_map,
)
from external_exchanger_accounts import (
    CLERK_ROLE,
    account_fields,
    account_public_dict,
    account_role,
    create_exchanger_account,
    credentials_response,
    fetch_account_by_exchanger_id,
    fetch_account_of_exchanger,
    fetch_accounts_for_exchanger,
    reset_account_password,
)
from external_exchange_stats import (
    fetch_exchanger_period_daily,
    fetch_exchanger_period_stats,
    fetch_exchanger_stats,
    fetch_global_summary,
    fetch_history,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(r) -> dict:
    """asyncpg Record → dict с сериализованными датами."""
    d = dict(r)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


async def _get_exchanger_or_404(conn, exchanger_id: int) -> dict:
    row = await conn.fetchrow(
        "SELECT * FROM external_exchangers WHERE id = $1",
        exchanger_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Внештатник не найден")
    return _row(row)


async def _balance(conn, exchanger_id: int) -> float:
    stats = await fetch_exchanger_stats(conn, exchanger_id)
    return float(stats["balance_usd"])


def _attach_stats(ex: dict, stats: dict) -> dict:
    ex["stats"] = stats
    ex["balance_usd"] = stats["balance_usd"]
    ex["deal_count"] = stats["deal_count"]
    ex["conversion_pct"] = stats.get("conversion_pct")
    ex["deals_confirmed"] = stats.get("deals_confirmed", stats.get("deal_count", 0))
    ex["deals_failed"] = stats.get("deals_failed", 0)
    ex["deals_awaiting"] = stats.get("deals_awaiting", 0)
    ex["deals_pending"] = stats.get("deals_pending", 0)
    ex["deals_cancelled"] = stats.get("deals_cancelled", 0)
    ex["deals_open"] = stats.get("deals_open", 0)
    ex["house_profit"] = {
        "deal_profit_usd": stats["deal_profit_usd"],
        "payout_fee_usd": stats["payout_fee_usd"],
        "total_profit_usd": stats["house_profit_usd"],
    }
    markup = resolve_exchanger_markup(ex)
    ex["effective_markup_pct"] = float(markup["markup_pct"])
    ex["effective_markup_mode"] = str(markup["markup_mode"])
    return ex


async def _attach_account(conn, ex: dict) -> dict:
    account = await fetch_account_by_exchanger_id(conn, int(ex["id"]))
    ex.update(account_fields(account))
    return ex


def _append_date_filters(
    where: str,
    params: list,
    *,
    column: str = "created_at",
    date_from: date | None = None,
    date_to: date | None = None,
) -> str:
    if date_from:
        where += f" AND {column}::date >= ${len(params) + 1}"
        params.append(date_from)
    if date_to:
        where += f" AND {column}::date <= ${len(params) + 1}"
        params.append(date_to)
    return where


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ExchangerCreate(BaseModel):
    name: str
    contact: Optional[str] = None
    net_percent: float = 0.0
    markup_pct: Optional[float] = None
    markup_mode: Optional[Literal["on_deal", "on_turnover"]] = None
    note: Optional[str] = None
    cabinet_username: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name is required")
        return v

    @field_validator("cabinet_username")
    @classmethod
    def _cabinet_username(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        return validate_username(v)

    @field_validator("net_percent")
    @classmethod
    def _percent_range(cls, v: float) -> float:
        if not (0 <= v <= 100):
            raise ValueError("net_percent must be 0..100")
        return v

    @field_validator("markup_pct")
    @classmethod
    def _markup_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0 <= v <= 100):
            raise ValueError("markup_pct must be 0..100")
        return v

    @field_validator("markup_mode")
    @classmethod
    def _markup_mode_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("on_deal", "on_turnover"):
            raise ValueError("markup_mode must be on_deal or on_turnover")
        return v


class ExchangerUpdate(BaseModel):
    name: Optional[str] = None
    contact: Optional[str] = None
    net_percent: Optional[float] = None
    markup_pct: Optional[float] = None
    markup_mode: Optional[Literal["on_deal", "on_turnover"]] = None
    note: Optional[str] = None
    is_active: Optional[bool] = None
    is_trusted_client: Optional[bool] = None
    auto_credit_on_payfast: Optional[bool] = None

    @field_validator("net_percent")
    @classmethod
    def _percent_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0 <= v <= 100):
            raise ValueError("net_percent must be 0..100")
        return v

    @field_validator("markup_pct")
    @classmethod
    def _markup_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0 <= v <= 100):
            raise ValueError("markup_pct must be 0..100")
        return v

    @field_validator("markup_mode")
    @classmethod
    def _markup_mode_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("on_deal", "on_turnover"):
            raise ValueError("markup_mode must be on_deal or on_turnover")
        return v


class DealCreate(BaseModel):
    amount_rub: float
    crypto: str = "usdt"
    note: Optional[str] = None
    client_is_new: bool = True

    @field_validator("amount_rub")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("amount_rub must be > 0")
        return v

    @field_validator("crypto")
    @classmethod
    def _valid_crypto(cls, v: str) -> str:
        if v not in ("btc", "usdt", "trx", "ltc"):
            raise ValueError("crypto must be btc/usdt/trx/ltc")
        return v


class IssueCredentialsBody(BaseModel):
    username: str

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return validate_username(v)


class ClerkCredentialsBody(BaseModel):
    """Кассирский логин магазина: реквизиты и чеки, без выводов."""

    username: str
    label: Optional[str] = None

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return validate_username(v)


class AccountPatchBody(BaseModel):
    is_active: Optional[bool] = None
    label: Optional[str] = None


class PayoutCreate(BaseModel):
    gross_usd: float
    crypto: str = "usdt"
    fee_usd: Optional[float] = None
    tx_hash: Optional[str] = None
    note: Optional[str] = None

    @field_validator("gross_usd")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("gross_usd must be > 0")
        return v

    @field_validator("fee_usd")
    @classmethod
    def _fee_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("fee_usd must be >= 0")
        return v

    @field_validator("crypto")
    @classmethod
    def _valid_crypto(cls, v: str) -> str:
        if v not in ("btc", "usdt", "trx", "ltc"):
            raise ValueError("crypto must be btc/usdt/trx/ltc")
        return v


# ---------------------------------------------------------------------------
# GET /api/admin/external/exchangers
# ---------------------------------------------------------------------------

@router.get("/external/exchangers")
async def list_exchangers(
    include_inactive: bool = False,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        where = "" if include_inactive else "WHERE is_active = TRUE"
        rows = await conn.fetch(
            f"SELECT * FROM external_exchangers {where} ORDER BY created_at DESC"
        )
        result = []
        for row in rows:
            ex = _row(row)
            stats = await fetch_exchanger_stats(conn, int(row["id"]))
            ex = _attach_stats(ex, stats)
            ex = await _attach_account(conn, ex)
            result.append(ex)
    return {"exchangers": result}


# ---------------------------------------------------------------------------
# GET /api/admin/external/summary
# ---------------------------------------------------------------------------

@router.get("/external/summary")
async def external_summary(
    include_inactive: bool = False,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        summary = await fetch_global_summary(conn, active_only=not include_inactive)
    return summary


# ---------------------------------------------------------------------------
# POST /api/admin/external/exchangers
# ---------------------------------------------------------------------------

@router.post("/external/exchangers", status_code=201)
async def create_exchanger(
    body: ExchangerCreate,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO external_exchangers (name, contact, net_percent, note, markup_pct, markup_mode)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
                """,
                body.name,
                body.contact,
                body.net_percent,
                body.note,
                body.markup_pct,
                body.markup_mode or settings.ext_markup_mode,
            )
            ex = _row(row)
            exchanger_id = int(row["id"])
            credentials = None
            if body.cabinet_username:
                try:
                    password_plain, _account = await create_exchanger_account(
                        conn, exchanger_id, body.cabinet_username
                    )
                    credentials = credentials_response(body.cabinet_username, password_plain)
                except ValueError as e:
                    code = str(e)
                    if code == "username_taken":
                        raise HTTPException(status_code=400, detail="Логин уже занят") from e
                    raise HTTPException(status_code=400, detail=str(e)) from e
            stats = await fetch_exchanger_stats(conn, exchanger_id)
            ex = _attach_stats(ex, stats)
            ex = await _attach_account(conn, ex)
    if credentials:
        ex.update(credentials)
    return ex


# ---------------------------------------------------------------------------
# GET /api/admin/external/exchangers/{id}
# ---------------------------------------------------------------------------

@router.get("/external/exchangers/{exchanger_id}")
async def get_exchanger(
    exchanger_id: int,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        ex = await _get_exchanger_or_404(conn, exchanger_id)
        stats = await fetch_exchanger_stats(conn, exchanger_id)
        ex = _attach_stats(ex, stats)
        ex = await _attach_account(conn, ex)
        ex["payout_count"] = stats["payout_count"]
    return ex


@router.get("/external/exchangers/{exchanger_id}/stats")
async def exchanger_period_stats(
    exchanger_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    admin=Depends(get_current_admin),
):
    today = today_moscow()
    d_from = date_from or today.replace(day=1)
    d_to = date_to or today
    if d_to < d_from:
        raise HTTPException(status_code=400, detail="date_to must be >= date_from")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _get_exchanger_or_404(conn, exchanger_id)
        lifetime = await fetch_exchanger_stats(conn, exchanger_id)
        period = await fetch_exchanger_period_stats(conn, exchanger_id, d_from, d_to)
        daily = await fetch_exchanger_period_daily(conn, exchanger_id, d_from, d_to)
    period["balance_usd"] = lifetime["balance_usd"]
    return {
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "lifetime": lifetime,
        "period": period,
        "daily": daily,
    }


# ---------------------------------------------------------------------------
# PATCH /api/admin/external/exchangers/{id}
# ---------------------------------------------------------------------------

@router.patch("/external/exchangers/{exchanger_id}")
async def update_exchanger(
    exchanger_id: int,
    body: ExchangerUpdate,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        ex = await _get_exchanger_or_404(conn, exchanger_id)

        updates: list[str] = []
        values: list = []
        idx = 1

        def add(col: str, val):
            nonlocal idx
            updates.append(f"{col} = ${idx}")
            values.append(val)
            idx += 1

        if body.name is not None:
            add("name", body.name.strip())
        if body.contact is not None:
            add("contact", body.contact)
        if body.net_percent is not None:
            add("net_percent", body.net_percent)
        if "markup_pct" in body.model_fields_set:
            add("markup_pct", body.markup_pct)
        if "markup_mode" in body.model_fields_set:
            add("markup_mode", body.markup_mode or "on_deal")
        if body.note is not None:
            add("note", body.note)
        if body.is_active is not None:
            add("is_active", body.is_active)

        new_trusted = (
            bool(body.is_trusted_client)
            if "is_trusted_client" in body.model_fields_set
            else bool(ex.get("is_trusted_client"))
        )
        if "is_trusted_client" in body.model_fields_set:
            add("is_trusted_client", new_trusted)

        if "auto_credit_on_payfast" in body.model_fields_set:
            want_auto = bool(body.auto_credit_on_payfast)
            if want_auto and not new_trusted:
                raise HTTPException(
                    status_code=400,
                    detail="Автоначисление доступно только для доверенных внештатников",
                )
            add("auto_credit_on_payfast", want_auto)
        elif "is_trusted_client" in body.model_fields_set and not new_trusted:
            add("auto_credit_on_payfast", False)

        if not updates:
            return _row(await conn.fetchrow("SELECT * FROM external_exchangers WHERE id = $1", exchanger_id))

        values.append(exchanger_id)
        row = await conn.fetchrow(
            f"UPDATE external_exchangers SET {', '.join(updates)} WHERE id = ${idx} RETURNING *",
            *values,
        )
    return _row(row)


@router.post("/external/exchangers/{exchanger_id}/issue-credentials")
async def issue_exchanger_credentials(
    exchanger_id: int,
    body: IssueCredentialsBody,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _get_exchanger_or_404(conn, exchanger_id)
        try:
            password_plain, account = await create_exchanger_account(
                conn, exchanger_id, body.username
            )
        except ValueError as e:
            code = str(e)
            if code == "access_already_issued":
                raise HTTPException(status_code=400, detail="Доступ уже выдан") from e
            if code == "username_taken":
                raise HTTPException(status_code=400, detail="Логин уже занят") from e
            raise HTTPException(status_code=400, detail=str(e)) from e
    return credentials_response(account["username"], password_plain)


@router.post("/external/exchangers/{exchanger_id}/reset-password")
async def reset_exchanger_password(
    exchanger_id: int,
    admin=Depends(get_current_admin),
):
    password_plain = secrets.token_urlsafe(10)
    pool = await get_pool()
    async with pool.acquire() as conn:
        account = await fetch_account_by_exchanger_id(conn, exchanger_id)
        if not account:
            raise HTTPException(
                status_code=404,
                detail="Доступ не выдан — сначала выдайте доступ в кабинет",
            )
        await conn.execute(
            "UPDATE external_exchanger_accounts SET password_hash = $1 WHERE id = $2",
            hash_password(password_plain),
            account["id"],
        )
    return credentials_response(account["username"], password_plain)


# ---------------------------------------------------------------------------
# Логины магазина: хозяин + кассиры
# ---------------------------------------------------------------------------

@router.get("/external/exchangers/{exchanger_id}/accounts")
async def list_exchanger_accounts(
    exchanger_id: int,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _get_exchanger_or_404(conn, exchanger_id)
        rows = await fetch_accounts_for_exchanger(conn, exchanger_id)
    return {"items": [account_public_dict(row) for row in rows]}


@router.post("/external/exchangers/{exchanger_id}/accounts", status_code=201)
async def create_exchanger_clerk(
    exchanger_id: int,
    body: ClerkCredentialsBody,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _get_exchanger_or_404(conn, exchanger_id)
        try:
            password_plain, account = await create_exchanger_account(
                conn,
                exchanger_id,
                body.username,
                role=CLERK_ROLE,
                label=body.label,
            )
        except ValueError as e:
            if str(e) == "username_taken":
                raise HTTPException(status_code=400, detail="Логин уже занят") from e
            raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "account": account_public_dict(account),
        "credentials": credentials_response(
            account["username"], password_plain, role=CLERK_ROLE
        ),
    }


@router.post("/external/exchangers/{exchanger_id}/accounts/{account_id}/reset-password")
async def reset_exchanger_account_password(
    exchanger_id: int,
    account_id: int,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        account = await fetch_account_of_exchanger(conn, account_id, exchanger_id)
        if not account:
            raise HTTPException(status_code=404, detail="Логин не найден")
        password_plain = await reset_account_password(conn, account_id)
    return credentials_response(
        account["username"], password_plain, role=account_role(account)
    )


@router.patch("/external/exchangers/{exchanger_id}/accounts/{account_id}")
async def patch_exchanger_account(
    exchanger_id: int,
    account_id: int,
    body: AccountPatchBody,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        account = await fetch_account_of_exchanger(conn, account_id, exchanger_id)
        if not account:
            raise HTTPException(status_code=404, detail="Логин не найден")
        if body.is_active is not None:
            await conn.execute(
                "UPDATE external_exchanger_accounts SET is_active = $1 WHERE id = $2",
                bool(body.is_active),
                account_id,
            )
        if body.label is not None:
            await conn.execute(
                "UPDATE external_exchanger_accounts SET label = $1 WHERE id = $2",
                body.label.strip() or None,
                account_id,
            )
        row = await fetch_account_of_exchanger(conn, account_id, exchanger_id)
    return {"account": account_public_dict(row)}


@router.get("/external/exchangers/{exchanger_id}/api-keys")
async def admin_exchanger_api_keys_get(
    exchanger_id: int,
    admin=Depends(get_current_admin),
):
    from exchanger_api_keys import list_key_for_exchanger

    pool = await get_pool()
    async with pool.acquire() as conn:
        await _get_exchanger_or_404(conn, exchanger_id)
        key = await list_key_for_exchanger(conn, exchanger_id)
    return {"key": key}


@router.post("/external/exchangers/{exchanger_id}/api-keys")
async def admin_exchanger_api_keys_issue(
    exchanger_id: int,
    admin=Depends(get_current_admin),
):
    from exchanger_api_keys import issue_key_for_exchanger

    pool = await get_pool()
    async with pool.acquire() as conn:
        await _get_exchanger_or_404(conn, exchanger_id)
        issued = await issue_key_for_exchanger(conn, exchanger_id)
    return issued


@router.post("/external/exchangers/{exchanger_id}/api-keys/revoke")
async def admin_exchanger_api_keys_revoke(
    exchanger_id: int,
    admin=Depends(get_current_admin),
):
    from exchanger_api_keys import revoke_key_for_exchanger

    pool = await get_pool()
    async with pool.acquire() as conn:
        await _get_exchanger_or_404(conn, exchanger_id)
        return await revoke_key_for_exchanger(conn, exchanger_id)


# ---------------------------------------------------------------------------
# POST /api/admin/external/exchangers/{id}/deals  — ввод сделки
# ---------------------------------------------------------------------------

@router.post("/external/exchangers/{exchanger_id}/deals", status_code=201)
async def create_deal(
    exchanger_id: int,
    body: DealCreate,
    admin=Depends(get_current_admin),
):
    created_by = str(admin.get("username") or admin.get("id") or "admin")
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            result = await create_external_deal(
                conn,
                exchanger_id=exchanger_id,
                amount_rub=body.amount_rub,
                crypto=body.crypto,
                note=body.note,
                created_by=created_by,
                client_is_new=body.client_is_new,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
    return result


# ---------------------------------------------------------------------------
# GET /api/admin/external/exchangers/{id}/deals
# ---------------------------------------------------------------------------

@router.get("/external/exchangers/{exchanger_id}/deals")
async def list_deals(
    exchanger_id: int,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _get_exchanger_or_404(conn, exchanger_id)
        allowed_statuses = {"awaiting_receipt", "pending", "confirmed", "cancelled", "open"}
        status_filter = status.strip().lower() if status else None
        if status_filter and status_filter not in allowed_statuses:
            raise HTTPException(status_code=400, detail="status must be awaiting_receipt/pending/confirmed/cancelled/open")
        where = "WHERE exchanger_id = $1"
        params: list = [exchanger_id]
        if status_filter == "open":
            where += " AND status IN ('awaiting_receipt', 'pending')"
        elif status_filter:
            where += f" AND status = ${len(params) + 1}"
            params.append(status_filter)
        where = _append_date_filters(where, params, date_from=date_from, date_to=date_to)
        params.extend([limit, offset])
        rows = await conn.fetch(
            f"""
            SELECT * FROM external_deals
            {where}
            ORDER BY created_at DESC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}
            """,
            *params,
        )
        deals = []
        for r in rows:
            d = _row(r)
            d["has_receipt"] = bool(r.get("receipt_file"))
            deals.append(d)
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM external_deals {where}",
            *params[:-2],
        )
    return {
        "deals": deals,
        "total": int(total or 0),
    }


@router.get("/external/deals/{deal_id}")
async def get_deal(
    deal_id: int,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT d.*, e.name AS exchanger_name
            FROM external_deals d
            JOIN external_exchangers e ON e.id = d.exchanger_id
            WHERE d.id = $1
            """,
            deal_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Сделка не найдена")
        deal = _row(row)
        deal["has_receipt"] = bool(row.get("receipt_file"))
    return deal


@router.get("/external/deals/{deal_id}/receipt")
async def get_deal_receipt(
    deal_id: int,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        receipt_file = await conn.fetchval(
            "SELECT receipt_file FROM external_deals WHERE id = $1",
            deal_id,
        )
    return receipt_file_response(receipt_file)


# ---------------------------------------------------------------------------
# GET /api/admin/external/exchangers/{id}/ledger
# ---------------------------------------------------------------------------

@router.get("/external/exchangers/{exchanger_id}/ledger")
async def get_ledger(
    exchanger_id: int,
    limit: int = 50,
    offset: int = 0,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _get_exchanger_or_404(conn, exchanger_id)
        where = "WHERE exchanger_id = $1"
        params: list = [exchanger_id]
        where = _append_date_filters(where, params, date_from=date_from, date_to=date_to)
        count_params = list(params)
        params.extend([limit, offset])
        rows = await conn.fetch(
            f"""
            SELECT * FROM external_ledger
            {where}
            ORDER BY created_at DESC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}
            """,
            *params,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM external_ledger {where}",
            *count_params,
        )
        balance = await _balance(conn, exchanger_id)
    return {
        "entries": [_row(r) for r in rows],
        "balance_usd": balance,
        "total": int(total or 0),
    }


# ---------------------------------------------------------------------------
# GET /api/admin/external/exchangers/{id}/history
# ---------------------------------------------------------------------------

@router.get("/external/exchangers/{exchanger_id}/history")
async def get_history(
    exchanger_id: int,
    limit: int = 50,
    offset: int = 0,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _get_exchanger_or_404(conn, exchanger_id)
        items, total = await fetch_history(
            conn,
            exchanger_id,
            limit=limit,
            offset=offset,
            date_from=date_from,
            date_to=date_to,
        )
    return {"items": items, "total": total}


# ---------------------------------------------------------------------------
# POST /api/admin/external/exchangers/{id}/payouts  — вывод (фин. доступ)
# ---------------------------------------------------------------------------

@router.post("/external/exchangers/{exchanger_id}/payouts", status_code=201)
async def create_payout(
    exchanger_id: int,
    body: PayoutCreate,
    admin=Depends(get_current_finance_viewer),
):
    from routers.public import get_exchanger_rates_cached

    pool = await get_pool()
    async with pool.acquire() as conn:
        ex = await _get_exchanger_or_404(conn, exchanger_id)

        balance = await _balance(conn, exchanger_id)

        if body.gross_usd > balance + 0.000001:
            raise HTTPException(
                status_code=400,
                detail=f"Недостаточно баланса: ${balance:.2f}, запрошено ${body.gross_usd:.2f}",
            )

        rates = await get_exchanger_rates_cached()
        usdt_rate_rub = float(rates.get("usdt") or 0)
        if usdt_rate_rub <= 0:
            raise HTTPException(status_code=503, detail="Курс недоступен")

        fee_usd = (
            float(body.fee_usd)
            if body.fee_usd is not None
            else float(withdraw_fee_usd(body.crypto))
        )
        try:
            pc = calc_payout_with_crypto(
                body.gross_usd,
                fee_usd=fee_usd,
                crypto=body.crypto,
                market_rub=rates,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        created_by = str(admin.get("username") or admin.get("id") or "admin")

        async with conn.transaction():
            payout_row = await conn.fetchrow(
                """
                INSERT INTO external_payouts (
                    exchanger_id, gross_usd, fee_usd, net_usd,
                    crypto, crypto_amount, crypto_rate_usd,
                    tx_hash, status, note, created_by
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'paid',$9,$10)
                RETURNING *
                """,
                exchanger_id,
                pc.gross_usd,
                pc.fee_usd,
                pc.net_usd,
                body.crypto,
                pc.crypto_amount,
                pc.crypto_rate_usd,
                body.tx_hash,
                body.note,
                created_by,
            )
            payout_id = int(payout_row["id"])

            await conn.execute(
                """
                INSERT INTO external_ledger (exchanger_id, type, amount_usd, payout_id, note)
                VALUES ($1, 'payout', $2, $3, $4)
                """,
                exchanger_id,
                -abs(pc.gross_usd),
                payout_id,
                f"Вывод: ${pc.net_usd:.2f} на руки, комиссия ${pc.fee_usd:.2f}",
            )

    return _row(payout_row)


# ---------------------------------------------------------------------------
# GET /api/admin/external/exchangers/{id}/payouts
# ---------------------------------------------------------------------------

@router.get("/external/exchangers/{exchanger_id}/payouts")
async def list_payouts(
    exchanger_id: int,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _get_exchanger_or_404(conn, exchanger_id)
        allowed = {"paid", "pending", "rejected", "canceled", "cancelled"}
        status_filter = status.strip().lower() if status else None
        if status_filter == "cancelled":
            status_filter = "canceled"
        if status_filter and status_filter not in allowed:
            raise HTTPException(status_code=400, detail="status must be paid/pending/rejected/canceled")
        where = "WHERE exchanger_id = $1"
        params: list = [exchanger_id]
        if status_filter:
            where += f" AND status = ${len(params) + 1}"
            params.append(status_filter)
        where = _append_date_filters(where, params, date_from=date_from, date_to=date_to)
        count_params = list(params)
        params.extend([limit, offset])
        rows = await conn.fetch(
            f"""
            SELECT * FROM external_payouts
            {where}
            ORDER BY created_at DESC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}
            """,
            *params,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM external_payouts {where}",
            *count_params,
        )
    return {
        "payouts": [_row(r) for r in rows],
        "total": int(total or 0),
    }


class PayoutCompleteBody(BaseModel):
    tx_hash: Optional[str] = None
    fee_usd: Optional[float] = None

    @field_validator("fee_usd")
    @classmethod
    def _fee_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("fee_usd must be >= 0")
        return v


class PayoutRejectBody(BaseModel):
    reason: Optional[str] = None


class PayoutFeeUpdateBody(BaseModel):
    fee_usd: float

    @field_validator("fee_usd")
    @classmethod
    def _fee_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("fee_usd must be >= 0")
        return v


@router.get("/external/payouts/pending")
async def list_pending_payouts(
    limit: int = 100,
    offset: int = 0,
    admin=Depends(get_current_finance_viewer),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              p.*,
              e.name AS exchanger_name,
              a.username AS exchanger_username
            FROM external_payouts p
            JOIN external_exchangers e ON e.id = p.exchanger_id
            LEFT JOIN external_exchanger_accounts a ON a.external_exchanger_id = p.exchanger_id
            WHERE p.status = 'pending'
            ORDER BY p.created_at ASC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM external_payouts WHERE status = 'pending'"
        )
    return {
        "items": [_row(r) for r in rows],
        "total": int(total or 0),
    }


@router.patch("/external/payouts/{payout_id}/fee")
async def update_exchanger_payout_fee(
    payout_id: int,
    body: PayoutFeeUpdateBody,
    admin=Depends(get_current_finance_viewer),
):
    """Изменить комиссию вывода у pending-заявки (пересчёт net/crypto)."""
    from routers.public import get_exchanger_rates_cached

    rates = await get_exchanger_rates_cached()
    if float(rates.get("usdt") or 0) <= 0:
        raise HTTPException(status_code=503, detail="Курс недоступен")

    updated_by = str(admin.get("username") or admin.get("id") or "admin")
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await update_pending_payout_fee(
            conn,
            payout_id,
            fee_usd=body.fee_usd,
            market_rub=rates,
            updated_by=updated_by,
        )


@router.post("/external/payouts/{payout_id}/complete")
async def complete_exchanger_payout(
    payout_id: int,
    body: PayoutCompleteBody,
    admin=Depends(get_current_finance_viewer),
):
    """Подтвердить заявку на вывод из кабинета (pending → paid + списание с баланса)."""
    from routers.public import get_exchanger_rates_cached

    completed_by = str(admin.get("username") or admin.get("id") or "admin")
    rates = None
    if body.fee_usd is not None:
        rates = await get_exchanger_rates_cached()
        if float(rates.get("usdt") or 0) <= 0:
            raise HTTPException(status_code=503, detail="Курс недоступен")
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await complete_pending_payout(
            conn,
            payout_id,
            tx_hash=body.tx_hash,
            completed_by=completed_by,
            fee_usd=body.fee_usd,
            market_rub=rates,
        )
    return result


@router.post("/external/payouts/{payout_id}/reject")
async def reject_exchanger_payout(
    payout_id: int,
    body: PayoutRejectBody,
    admin=Depends(get_current_finance_viewer),
):
    rejected_by = str(admin.get("username") or admin.get("id") or "admin")
    reason = (body.reason or "").strip()
    suffix = f" · reason: {reason}" if reason else ""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE external_payouts
            SET status = 'rejected',
                note = CONCAT(COALESCE(note, ''), CASE WHEN COALESCE(note, '') = '' THEN '' ELSE ' ' END, '[rejected by ', $2, $3, ']')
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            payout_id,
            rejected_by,
            suffix,
        )
        if not row:
            exists = await conn.fetchval(
                "SELECT 1 FROM external_payouts WHERE id = $1",
                payout_id,
            )
            if not exists:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            raise HTTPException(status_code=400, detail="Заявка уже обработана")
    return _row(row)


# ---------------------------------------------------------------------------
# GET /api/admin/external/preview-deal  — расчёт превью без записи
# ---------------------------------------------------------------------------

@router.get("/external/preview-deal")
async def preview_deal_endpoint(
    amount_rub: float,
    operator_percent: float = 0.0,
    admin=Depends(get_current_admin),
):
    from routers.public import get_exchanger_rates_cached

    rates = await get_exchanger_rates_cached()
    usdt_rate_rub = float(rates.get("usdt") or 0)
    if usdt_rate_rub <= 0:
        raise HTTPException(status_code=503, detail="Курс USDT/RUB недоступен")

    result = preview_deal(
        amount_rub,
        usdt_rate_rub,
        markup_pct=settings.ext_markup_pct,
        card_fee_pct=settings.ext_card_fee_pct,
        receive_fee_usd=settings.ext_receive_fee_usd,
        operator_percent=operator_percent,
    )
    if result is None:
        raise HTTPException(status_code=400, detail="Ошибка расчёта")

    result["withdraw_fee_usd"] = withdraw_fee_usd("usdt")
    result["withdraw_fees"] = withdraw_fees_map()
    result["payout_threshold_usd"] = min_payout_gross_usd("usdt")
    return result


# ---------------------------------------------------------------------------
# GET /api/admin/external/preview-payout
# ---------------------------------------------------------------------------

@router.get("/external/preview-payout")
async def preview_payout_endpoint(
    gross_usd: float,
    crypto: str = "usdt",
    fee_usd: Optional[float] = None,
    admin=Depends(get_current_admin),
):
    from routers.public import get_exchanger_rates_cached

    if crypto not in ("btc", "usdt", "trx", "ltc"):
        raise HTTPException(status_code=400, detail="crypto must be btc/usdt/trx/ltc")
    if fee_usd is not None and fee_usd < 0:
        raise HTTPException(status_code=400, detail="fee_usd must be >= 0")

    rates = await get_exchanger_rates_cached()
    usdt_rate_rub = float(rates.get("usdt") or 0)
    if usdt_rate_rub <= 0:
        raise HTTPException(status_code=503, detail="Курс недоступен")

    effective_fee = (
        float(fee_usd) if fee_usd is not None else float(withdraw_fee_usd(crypto))
    )
    result = preview_payout(
        gross_usd,
        crypto,
        rates,
        fee_usd=effective_fee,
        payout_threshold_usd=min_payout_gross_usd(crypto),
    )
    if result is None:
        raise HTTPException(status_code=400, detail="Ошибка расчёта")
    return result
