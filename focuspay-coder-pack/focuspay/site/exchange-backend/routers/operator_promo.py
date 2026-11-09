"""Промокоды: выдача оператором."""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from auth import get_current_operator, operator_public_dict
from db import get_pool
from promo_campaigns import (
    create_exchange_discount_campaign,
    create_fixed_rub_campaign,
    effective_promo_status,
)

logger = logging.getLogger("operator_promo")

router = APIRouter()

_TEAM_PROMO_KINDS = ("fixed_rub", "exchange_discount")

_TEAM_PROMO_SELECT = """
    SELECT pc.*,
           oa.username AS issuer_username,
           oa.display_name AS issuer_display_name,
           (
               SELECT COUNT(*)::int FROM promo_gift_redemptions pgr
               WHERE pgr.promo_code = pc.code
           ) AS activations_used
    FROM promo_campaigns pc
    LEFT JOIN operator_accounts oa ON oa.id = pc.issued_by_operator_id
    WHERE pc.campaign_kind = ANY($1::text[])
"""

_TEAM_PROMO_CTE = """
WITH team_promos AS (
    SELECT pc.*,
           oa.username AS issuer_username,
           oa.display_name AS issuer_display_name,
           (
               SELECT COUNT(*)::int FROM promo_gift_redemptions pgr
               WHERE pgr.promo_code = pc.code
           ) AS activations_used
    FROM promo_campaigns pc
    LEFT JOIN operator_accounts oa ON oa.id = pc.issued_by_operator_id
    WHERE pc.campaign_kind = ANY($1::text[])
)
"""

_DUPLICATE_EXISTS = """
EXISTS (
    SELECT 1 FROM team_promos tp2
    WHERE tp2.id <> tp.id
      AND tp2.activations_used = 0
      AND tp.activations_used = 0
      AND tp2.campaign_kind = tp.campaign_kind
      AND tp2.client_fixed_bonus_rub = tp.client_fixed_bonus_rub
      AND tp2.issued_by_operator_id IS NOT DISTINCT FROM tp.issued_by_operator_id
)
"""


class OperatorPromoCreate(BaseModel):
    client_fixed_bonus_rub: float
    max_activations: int = 1
    name: Optional[str] = None
    min_order_rub: float = 0  # для скидки на обмен: мин. сумма заказа

    @field_validator("max_activations")
    @classmethod
    def _max_act(cls, v: int) -> int:
        if v < 1 or v > 1000:
            raise ValueError("max_activations must be between 1 and 1000")
        return v

    @field_validator("min_order_rub")
    @classmethod
    def _min_order(cls, v: float) -> float:
        if v < 0:
            raise ValueError("min_order_rub must be >= 0")
        return v


class OperatorPromoUpdate(BaseModel):
    is_active: Optional[bool] = None


class OperatorPromoBulkIds(BaseModel):
    ids: List[int]

    @field_validator("ids")
    @classmethod
    def _ids_nonempty(cls, v: List[int]) -> List[int]:
        cleaned = sorted({int(x) for x in v if int(x) > 0})
        if not cleaned:
            raise ValueError("ids must not be empty")
        if len(cleaned) > 500:
            raise ValueError("too many ids (max 500)")
        return cleaned


async def _fetch_team_promo_row(conn, promo_id: int):
    return await conn.fetchrow(
        f"""
        {_TEAM_PROMO_SELECT}
          AND pc.id = $2
        """,
        list(_TEAM_PROMO_KINDS),
        promo_id,
    )


def _issuer_out(row) -> dict | None:
    op_id = row.get("issued_by_operator_id")
    if not op_id:
        return None
    username = (row.get("issuer_username") or "").strip()
    display = (row.get("issuer_display_name") or "").strip()
    label = display or (f"@{username}" if username else f"#{op_id}")
    return {
        "id": int(op_id),
        "username": username or None,
        "display_name": display or None,
        "label": label,
    }


def _promo_row_out(row, *, activations_used: int | None = None) -> dict:
    used = int(
        activations_used
        if activations_used is not None
        else (row.get("activations_used") or 0)
    )
    max_act = int(row.get("max_activations") or 1)
    is_active = bool(row["is_active"])
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "campaign_kind": row.get("campaign_kind") or "fixed_rub",
        "client_fixed_bonus_rub": float(row["client_fixed_bonus_rub"] or 0),
        "min_order_rub": float(row.get("exchange_discount_min_order_rub") or 0),
        "max_activations": max_act,
        "activations_used": used,
        "activations_remaining": max(0, max_act - used),
        "is_active": is_active,
        "status": effective_promo_status(
            is_active=is_active,
            activations_used=used,
            max_activations=max_act,
        ),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "issued_by_operator_id": row.get("issued_by_operator_id"),
        "issued_by_operator": _issuer_out(row),
    }


def _issuer_label_from_parts(
    op_id: int | None, username: str | None, display_name: str | None
) -> str:
    if not op_id:
        return "Админ"
    display = (display_name or "").strip()
    user = (username or "").strip()
    if display and user:
        return f"{display} (@{user})"
    if display:
        return display
    if user:
        return f"@{user}"
    return f"#{op_id}"


def _parse_issued_by_filter(issued_by: str, op_id: int) -> tuple[str | None, object]:
    raw = (issued_by or "all").strip().lower()
    if raw in ("all", ""):
        return None, None
    if raw == "mine":
        return "tp.issued_by_operator_id = ${n}", op_id
    if raw == "admin":
        return "tp.issued_by_operator_id IS NULL", None
    try:
        oid = int(raw)
        if oid > 0:
            return "tp.issued_by_operator_id = ${n}", oid
    except ValueError:
        pass
    raise HTTPException(status_code=400, detail="Invalid issued_by filter")


def _build_list_filters(
    *,
    op_id: int,
    mine_only: bool,
    kind: str,
    status: str,
    issued_by: str,
    q: str | None,
    duplicates_only: bool,
    date_from: date | None,
    date_to: date | None,
) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    def add(clause: str, value: object | None = None) -> None:
        if "${n}" in clause:
            idx = len(params) + 2  # $1 = kinds array
            clause = clause.replace("${n}", f"${idx}")
        clauses.append(clause)
        if value is not None:
            params.append(value)

    if mine_only:
        add("tp.issued_by_operator_id = ${n}", op_id)
    else:
        ib_clause, ib_val = _parse_issued_by_filter(issued_by, op_id)
        if ib_clause:
            add(ib_clause, ib_val)

    kind_norm = (kind or "all").strip().lower()
    if kind_norm == "fixed_rub":
        add("tp.campaign_kind = ${n}", "fixed_rub")
    elif kind_norm == "exchange_discount":
        add("tp.campaign_kind = ${n}", "exchange_discount")

    status_norm = (status or "all").strip().lower()
    if status_norm == "unused":
        add("tp.activations_used = 0")
    elif status_norm == "active":
        add("tp.is_active = TRUE AND tp.activations_used < tp.max_activations")
    elif status_norm == "exhausted":
        add("tp.activations_used >= tp.max_activations")
    elif status_norm == "disabled":
        add("tp.is_active = FALSE")

    q_norm = (q or "").strip()
    if q_norm:
        like = f"%{q_norm}%"
        idx = len(params) + 2
        clauses.append(f"(tp.code ILIKE ${idx} OR tp.name ILIKE ${idx + 1})")
        params.extend([like, like])

    if duplicates_only:
        add(_DUPLICATE_EXISTS)

    if date_from:
        add("tp.created_at >= ${n}", datetime.combine(date_from, time.min))
    if date_to:
        add("tp.created_at < ${n}", datetime.combine(date_to, time.max))

    return clauses, params


async def _fetch_promo_meta(conn) -> tuple[dict, list[dict], int]:
    summary_row = await conn.fetchrow(
        f"""
        {_TEAM_PROMO_CTE}
        SELECT
            COUNT(*)::int AS total_all,
            COUNT(*) FILTER (
                WHERE tp.is_active AND tp.activations_used < tp.max_activations
            )::int AS active,
            COUNT(*) FILTER (WHERE tp.activations_used = 0)::int AS unused,
            COUNT(*) FILTER (
                WHERE tp.activations_used >= tp.max_activations
            )::int AS exhausted,
            COUNT(*) FILTER (WHERE NOT tp.is_active)::int AS disabled,
            COUNT(*) FILTER (WHERE {_DUPLICATE_EXISTS})::int AS duplicates
        FROM team_promos tp
        """,
        list(_TEAM_PROMO_KINDS),
    )
    issuer_rows = await conn.fetch(
        f"""
        {_TEAM_PROMO_CTE}
        SELECT
            tp.issued_by_operator_id,
            tp.issuer_username,
            tp.issuer_display_name,
            COUNT(*)::int AS promo_count
        FROM team_promos tp
        GROUP BY tp.issued_by_operator_id, tp.issuer_username, tp.issuer_display_name
        ORDER BY promo_count DESC, tp.issuer_username NULLS LAST
        """,
        list(_TEAM_PROMO_KINDS),
    )
    issuers = [
        {
            "id": int(r["issued_by_operator_id"]) if r["issued_by_operator_id"] else None,
            "label": _issuer_label_from_parts(
                r["issued_by_operator_id"],
                r["issuer_username"],
                r["issuer_display_name"],
            ),
            "count": int(r["promo_count"] or 0),
        }
        for r in issuer_rows
    ]
    summary = {
        "active": int(summary_row["active"] or 0),
        "unused": int(summary_row["unused"] or 0),
        "exhausted": int(summary_row["exhausted"] or 0),
        "disabled": int(summary_row["disabled"] or 0),
        "duplicates": int(summary_row["duplicates"] or 0),
    }
    total_all = int(summary_row["total_all"] or 0)
    return summary, issuers, total_all


def _operator_delete_allowed(row) -> tuple[bool, str | None]:
    """Можно удалить: неиспользованные; использованные «баланс» — если отключены."""
    used = int(row.get("activations_used") or 0)
    if used == 0:
        return True, None
    kind = (row.get("campaign_kind") or "fixed_rub").lower()
    if kind == "fixed_rub" and not bool(row.get("is_active")):
        return True, "archive"
    return False, (
        "Код уже активировали. Для баланса: сначала «Отключить», потом «Удалить». "
        "Скидки на обмен после активации удалить нельзя — только отключить."
    )


async def _delete_team_promo(conn, row) -> None:
    allowed, mode = _operator_delete_allowed(row)
    if not allowed:
        raise HTTPException(status_code=409, detail=mode or "Нельзя удалить")
    if mode == "archive":
        await conn.execute(
            "DELETE FROM promo_gift_redemptions WHERE promo_code = $1",
            row["code"],
        )
    result = await conn.execute(
        "DELETE FROM promo_campaigns WHERE id = $1",
        int(row["id"]),
    )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Promo not found")


@router.get("/promos")
async def list_operator_promos(
    operator=Depends(get_current_operator),
    mine_only: bool = Query(False, description="Только промокоды текущего оператора"),
    kind: Literal["all", "fixed_rub", "exchange_discount"] = Query(
        "all", description="Тип промокода"
    ),
    status: Literal["all", "active", "unused", "exhausted", "disabled"] = Query(
        "all", description="Статус промокода"
    ),
    issued_by: str = Query(
        "all",
        description="Кто выдал: all | mine | admin | {operator_id}",
    ),
    q: Optional[str] = Query(None, description="Поиск по коду или комментарию"),
    duplicates_only: bool = Query(False, description="Только дубли"),
    date_from: Optional[date] = Query(None, description="Создан не раньше"),
    date_to: Optional[date] = Query(None, description="Создан не позже"),
):
    op_id = int(operator["id"])
    if mine_only:
        issued_by = "mine"

    clauses, extra_params = _build_list_filters(
        op_id=op_id,
        mine_only=False,
        kind=kind,
        status=status,
        issued_by=issued_by,
        q=q,
        duplicates_only=duplicates_only,
        date_from=date_from,
        date_to=date_to,
    )

    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    pool = await get_pool()
    async with pool.acquire() as conn:
        summary, issuers, total_all = await _fetch_promo_meta(conn)
        count_row = await conn.fetchrow(
            f"""
            {_TEAM_PROMO_CTE}
            SELECT COUNT(*)::int AS cnt
            FROM team_promos tp
            {where_sql}
            """,
            list(_TEAM_PROMO_KINDS),
            *extra_params,
        )
        rows = await conn.fetch(
            f"""
            {_TEAM_PROMO_CTE}
            SELECT tp.*
            FROM team_promos tp
            {where_sql}
            ORDER BY tp.created_at DESC
            LIMIT 500
            """,
            list(_TEAM_PROMO_KINDS),
            *extra_params,
        )

    promos = [_promo_row_out(r) for r in rows]
    total_filtered = int(count_row["cnt"] or 0) if count_row else len(promos)
    return {
        "promos": promos,
        "total": total_filtered,
        "total_all": total_all,
        "summary": summary,
        "issuers": issuers,
        "operator": operator_public_dict(operator),
        "mine_only": mine_only or issued_by.strip().lower() == "mine",
        "filters": {
            "kind": kind,
            "status": status,
            "issued_by": issued_by,
            "q": (q or "").strip() or None,
            "duplicates_only": duplicates_only,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "mine_only": mine_only,
        },
    }


@router.get("/promos/{promo_id}")
async def get_operator_promo(promo_id: int, operator=Depends(get_current_operator)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _fetch_team_promo_row(conn, promo_id)
        if not row:
            raise HTTPException(status_code=404, detail="Promo not found")

        entries = await conn.fetch(
            """
            SELECT pgr.user_id, pgr.amount_rub, pgr.redeemed_at,
                   bu.username, bu.first_name
            FROM promo_gift_redemptions pgr
            LEFT JOIN bot_users bu ON bu.user_id = pgr.user_id
            WHERE pgr.promo_code = $1
            ORDER BY pgr.redeemed_at DESC
            LIMIT 200
            """,
            row["code"],
        )

    return {
        "promo": _promo_row_out(row),
        "entries": [
            {
                "user_id": e["user_id"],
                "username": e["username"],
                "first_name": e["first_name"],
                "amount_rub": float(e["amount_rub"]),
                "entered_at": e["redeemed_at"].isoformat() if e["redeemed_at"] else None,
            }
            for e in entries
        ],
    }


@router.post("/promos", status_code=201)
async def create_operator_promo(body: OperatorPromoCreate, operator=Depends(get_current_operator)):
    if not operator.get("is_active"):
        raise HTTPException(status_code=403, detail="Operator account inactive")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                row = await create_fixed_rub_campaign(
                    conn,
                    client_fixed_bonus_rub=body.client_fixed_bonus_rub,
                    max_activations=body.max_activations,
                    name=(body.name or "").strip() or None,
                    issued_by_operator_id=int(operator["id"]),
                    code_prefix="G",
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Не удалось создать промокод: {e}") from e

    return _promo_row_out(row, activations_used=0)


@router.patch("/promos/{promo_id}")
async def update_operator_promo(
    promo_id: int, body: OperatorPromoUpdate, operator=Depends(get_current_operator)
):
    if body.is_active is None:
        raise HTTPException(status_code=400, detail="Nothing to update")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _fetch_team_promo_row(conn, promo_id)
        if not row:
            raise HTTPException(status_code=404, detail="Promo not found")
        await conn.execute(
            """
            UPDATE promo_campaigns
            SET is_active = $2, updated_at = now()
            WHERE id = $1
            """,
            promo_id,
            bool(body.is_active),
        )
        updated = await _fetch_team_promo_row(conn, promo_id)
        if not updated:
            raise HTTPException(status_code=404, detail="Promo not found")

    return _promo_row_out(updated)


@router.delete("/promos/{promo_id}", status_code=204)
async def delete_operator_promo(promo_id: int, operator=Depends(get_current_operator)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _fetch_team_promo_row(conn, promo_id)
        if not row:
            raise HTTPException(status_code=404, detail="Promo not found")
        async with conn.transaction():
            await _delete_team_promo(conn, row)


@router.post("/promos/bulk-delete")
async def bulk_delete_operator_promos(
    body: OperatorPromoBulkIds, operator=Depends(get_current_operator)
):
    deleted: list[int] = []
    skipped: list[dict] = []
    pool = await get_pool()
    async with pool.acquire() as conn:
        for promo_id in body.ids:
            row = await _fetch_team_promo_row(conn, promo_id)
            if not row:
                skipped.append({"id": promo_id, "reason": "not_found"})
                continue
            allowed, reason = _operator_delete_allowed(row)
            if not allowed:
                skipped.append(
                    {
                        "id": promo_id,
                        "reason": "already_used",
                        "code": row["code"],
                        "detail": reason,
                    }
                )
                continue
            try:
                async with conn.transaction():
                    await _delete_team_promo(conn, row)
                deleted.append(promo_id)
            except HTTPException as e:
                skipped.append({"id": promo_id, "reason": "delete_failed", "detail": e.detail})
    return {"deleted": deleted, "skipped": skipped, "deleted_count": len(deleted)}


@router.post("/promos/bulk-deactivate")
async def bulk_deactivate_operator_promos(
    body: OperatorPromoBulkIds, operator=Depends(get_current_operator)
):
    updated: list[int] = []
    skipped: list[dict] = []
    pool = await get_pool()
    async with pool.acquire() as conn:
        for promo_id in body.ids:
            row = await _fetch_team_promo_row(conn, promo_id)
            if not row:
                skipped.append({"id": promo_id, "reason": "not_found"})
                continue
            if not row["is_active"]:
                skipped.append({"id": promo_id, "reason": "already_inactive", "code": row["code"]})
                continue
            result = await conn.execute(
                """
                UPDATE promo_campaigns
                SET is_active = FALSE, updated_at = now()
                WHERE id = $1
                """,
                promo_id,
            )
            if result.endswith("1"):
                updated.append(promo_id)
            else:
                skipped.append({"id": promo_id, "reason": "update_failed"})
    return {"deactivated": updated, "skipped": skipped, "deactivated_count": len(updated)}


class OperatorDiscountGrant(BaseModel):
    """Прямая выдача скидки на обмен пользователю(ям) без промокода."""

    amount_rub: float
    min_order_rub: float = 0
    recipients: List[str]
    name: Optional[str] = None
    raffle_winner_id: Optional[int] = None

    @field_validator("amount_rub")
    @classmethod
    def _amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("amount_rub must be > 0")
        if v > 1_000_000:
            raise ValueError("amount_rub too large")
        return v

    @field_validator("min_order_rub")
    @classmethod
    def _min_order(cls, v: float) -> float:
        if v < 0:
            raise ValueError("min_order_rub must be >= 0")
        return v

    @field_validator("recipients")
    @classmethod
    def _recipients(cls, v: List[str]) -> List[str]:
        cleaned = [str(x).strip() for x in (v or []) if str(x).strip()]
        if not cleaned:
            raise ValueError("recipients must not be empty")
        if len(cleaned) > 500:
            raise ValueError("too many recipients (max 500)")
        return cleaned


_GRANTS_FROM = """
    FROM user_exchange_discounts ued
    LEFT JOIN bot_users bu ON bu.user_id = ued.user_id
    LEFT JOIN operator_accounts oa ON oa.id = ued.issued_by_operator_id
"""

_GRANT_STATUS_LABELS = {
    "active": "Активна",
    "held": "В заказе",
    "used": "Использована",
    "released": "Снята",
}


def _user_label(row) -> str:
    username = (row.get("user_username") or "").strip()
    first = (row.get("user_first_name") or "").strip()
    if username:
        return f"@{username}"
    if first:
        return first
    uid = row.get("user_id")
    return f"ID {uid}" if uid is not None else "—"


def _grant_row_out(row) -> dict:
    status = (row.get("status") or "active").lower()
    op_id = row.get("issued_by_operator_id")
    issuer_username = (row.get("issuer_username") or "").strip()
    issuer_display = (row.get("issuer_display_name") or "").strip()
    issuer = None
    if op_id:
        issuer = {
            "id": int(op_id),
            "username": issuer_username or None,
            "display_name": issuer_display or None,
            "label": _issuer_label_from_parts(op_id, issuer_username, issuer_display),
        }
    amount = float(row["amount_rub"] or 0)
    min_order = float(row.get("min_order_rub") or 0)
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "user_label": _user_label(row),
        "username": (row.get("user_username") or None),
        "first_name": (row.get("user_first_name") or None),
        "amount_rub": amount,
        "min_order_rub": min_order,
        "label": (row.get("promo_code") or "").strip() or None,
        "status": status,
        "status_label": _GRANT_STATUS_LABELS.get(status, status),
        "order_id": row.get("order_id"),
        "issued_by_operator_id": op_id,
        "issued_by_operator": issuer,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "used_at": row["used_at"].isoformat() if row.get("used_at") else None,
    }


def _build_grant_list_filters(
    *,
    op_id: int,
    status: str,
    issued_by: str,
    q: str | None,
    amount_rub: float | None = None,
    date_from: date | None,
    date_to: date | None,
) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    ib_clause, ib_val = _parse_issued_by_filter(issued_by, op_id)
    if ib_clause:
        clause = ib_clause.replace("tp.", "ued.")
        if "${n}" in clause:
            idx = len(params) + 1
            clause = clause.replace("${n}", f"${idx}")
        clauses.append(clause)
        if ib_val is not None:
            params.append(ib_val)

    status_norm = (status or "all").strip().lower()
    if status_norm == "active":
        clauses.append("ued.status = 'active'")
    elif status_norm == "used":
        clauses.append("ued.status IN ('used', 'released')")
    elif status_norm == "held":
        clauses.append("ued.status = 'held'")

    if amount_rub is not None and amount_rub > 0:
        idx = len(params) + 1
        clauses.append(f"ued.amount_rub = ${idx}")
        params.append(amount_rub)

    q_norm = (q or "").strip()
    if q_norm:
        like = f"%{q_norm}%"
        username_like = f"%{q_norm.lstrip('@')}%"
        idx = len(params) + 1
        # Комментарий прямой выдачи хранится в promo_code (отдельной колонки label нет).
        clauses.append(
            f"(ued.promo_code ILIKE ${idx} OR bu.username ILIKE ${idx + 1} "
            f"OR bu.first_name ILIKE ${idx + 2} OR ued.user_id::text ILIKE ${idx + 3} "
            f"OR ued.amount_rub::text ILIKE ${idx + 4} "
            f"OR ued.min_order_rub::text ILIKE ${idx + 5})"
        )
        params.extend([like, username_like, like, q_norm, like, like])

    if date_from:
        idx = len(params) + 1
        clauses.append(f"ued.created_at >= ${idx}")
        params.append(datetime.combine(date_from, time.min))
    if date_to:
        idx = len(params) + 1
        clauses.append(f"ued.created_at < ${idx}")
        params.append(datetime.combine(date_to, time.max))

    return clauses, params


async def _fetch_grant_meta(conn) -> tuple[dict, list[dict], int]:
    summary_row = await conn.fetchrow(
        f"""
        SELECT
            COUNT(*)::int AS total_all,
            COUNT(*) FILTER (WHERE ued.status = 'active')::int AS active,
            COUNT(*) FILTER (WHERE ued.status IN ('used', 'released'))::int AS used,
            COUNT(*) FILTER (WHERE ued.status = 'held')::int AS held
        {_GRANTS_FROM}
        """
    )
    issuer_rows = await conn.fetch(
        f"""
        SELECT
            ued.issued_by_operator_id,
            oa.username AS issuer_username,
            oa.display_name AS issuer_display_name,
            COUNT(*)::int AS grant_count
        {_GRANTS_FROM}
        GROUP BY ued.issued_by_operator_id, oa.username, oa.display_name
        ORDER BY grant_count DESC, oa.username NULLS LAST
        """
    )
    issuers = [
        {
            "id": int(r["issued_by_operator_id"]) if r["issued_by_operator_id"] else None,
            "label": _issuer_label_from_parts(
                r["issued_by_operator_id"],
                r["issuer_username"],
                r["issuer_display_name"],
            ),
            "count": int(r["grant_count"] or 0),
        }
        for r in issuer_rows
    ]
    summary = {
        "active": int(summary_row["active"] or 0),
        "used": int(summary_row["used"] or 0),
        "held": int(summary_row["held"] or 0),
    }
    return summary, issuers, int(summary_row["total_all"] or 0)


@router.get("/discounts")
async def list_operator_discount_grants(
    operator=Depends(get_current_operator),
    status: Literal["all", "active", "used", "held"] = Query(
        "all", description="Статус выданной скидки"
    ),
    issued_by: str = Query(
        "all",
        description="Кто выдал: all | mine | admin | {operator_id}",
    ),
    q: Optional[str] = Query(None, description="Поиск по клиенту, сумме или комментарию"),
    amount_rub: Optional[float] = Query(None, description="Точная сумма скидки, ₽"),
    date_from: Optional[date] = Query(None, description="Выдана не раньше"),
    date_to: Optional[date] = Query(None, description="Выдана не позже"),
):
    op_id = int(operator["id"])
    clauses, extra_params = _build_grant_list_filters(
        op_id=op_id,
        status=status,
        issued_by=issued_by,
        q=q,
        amount_rub=amount_rub,
        date_from=date_from,
        date_to=date_to,
    )
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    pool = await get_pool()
    async with pool.acquire() as conn:
        summary, issuers, total_all = await _fetch_grant_meta(conn)
        count_row = await conn.fetchrow(
            f"""
            SELECT COUNT(*)::int AS cnt
            {_GRANTS_FROM}
            {where_sql}
            """,
            *extra_params,
        )
        rows = await conn.fetch(
            f"""
            SELECT ued.*, bu.username AS user_username, bu.first_name AS user_first_name,
                   oa.username AS issuer_username, oa.display_name AS issuer_display_name
            {_GRANTS_FROM}
            {where_sql}
            ORDER BY ued.created_at DESC
            LIMIT 500
            """,
            *extra_params,
        )

    grants = [_grant_row_out(r) for r in rows]
    total_filtered = int(count_row["cnt"] or 0) if count_row else len(grants)
    return {
        "grants": grants,
        "total": total_filtered,
        "total_all": total_all,
        "summary": summary,
        "issuers": issuers,
        "operator": operator_public_dict(operator),
        "filters": {
            "status": status,
            "issued_by": issued_by,
            "q": (q or "").strip() or None,
            "amount_rub": amount_rub,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
    }


def _grant_notice_text(amount_rub: float, min_order_rub: float) -> str:
    amt = f"{amount_rub:,.0f}".replace(",", " ")
    if min_order_rub and min_order_rub > 0:
        mo = f"{min_order_rub:,.0f}".replace(",", " ")
        cond = f" при обмене от {mo} ₽"
    else:
        cond = ""
    return (
        "🎁 <b>Вам начислена скидка на обмен</b>\n\n"
        f"💸 <b>{amt} ₽</b>{cond}\n\n"
        "Откройте «🏷 Мои скидки» в боте. Скидка применяется при покупке крипты "
        "после ввода суммы."
    )


@router.post("/discounts/grant", status_code=201)
async def grant_operator_discount(
    body: OperatorDiscountGrant, operator=Depends(get_current_operator)
):
    if not operator.get("is_active"):
        raise HTTPException(status_code=403, detail="Operator account inactive")

    from exchange_discount_db import grant_exchange_discount
    from telegram_notify import send_user_message
    from telegram_user_lookup import resolve_single_recipient
    import operator_wallet_payouts as owp

    op_id = int(operator["id"])
    label = (body.name or "").strip() or "Подарок"
    results: list[dict] = []
    granted_count = 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        for raw in body.recipients:
            hit = await resolve_single_recipient(conn, raw)
            if not hit:
                results.append(
                    {"recipient": raw, "status": "not_found", "user_id": None, "notified": False}
                )
                continue
            user_id = int(hit["user_id"])
            try:
                async with conn.transaction():
                    await grant_exchange_discount(
                        conn,
                        user_id,
                        body.amount_rub,
                        body.min_order_rub,
                        operator_id=op_id,
                        label=label,
                    )
                    rw_id = body.raffle_winner_id if len(body.recipients) == 1 else None
                    await owp.mark_balance_raffle_winner_paid(
                        conn,
                        user_id=user_id,
                        amount_rub=body.amount_rub,
                        operator_id=op_id,
                        label=label,
                        raffle_winner_id=rw_id,
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning("grant discount uid=%s failed: %s", user_id, e)
                results.append(
                    {"recipient": raw, "status": "error", "user_id": user_id, "notified": False}
                )
                continue
            granted_count += 1
            notified = False
            if user_id > 0:
                try:
                    notified = await send_user_message(
                        user_id, _grant_notice_text(body.amount_rub, body.min_order_rub)
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("notify grant uid=%s failed: %s", user_id, e)
            results.append(
                {
                    "recipient": raw,
                    "status": "granted",
                    "user_id": user_id,
                    "username": hit.get("username"),
                    "notified": notified,
                }
            )

    return {
        "granted": granted_count,
        "total": len(body.recipients),
        "amount_rub": body.amount_rub,
        "min_order_rub": body.min_order_rub,
        "results": results,
    }


def _grant_delete_allowed(row) -> tuple[bool, str]:
    status = (row.get("status") or "active").lower()
    if status == "active":
        return True, ""
    if status == "held":
        return False, "Скидка в активном заказе — удалить нельзя"
    if status == "used":
        return False, "Скидка уже использована — удалить нельзя"
    if status == "released":
        return False, "Скидка уже снята — удалить нельзя"
    return False, "Удалить можно только активную скидку"


async def _fetch_grant_row(conn, grant_id: int):
    return await conn.fetchrow(
        f"""
        SELECT ued.*, bu.username AS user_username, bu.first_name AS user_first_name,
               oa.username AS issuer_username, oa.display_name AS issuer_display_name
        {_GRANTS_FROM}
        WHERE ued.id = $1
        """,
        grant_id,
    )


async def _delete_grant(conn, row) -> None:
    allowed, reason = _grant_delete_allowed(row)
    if not allowed:
        raise HTTPException(status_code=400, detail=reason)
    result = await conn.execute(
        "DELETE FROM user_exchange_discounts WHERE id = $1 AND status = 'active'",
        int(row["id"]),
    )
    if not result.endswith("1"):
        raise HTTPException(status_code=409, detail="Скидка уже изменилась — обновите список")


@router.delete("/discounts/{grant_id}", status_code=204)
async def delete_operator_discount_grant(
    grant_id: int, operator=Depends(get_current_operator)
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _fetch_grant_row(conn, grant_id)
        if not row:
            raise HTTPException(status_code=404, detail="Скидка не найдена")
        async with conn.transaction():
            await _delete_grant(conn, row)


@router.post("/discounts/bulk-delete")
async def bulk_delete_operator_discount_grants(
    body: OperatorPromoBulkIds, operator=Depends(get_current_operator)
):
    deleted: list[int] = []
    skipped: list[dict] = []
    pool = await get_pool()
    async with pool.acquire() as conn:
        for grant_id in body.ids:
            row = await _fetch_grant_row(conn, grant_id)
            if not row:
                skipped.append({"id": grant_id, "reason": "not_found"})
                continue
            allowed, reason = _grant_delete_allowed(row)
            if not allowed:
                skipped.append(
                    {
                        "id": grant_id,
                        "reason": "not_deletable",
                        "user_label": _user_label(row),
                        "detail": reason,
                    }
                )
                continue
            try:
                async with conn.transaction():
                    await _delete_grant(conn, row)
                deleted.append(grant_id)
            except HTTPException as e:
                skipped.append({"id": grant_id, "reason": "delete_failed", "detail": e.detail})
    return {"deleted": deleted, "skipped": skipped, "deleted_count": len(deleted)}


@router.post("/promos/exchange-discount", status_code=201)
async def create_operator_exchange_discount_promo(
    body: OperatorPromoCreate, operator=Depends(get_current_operator)
):
    if not operator.get("is_active"):
        raise HTTPException(status_code=403, detail="Operator account inactive")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                row = await create_exchange_discount_campaign(
                    conn,
                    client_fixed_bonus_rub=body.client_fixed_bonus_rub,
                    max_activations=body.max_activations,
                    name=(body.name or "").strip() or None,
                    issued_by_operator_id=int(operator["id"]),
                    min_order_rub=body.min_order_rub,
                    code_prefix="H",
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Не удалось создать промокод: {e}"
                ) from e

    return _promo_row_out(row, activations_used=0)


class OperatorWalletPayoutCreate(BaseModel):
    recipient_name: str
    wallet_address: str
    tx_hash: str
    amount_rub: float
    crypto: Literal["ltc", "btc", "usdt"] = "ltc"
    label: Optional[str] = None
    recipient: Optional[str] = None
    raffle_winner_id: Optional[int] = None

    @field_validator("recipient_name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("recipient_name is required")
        return v.strip()

    @field_validator("wallet_address")
    @classmethod
    def _wallet(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("wallet_address is required")
        return v.strip()

    @field_validator("amount_rub")
    @classmethod
    def _amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("amount_rub must be > 0")
        if v > 10_000_000:
            raise ValueError("amount_rub too large")
        return v


@router.get("/wallet-payouts/pending-raffle")
async def list_pending_raffle_wallet_payouts(operator=Depends(get_current_operator)):
    if not operator.get("is_active"):
        raise HTTPException(status_code=403, detail="Operator account inactive")
    import operator_wallet_payouts as owp

    items = await owp.list_pending_raffle_ltc_winners()
    balance = await owp.list_pending_raffle_balance_winners()
    return {"items": items, "ltc": items, "balance": balance}


@router.get("/wallet-payouts")
async def list_operator_wallet_payouts(
    operator=Depends(get_current_operator),
    issued_by: str = Query("all", description="Кто выдал: all | mine | {operator_id}"),
    q: Optional[str] = Query(None, description="Поиск по имени, адресу, hash, комментарию"),
    amount_rub: Optional[float] = Query(None, description="Точная сумма, ₽"),
    crypto: Optional[str] = Query(None, description="ltc | btc | usdt | all"),
    date_from: Optional[date] = Query(None, description="Не раньше"),
    date_to: Optional[date] = Query(None, description="Не позже"),
):
    if not operator.get("is_active"):
        raise HTTPException(status_code=403, detail="Operator account inactive")
    import operator_wallet_payouts as owp

    op_id = int(operator["id"])
    try:
        data = await owp.list_wallet_payouts(
            op_id=op_id,
            issued_by=issued_by,
            q=q,
            amount_rub=amount_rub,
            crypto=crypto,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        **data,
        "operator": operator_public_dict(operator),
        "filters": {
            "issued_by": issued_by,
            "q": (q or "").strip() or None,
            "amount_rub": amount_rub,
            "crypto": (crypto or "").strip().lower() or None,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
    }


@router.post("/wallet-payouts", status_code=201)
async def create_operator_wallet_payout(
    body: OperatorWalletPayoutCreate,
    operator=Depends(get_current_operator),
):
    if not operator.get("is_active"):
        raise HTTPException(status_code=403, detail="Operator account inactive")
    import operator_wallet_payouts as owp

    payout, err = await owp.create_wallet_payout(
        operator_id=int(operator["id"]),
        recipient_name=body.recipient_name,
        wallet_address=body.wallet_address,
        tx_hash_raw=body.tx_hash,
        amount_rub=body.amount_rub,
        crypto=body.crypto,
        label=body.label,
        recipient=body.recipient,
        raffle_winner_id=body.raffle_winner_id,
    )
    if err == "invalid_tx":
        raise HTTPException(
            status_code=400,
            detail="Некорректный hash. Минимум 8 символов, без пробелов.",
        )
    if err == "duplicate_tx":
        raise HTTPException(status_code=409, detail="Такой hash уже зафиксирован")
    if err == "missing_name":
        raise HTTPException(status_code=400, detail="Укажите имя получателя")
    if err == "missing_wallet":
        raise HTTPException(status_code=400, detail="Укажите адрес кошелька")
    if not payout:
        raise HTTPException(status_code=500, detail="Не удалось сохранить выплату")
    return payout
