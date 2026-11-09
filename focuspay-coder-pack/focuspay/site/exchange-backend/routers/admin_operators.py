"""
Управление операторами (суперадмин): создание аккаунтов, изменение параметров, просмотр статистики.
"""

from datetime import date, datetime, timezone
from typing import Literal, Optional
import logging

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator

from auth import get_current_admin, get_current_finance_viewer, normalize_username
from db import get_pool
from finance_access import can_view_finance_admin, strip_operator_profit_fields
from operator_earnings import utc_aware
from operator_stats import (
    MOSCOW_TODAY_SQL,
    build_daily_balance_stats,
    build_daily_stats,
    compute_balance_summary,
    compute_period_stats,
    default_period_range,
    match_orders_to_shift,
    match_orders_to_shift_by_created,
    moscow_date_expr,
)
from payroll_base import (
    fetch_accruals_for_orders,
    fetch_operator_shift_orders,
    fetch_role_split_earnings_by_order,
    operator_order_completed_at,
    order_completed_in_shift,
    stats_for_operator_shift_conn,
    stats_from_operator_orders,
    stats_from_orders,
)
from permissions import (
    PERM_ORDERS_HISTORY,
    PERM_PAYOUT_REQUISITES_CONFIRM,
    apply_permission_grants,
    operator_is_finance_senior,
    operator_is_senior,
    permissions_for_operator_roles,
)
router = APIRouter()
logger = logging.getLogger("admin_operators")


ROLE_VALUES = {"client", "finance"}
GRADE_VALUES = {"trainee", "junior", "senior"}


def _normalise_roles(value, fallback="client") -> list[str]:
    values = [value] if isinstance(value, str) else list(value or [])
    values = list(dict.fromkeys(str(v) for v in values))
    if not values:
        values = [fallback]
    if not 1 <= len(values) <= 2 or any(v not in ROLE_VALUES for v in values):
        raise ValueError("operator_roles must contain client, finance, or both")
    return values


def _legacy_role(roles: list[str]) -> str:
    return "finance" if roles == ["finance"] else "client"


def _op_out(row) -> dict:
    r = dict(row)
    if isinstance(r.get("created_at"), datetime):
        r["created_at"] = r["created_at"].isoformat()
    r.pop("password_hash", None)
    r.pop("percent", None)
    return r


async def _role_grades_for_operator(conn, operator_id: int) -> dict[str, str]:
    rows = await conn.fetch(
        """
        SELECT role, grade FROM operator_role_profiles
        WHERE operator_id = $1 AND valid_to IS NULL
        ORDER BY role
        """,
        operator_id,
    )
    return {str(row["role"]): str(row["grade"]) for row in rows}


async def _upsert_permission_grant(
    conn, operator_id: int, permission: str, granted: bool
) -> None:
    await conn.execute(
        """
        INSERT INTO operator_permission_grants (operator_id, permission, granted, updated_at)
        VALUES ($1, $2, $3, now())
        ON CONFLICT (operator_id, permission)
        DO UPDATE SET granted = EXCLUDED.granted, updated_at = now()
        """,
        int(operator_id),
        permission,
        bool(granted),
    )


def _payout_confirm_resolved(
    roles: list[str],
    grades: dict[str, str],
    grant: bool | None,
) -> bool:
    principal = {"operator_roles": roles, "role_grades": grades}
    perms = permissions_for_operator_roles(roles)
    if operator_is_senior(principal, grades):
        perms.add(PERM_ORDERS_HISTORY)
    if operator_is_finance_senior(principal, grades):
        perms.add(PERM_PAYOUT_REQUISITES_CONFIRM)
    if grant is not None:
        perms = apply_permission_grants(perms, [(PERM_PAYOUT_REQUISITES_CONFIRM, grant)])
    return PERM_PAYOUT_REQUISITES_CONFIRM in perms


async def _payout_confirm_grant_map(conn, operator_ids: list[int]) -> dict[int, bool]:
    if not operator_ids:
        return {}
    try:
        rows = await conn.fetch(
            """
            SELECT operator_id, granted
            FROM operator_permission_grants
            WHERE permission = $1 AND operator_id = ANY($2::int[])
            """,
            PERM_PAYOUT_REQUISITES_CONFIRM,
            operator_ids,
        )
    except Exception:
        return {}
    return {int(row["operator_id"]): bool(row["granted"]) for row in rows}


async def _sync_operator_role_profiles(
    conn,
    operator_id: int,
    roles: list[str],
    requested_grades: dict[str, str] | None,
    changed_by: int | None,
) -> dict[str, str]:
    current_rows = await conn.fetch(
        """
        SELECT role, grade FROM operator_role_profiles
        WHERE operator_id = $1 AND valid_to IS NULL
        """,
        operator_id,
    )
    current = {str(row["role"]): str(row["grade"]) for row in current_rows}
    requested = requested_grades or {}
    target = {role: requested.get(role, current.get(role, "junior")) for role in roles}
    if any(role not in ROLE_VALUES or grade not in GRADE_VALUES for role, grade in target.items()):
        raise HTTPException(status_code=400, detail="Некорректная роль или уровень оператора")

    removed = set(current) - set(target)
    if removed:
        await conn.execute(
            """
            UPDATE operator_role_profiles
            SET valid_to = now()
            WHERE operator_id = $1 AND valid_to IS NULL AND role = ANY($2::text[])
            """,
            operator_id,
            list(removed),
        )
    for role, grade in target.items():
        if current.get(role) == grade:
            continue
        await conn.execute(
            """
            UPDATE operator_role_profiles
            SET valid_to = now()
            WHERE operator_id = $1 AND role = $2 AND valid_to IS NULL
            """,
            operator_id,
            role,
        )
        weight = await conn.fetchval(
            """
            SELECT weight_multiplier FROM operator_payroll_grade_settings
            WHERE role = $1 AND grade = $2 AND valid_to IS NULL
            ORDER BY valid_from DESC, id DESC LIMIT 1
            """,
            role,
            grade,
        )
        await conn.execute(
            """
            INSERT INTO operator_role_profiles
                (operator_id, role, grade, grade_weight, changed_by)
            VALUES ($1, $2, $3, COALESCE($4, 1.0), $5)
            """,
            operator_id,
            role,
            grade,
            weight,
            changed_by,
        )
    return target


class OperatorPayrollSettingsPatch(BaseModel):
    operator_pool_percent: Optional[float] = Field(None, ge=0, le=100)
    client_operator_share_percent: Optional[float] = Field(None, ge=0, le=100)
    finance_operator_share_percent: Optional[float] = Field(None, ge=0, le=100)
    unassigned_policy: Optional[Literal["ledger", "business"]] = None
    autopilot_presence_percent: Optional[float] = Field(None, ge=0, le=100)
    autopilot_manual_percent: Optional[float] = Field(None, ge=0, le=100)
    autopilot_hourly_enabled: Optional[bool] = None
    autopilot_hourly_rate_rub: Optional[float] = Field(None, ge=0, le=100_000)

    @model_validator(mode="after")
    def validate_total(self):
        client = self.client_operator_share_percent
        finance = self.finance_operator_share_percent
        if (client is None) != (finance is None):
            raise ValueError("client and finance shares must be set together")
        if client is not None and finance is not None and abs(client + finance - 100) > 0.001:
            raise ValueError("client and finance shares must total 100")
        return self


def _settings_number(current: dict, key: str, fallback: float) -> float:
    raw = current.get(key)
    if raw is None:
        return fallback
    return float(raw)


@router.get("/operator-payroll/settings")
async def get_operator_payroll_settings(_admin=Depends(get_current_finance_viewer)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM operator_payroll_settings WHERE valid_to IS NULL ORDER BY valid_from DESC LIMIT 1")
    if not row:
        return {
            "operator_pool_percent": 30.0,
            "client_operator_share_percent": 30.0,
            "finance_operator_share_percent": 70.0,
            "autopilot_presence_percent": 5.0,
            "autopilot_manual_percent": 10.0,
            "autopilot_hourly_enabled": False,
            "autopilot_hourly_rate_rub": 0.0,
        }
    return dict(row)


@router.patch("/operator-payroll/settings")
async def patch_operator_payroll_settings(body: OperatorPayrollSettingsPatch, admin=Depends(get_current_finance_viewer)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            current_row = await conn.fetchrow(
                "SELECT * FROM operator_payroll_settings WHERE valid_to IS NULL ORDER BY valid_from DESC LIMIT 1"
            )
            current = dict(current_row) if current_row else {}
            pool_percent = (
                body.operator_pool_percent
                if body.operator_pool_percent is not None
                else _settings_number(current, "operator_pool_percent", 30)
            )
            client_share = (
                body.client_operator_share_percent
                if body.client_operator_share_percent is not None
                else _settings_number(current, "client_operator_share_percent", 30)
            )
            finance_share = (
                body.finance_operator_share_percent
                if body.finance_operator_share_percent is not None
                else _settings_number(current, "finance_operator_share_percent", 70)
            )
            if abs(client_share + finance_share - 100) > 0.001:
                raise HTTPException(status_code=400, detail="client and finance shares must total 100")
            policy = body.unassigned_policy or current.get("unassigned_policy") or "ledger"
            presence = (
                body.autopilot_presence_percent
                if body.autopilot_presence_percent is not None
                else _settings_number(current, "autopilot_presence_percent", 5)
            )
            manual = (
                body.autopilot_manual_percent
                if body.autopilot_manual_percent is not None
                else _settings_number(current, "autopilot_manual_percent", 10)
            )
            hourly_enabled = (
                body.autopilot_hourly_enabled
                if body.autopilot_hourly_enabled is not None
                else bool(current.get("autopilot_hourly_enabled") or False)
            )
            hourly_rate = (
                body.autopilot_hourly_rate_rub
                if body.autopilot_hourly_rate_rub is not None
                else _settings_number(current, "autopilot_hourly_rate_rub", 0)
            )
            await conn.execute("UPDATE operator_payroll_settings SET valid_to = now() WHERE valid_to IS NULL")
            row = await conn.fetchrow(
                """INSERT INTO operator_payroll_settings(
                       operator_pool_percent, client_operator_share_percent,
                       finance_operator_share_percent, unassigned_policy,
                       autopilot_presence_percent, autopilot_manual_percent,
                       autopilot_hourly_enabled, autopilot_hourly_rate_rub,
                       created_by
                   ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
                pool_percent,
                client_share,
                finance_share,
                policy,
                presence,
                manual,
                hourly_enabled,
                hourly_rate,
                admin.get("id"),
            )
    return dict(row)


class OperatorPayrollGradesPatch(BaseModel):
    role_grade_weights: dict[
        Literal["client", "finance"],
        dict[Literal["trainee", "junior", "senior"], float],
    ]

    @model_validator(mode="after")
    def validate_weights(self):
        expected_roles = {"client", "finance"}
        expected_grades = {"trainee", "junior", "senior"}
        if set(self.role_grade_weights) != expected_roles:
            raise ValueError("Configure client and finance grades")
        for role, grades in self.role_grade_weights.items():
            if set(grades) != expected_grades:
                raise ValueError(f"Configure all grades for {role}")
            if any(value <= 0 or value > 1000 for value in grades.values()):
                raise ValueError("Grade weight must be greater than 0 and no more than 1000")
        return self


def _grade_weights_output(rows) -> dict[str, dict[str, float]]:
    out = {
        "client": {"trainee": 0.75, "junior": 1.0, "senior": 1.25},
        "finance": {"trainee": 0.75, "junior": 1.0, "senior": 1.25},
    }
    for row in rows:
        out.setdefault(str(row["role"]), {})[str(row["grade"])] = float(row["weight_multiplier"])
    return out


@router.get("/operator-payroll/grades")
async def get_operator_payroll_grades(_admin=Depends(get_current_finance_viewer)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, grade, weight_multiplier
            FROM operator_payroll_grade_settings
            WHERE valid_to IS NULL
            ORDER BY role, CASE grade WHEN 'trainee' THEN 1 WHEN 'junior' THEN 2 ELSE 3 END
            """
        )
    return {"role_grade_weights": _grade_weights_output(rows)}


@router.patch("/operator-payroll/grades")
async def patch_operator_payroll_grades(
    body: OperatorPayrollGradesPatch,
    admin=Depends(get_current_finance_viewer),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE operator_payroll_grade_settings SET valid_to = now() WHERE valid_to IS NULL"
            )
            for role, grades in body.role_grade_weights.items():
                for grade, weight in grades.items():
                    await conn.execute(
                        """
                        INSERT INTO operator_payroll_grade_settings
                            (role, grade, weight_multiplier, created_by)
                        VALUES ($1, $2, $3, $4)
                        """,
                        role,
                        grade,
                        weight,
                        admin.get("id"),
                    )
            await conn.execute(
                """
                UPDATE operator_role_profiles p
                SET grade_weight = s.weight_multiplier
                FROM operator_payroll_grade_settings s
                WHERE p.valid_to IS NULL AND s.valid_to IS NULL
                  AND s.role = p.role AND s.grade = p.grade
                """
            )
    return {"role_grade_weights": body.role_grade_weights}


@router.get("/operator-payroll/splits")
async def list_operator_payroll_splits(
    order_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    _admin=Depends(get_current_finance_viewer),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        splits = await conn.fetch(
            """
            SELECT s.*, o.status, o.direction, o.order_source,
                   o.payout_confirmed_at
            FROM order_payroll_splits s
            JOIN orders o ON o.order_id = s.order_id
            WHERE ($1::text IS NULL OR s.order_id = $1)
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT $2
            """,
            order_id,
            limit,
        )
        split_ids = [int(row["id"]) for row in splits]
        lines_by_split: dict[int, list[dict]] = {split_id: [] for split_id in split_ids}
        if split_ids:
            lines = await conn.fetch(
                """
                SELECT l.*, oa.username, oa.display_name
                FROM order_payroll_split_lines l
                LEFT JOIN operator_accounts oa ON oa.id = l.operator_id
                WHERE l.split_id = ANY($1::bigint[])
                ORDER BY l.split_id, l.id
                """,
                split_ids,
            )
            for line in lines:
                item = dict(line)
                for key in ("amount_rub", "weight"):
                    if item.get(key) is not None:
                        item[key] = float(item[key])
                lines_by_split[int(line["split_id"])].append(item)
    result = []
    for split in splits:
        item = dict(split)
        for key in (
            "profit_rub", "operator_pool_percent", "pool_rub", "client_pool_rub",
            "finance_pool_rub", "unassigned_client_pool_rub", "unassigned_finance_pool_rub",
        ):
            if item.get(key) is not None:
                item[key] = float(item[key])
        for key in ("created_at", "payout_confirmed_at"):
            if item.get(key) is not None and hasattr(item[key], "isoformat"):
                item[key] = item[key].isoformat()
        item["lines"] = lines_by_split.get(int(split["id"]), [])
        result.append(item)
    return {"splits": result, "limit": limit}

async def _operator_earnings_map(conn) -> dict[int, dict]:
    """Начисления, выплаты и заработок на активной смене по каждому оператору."""
    from operator_payroll_pool import backfill_accruals

    await backfill_accruals(conn)

    ledger_rows = await conn.fetch(
        """
        SELECT operator_id,
               COALESCE(SUM(amount_rub), 0)::float AS available,
               COALESCE(SUM(amount_rub) FILTER (WHERE type = 'accrual'), 0)::float AS accrued,
               COALESCE(SUM(ABS(amount_rub)) FILTER (WHERE type = 'payout'), 0)::float AS paid,
               COALESCE(SUM(ABS(amount_rub)) FILTER (WHERE type = 'penalty'), 0)::float AS penalty
        FROM operator_payroll_ledger
        WHERE operator_id IS NOT NULL
        GROUP BY operator_id
        """,
    )
    out: dict[int, dict] = {}
    for r in ledger_rows:
        oid = int(r["operator_id"])
        out[oid] = {
            "earnings_accrued_rub": round(float(r["accrued"] or 0), 2),
            "earnings_paid_rub": round(float(r["paid"] or 0), 2),
            "payroll_available_rub": round(float(r["available"] or 0), 2),
            "payroll_penalty_rub": round(float(r["penalty"] or 0), 2),
            "earnings_shift_rub": 0.0,
            "turnover_shift_rub": 0.0,
        }

    active_shifts = await conn.fetch(
        """
        SELECT s.id, s.operator_id, s.started_at, oa.percent
        FROM operator_shifts s
        JOIN operator_accounts oa ON oa.id = s.operator_id
        WHERE s.ended_at IS NULL
        """
    )
    for s in active_shifts:
        oid = int(s["operator_id"])
        st = await stats_for_operator_shift_conn(
            conn, oid, s["started_at"], None, float(s["percent"] or 0)
        )
        entry = out.setdefault(
            oid,
            {
                "earnings_accrued_rub": 0.0,
                "earnings_paid_rub": 0.0,
                "payroll_available_rub": 0.0,
                "payroll_penalty_rub": 0.0,
                "earnings_shift_rub": 0.0,
                "turnover_shift_rub": 0.0,
            },
        )
        entry["earnings_shift_rub"] = round(float(st.get("earnings_rub") or 0), 2)
        entry["turnover_shift_rub"] = round(float(st.get("fiat_total") or 0), 2)

    return out


# ---------------------------------------------------------------------------
# GET /api/admin/operators
# ---------------------------------------------------------------------------

@router.get("/operators")
async def list_operators(
    include_inactive: bool = False,
    status: Literal["active", "inactive", "all"] = Query("active"),
    search: Optional[str] = None,
    on_shift: Optional[bool] = None,
    operator_role: Optional[Literal["client", "finance"]] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    admin=Depends(get_current_admin),
):
    can_finance = can_view_finance_admin(admin)
    d_from, d_to = date_from, date_to
    if d_from is None or d_to is None:
        default_from, default_to = default_period_range(30)
        d_from = d_from or default_from
        d_to = d_to or default_to

    # Backward compat: include_inactive=true → show all statuses
    if include_inactive and status == "active":
        status = "all"

    search_pat = f"%{search.strip()}%" if search and search.strip() else None

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                oa.*,
                (SELECT COUNT(*)::int FROM operator_shifts os
                 WHERE os.operator_id = oa.id AND os.ended_at IS NULL) AS active_shifts,
                (SELECT COUNT(*)::int FROM orders o
                 WHERE o.operator_id = oa.id
                   AND o.status IN ('PAID', 'COMPLETED', 'OPERATOR_PENDING')
                   AND {moscow_date_expr('o.created_at')} = {MOSCOW_TODAY_SQL}) AS orders_today,
                (SELECT COALESCE(SUM(o.fiat_amount), 0) FROM orders o
                 WHERE o.operator_id = oa.id
                   AND o.status IN ('PAID', 'COMPLETED')
                   AND COALESCE(o.payroll_model, 'legacy') <> 'role_split'
                   AND {moscow_date_expr('o.created_at')} = {MOSCOW_TODAY_SQL}) AS fiat_today
            FROM operator_accounts oa
            WHERE (
                ($1 = 'all')
                OR ($1 = 'active' AND oa.is_active)
                OR ($1 = 'inactive' AND NOT oa.is_active)
            )
            AND (
                $2::text IS NULL
                OR oa.username ILIKE $2
                OR COALESCE(oa.display_name, '') ILIKE $2
            )
            AND (
                $3::bool IS NULL
                OR (
                    $3 = TRUE
                    AND EXISTS (
                        SELECT 1 FROM operator_shifts os
                        WHERE os.operator_id = oa.id AND os.ended_at IS NULL
                    )
                )
                OR (
                    $3 = FALSE
                    AND NOT EXISTS (
                        SELECT 1 FROM operator_shifts os
                        WHERE os.operator_id = oa.id AND os.ended_at IS NULL
                    )
                )
            )
            AND (
                $4::text IS NULL
                OR COALESCE(oa.operator_roles, ARRAY[oa.operator_role]) @> ARRAY[$4]::text[]
            )
            ORDER BY oa.id
            """,
            status,
            search_pat,
            on_shift,
            operator_role,
        )

        op_ids = [int(r["id"]) for r in rows]
        shifts_by_op: dict[int, list] = {oid: [] for oid in op_ids}
        orders_by_op: dict[int, list] = {oid: [] for oid in op_ids}

        if op_ids:
            shift_rows = await conn.fetch(
                f"""
                SELECT * FROM operator_shifts
                WHERE operator_id = ANY($1::int[])
                  AND {moscow_date_expr('started_at')} BETWEEN $2 AND $3
                """,
                op_ids,
                d_from,
                d_to,
            )
            for s in shift_rows:
                shifts_by_op[int(s["operator_id"])].append(dict(s))

            # Orders by shift completion window (+ created_at for wallet flows).
            # Include role_split assignments (intake/finance/participants), not only
            # legacy operator_id rows — otherwise period KPIs stay at 0.
            if shift_rows:
                for oid in op_ids:
                    op_shifts = shifts_by_op.get(oid) or []
                    if not op_shifts:
                        continue
                    min_start = min(s["started_at"] for s in op_shifts)
                    max_end = max(
                        (s["ended_at"] or datetime.now(timezone.utc)) for s in op_shifts
                    )
                    orders_by_op[oid] = await fetch_operator_shift_orders(
                        conn, oid, min_start, max_end
                    )
            all_order_ids = [
                str(o["order_id"])
                for rows_for_op in orders_by_op.values()
                for o in rows_for_op
                if o.get("order_id")
            ]
            accruals = await fetch_accruals_for_orders(conn, all_order_ids)
            split_earn_by_op: dict[int, dict[str, float]] = {}
            for oid in op_ids:
                op_shifts = shifts_by_op.get(oid) or []
                if not op_shifts:
                    split_earn_by_op[oid] = {}
                    continue
                min_start = min(s["started_at"] for s in op_shifts)
                max_end = max(
                    (s["ended_at"] or datetime.now(timezone.utc)) for s in op_shifts
                )
                split_earn_by_op[oid] = await fetch_role_split_earnings_by_order(
                    conn, oid, min_start, max_end
                )
        else:
            accruals = {}
            split_earn_by_op = {}

        earnings_map: dict[int, dict] = {}
        if can_finance:
            earnings_map = await _operator_earnings_map(conn)
        grade_map: dict[int, dict[str, str]] = {oid: {} for oid in op_ids}
        if op_ids:
            grade_rows = await conn.fetch(
                """
                SELECT operator_id, role, grade
                FROM operator_role_profiles
                WHERE operator_id = ANY($1::int[]) AND valid_to IS NULL
                """,
                op_ids,
            )
            for grade_row in grade_rows:
                grade_map[int(grade_row["operator_id"])][str(grade_row["role"])] = str(grade_row["grade"])
        confirm_grants = await _payout_confirm_grant_map(conn, op_ids)

    result = []
    for r in rows:
        oid = int(r["id"])
        d = _op_out(r)
        d["active_shifts"] = r["active_shifts"]
        d["on_shift"] = int(r["active_shifts"] or 0) > 0
        d["orders_today"] = r["orders_today"]
        d["fiat_today"] = float(r["fiat_today"])
        if can_finance:
            d["role_grades"] = grade_map.get(oid, {})
        roles = _normalise_roles(d.get("operator_roles"), d.get("operator_role") or "client")
        grades = grade_map.get(oid, {})
        d["payout_requisites_confirm"] = _payout_confirm_resolved(
            roles, grades, confirm_grants.get(oid)
        )
        period = compute_period_stats(
            shifts_by_op.get(oid, []),
            orders_by_op.get(oid, []),
            float(r["percent"] or 0),
            accruals,
            include_earnings=can_finance,
            role_split_earnings_by_order=split_earn_by_op.get(oid) or {},
        )
        d.update(period)
        if can_finance:
            e = earnings_map.get(
                oid,
                {
                    "earnings_accrued_rub": 0.0,
                    "earnings_paid_rub": 0.0,
                    "payroll_available_rub": 0.0,
                    "payroll_penalty_rub": 0.0,
                    "earnings_shift_rub": 0.0,
                    "turnover_shift_rub": 0.0,
                },
            )
            d.update(e)
        result.append(d)
    live_on_shift = [row for row in result if row.get("on_shift")]
    try:
        from operator_availability import evaluate_shift_gate, shift_gate_payload

        gate = evaluate_shift_gate(live_on_shift)
        shift_gate = shift_gate_payload(gate)
    except Exception:
        logger.exception("shift_gate failed; returning operators without live gate")
        shift_gate = {
            "allow": False,
            "reason": "check_failed",
            "active_count": len(live_on_shift),
            "missing_roles": ["client", "finance"],
            "telegram_user_ids": [],
            "unbound_count": 0,
        }
    return {
        "operators": result,
        "can_view_finance": can_finance,
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "shift_gate": shift_gate,
    }


# ---------------------------------------------------------------------------
# POST /api/admin/operators — создать оператора
# ---------------------------------------------------------------------------

class CreateOperatorRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    operator_roles: list[Literal["client", "finance"]] = Field(default_factory=lambda: ["client"])
    operator_role: Optional[Literal["client", "finance"]] = None
    role_grades: dict[Literal["client", "finance"], Literal["trainee", "junior", "senior"]] = Field(default_factory=dict)
    payout_requisites_confirm: Optional[bool] = None

    @model_validator(mode="after")
    def validate_roles(self):
        try:
            self.operator_roles = _normalise_roles(self.operator_roles, self.operator_role or "client")
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return self

    @field_validator("username")
    @classmethod
    def _validate_username(cls, v: str) -> str:
        v = normalize_username(v)
        if not v or len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        return v

    @field_validator("password")
    @classmethod
    def _validate_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v

@router.post("/operators", status_code=201)
async def create_operator(
    body: CreateOperatorRequest,
    _admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT id FROM operator_accounts WHERE LOWER(username) = $1",
                body.username.lower(),
            )
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail="Оператор с таким логином уже существует",
                )
            pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
            row = await conn.fetchrow(
                """
                INSERT INTO operator_accounts (username, display_name, password_hash, percent, operator_role, operator_roles)
                VALUES ($1, $2, $3, 0, $4, $5)
                RETURNING *
                """,
                body.username,
                body.display_name or body.username,
                pw_hash,
                _legacy_role(body.operator_roles),
                body.operator_roles,
            )
            await _sync_operator_role_profiles(
                conn,
                int(row["id"]),
                body.operator_roles,
                body.role_grades,
                _admin.get("id"),
            )
            if body.payout_requisites_confirm:
                await _upsert_permission_grant(
                    conn,
                    int(row["id"]),
                    PERM_PAYOUT_REQUISITES_CONFIRM,
                    True,
                )
    output = _op_out(row)
    output["role_grades"] = body.role_grades or {role: "junior" for role in body.operator_roles}
    output["payout_requisites_confirm"] = _payout_confirm_resolved(
        body.operator_roles,
        output["role_grades"],
        True if body.payout_requisites_confirm else None,
    )
    return {"operator": output}


# ---------------------------------------------------------------------------
# PATCH /api/admin/operators/{id} — изменить процент / is_active
# ---------------------------------------------------------------------------

class PatchOperatorRequest(BaseModel):
    display_name: Optional[str] = None
    operator_roles: Optional[list[Literal["client", "finance"]]] = None
    operator_role: Optional[Literal["client", "finance"]] = None
    role_grades: Optional[dict[Literal["client", "finance"], Literal["trainee", "junior", "senior"]]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    payout_requisites_confirm: Optional[bool] = None

    @model_validator(mode="after")
    def validate_roles(self):
        if self.operator_roles is not None:
            try:
                self.operator_roles = _normalise_roles(self.operator_roles)
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
        return self

@router.patch("/operators/{operator_id}")
async def patch_operator(
    operator_id: int,
    body: PatchOperatorRequest,
    _admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM operator_accounts WHERE id = $1", operator_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Оператор не найден")

        updates = {}
        if body.display_name is not None:
            updates["display_name"] = body.display_name
        requested_roles = body.operator_roles
        if requested_roles is None and body.operator_role is not None:
            requested_roles = [body.operator_role]
        old_roles = _normalise_roles(row.get("operator_roles"), row.get("operator_role") or "client")
        if requested_roles is not None:
            updates["operator_roles"] = requested_roles
            updates["operator_role"] = _legacy_role(requested_roles)
            updates["role_changed_at"] = datetime.now(timezone.utc)
            updates["role_changed_by"] = _admin.get("id")
        if body.is_active is not None:
            updates["is_active"] = body.is_active
        if body.password is not None:
            if len(body.password) < 6:
                raise HTTPException(status_code=400, detail="Password too short")
            updates["password_hash"] = bcrypt.hashpw(
                body.password.encode(), bcrypt.gensalt()
            ).decode()

        if not updates and body.role_grades is None and body.payout_requisites_confirm is None:
            output = _op_out(row)
            output["role_grades"] = await _role_grades_for_operator(conn, operator_id)
            grants = await _payout_confirm_grant_map(conn, [operator_id])
            output["payout_requisites_confirm"] = _payout_confirm_resolved(
                old_roles, output["role_grades"], grants.get(operator_id)
            )
            return {"operator": output}

        set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
        values = list(updates.values())
        updated = row
        if updates:
            updated = await conn.fetchrow(
                f"UPDATE operator_accounts SET {set_clause} WHERE id = $1 RETURNING *",
                operator_id,
                *values,
            )
        if requested_roles is not None and requested_roles != old_roles:
            await conn.execute(
                """
                INSERT INTO operator_role_audit(operator_id, old_role, new_role, changed_by, reason)
                VALUES ($1, $2, $3, $4, $5)
                """,
                operator_id, ",".join(old_roles), ",".join(requested_roles), _admin.get("id"), "admin role change",
            )
        target_roles = requested_roles or old_roles
        grades = await _sync_operator_role_profiles(
            conn,
            operator_id,
            target_roles,
            body.role_grades,
            _admin.get("id"),
        )
        grant_value = body.payout_requisites_confirm
        if grant_value is not None:
            await _upsert_permission_grant(
                conn, operator_id, PERM_PAYOUT_REQUISITES_CONFIRM, grant_value
            )
        else:
            grant_map = await _payout_confirm_grant_map(conn, [operator_id])
            grant_value = grant_map.get(operator_id)
    output = _op_out(updated)
    output["role_grades"] = grades
    output["payout_requisites_confirm"] = _payout_confirm_resolved(
        target_roles, grades, grant_value
    )
    return {"operator": output}


# ---------------------------------------------------------------------------
# GET /api/admin/operators/shifts — последние смены всех операторов
# ---------------------------------------------------------------------------

@router.get("/operators/shifts")
async def list_all_operator_shifts(
    limit: int = 50,
    offset: int = 0,
    operator_id: Optional[int] = None,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if operator_id is not None:
            op = await conn.fetchrow(
                "SELECT * FROM operator_accounts WHERE id = $1", operator_id
            )
            if not op:
                raise HTTPException(status_code=404, detail="Оператор не найден")

        shift_rows = await conn.fetch(
            f"""
            SELECT s.*, oa.username, oa.display_name, oa.percent
            FROM operator_shifts s
            JOIN operator_accounts oa ON oa.id = s.operator_id
            {"WHERE s.operator_id = $3" if operator_id is not None else ""}
            ORDER BY s.started_at DESC
            LIMIT $1 OFFSET $2
            """,
            *([limit, offset, operator_id] if operator_id is not None else [limit, offset]),
        )

        order_rows = await conn.fetch(
            """
            SELECT o.operator_id, o.intake_operator_id, o.finance_operator_id,
                   o.order_id, o.user_id, o.crypto, o.direction,
                   o.fiat_amount, o.crypto_amount, o.rate, o.status,
                   o.cashback_applied_rub, o.card_fee_pct, o.economics_snapshot,
                   o.payroll_model,
                   o.created_at, o.updated_at, o.payout_confirmed_at,
                   bu.username AS buyer_username,
                   bu.first_name AS buyer_first_name
            FROM orders o
            LEFT JOIN bot_users bu ON bu.user_id = o.user_id
            WHERE o.status IN ('PAID', 'COMPLETED')
              AND (
                o.operator_id IS NOT NULL
                OR o.intake_operator_id IS NOT NULL
                OR o.finance_operator_id IS NOT NULL
              )
              AND (
                o.created_at >= now() - interval '90 days'
                OR COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at)
                    >= now() - interval '90 days'
              )
            """
        )

        participant_rows = await conn.fetch(
            """
            SELECT p.order_id, p.operator_id
            FROM order_operator_participants p
            JOIN orders o ON o.order_id = p.order_id
            WHERE p.released_at IS NULL
              AND o.status IN ('PAID', 'COMPLETED')
              AND (
                o.created_at >= now() - interval '90 days'
                OR COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at)
                    >= now() - interval '90 days'
              )
            """
        )
        participant_ops: dict[str, set] = {}
        for p in participant_rows:
            if p.get("order_id") is not None and p.get("operator_id") is not None:
                participant_ops.setdefault(str(p["order_id"]), set()).add(int(p["operator_id"]))

        by_op_orders: dict[int, list] = {}
        for o in order_rows:
            d = dict(o)
            oid = str(d.get("order_id"))
            owners = {
                op for op in (
                    d.get("operator_id"),
                    d.get("intake_operator_id"),
                    d.get("finance_operator_id"),
                ) if op is not None
            } | participant_ops.get(oid, set())
            for op_id in owners:
                by_op_orders.setdefault(int(op_id), []).append(d)

        all_ids = [str(o["order_id"]) for o in order_rows if o.get("order_id")]
        accruals = await fetch_accruals_for_orders(conn, all_ids)

        split_earn_by_order: dict[str, float] = {}
        if all_ids:
            split_rows = await conn.fetch(
                """
                SELECT s.order_id, sl.operator_id,
                       COALESCE(SUM(sl.amount_rub), 0)::float AS amount
                FROM order_payroll_split_lines sl
                JOIN order_payroll_splits s ON s.id = sl.split_id
                WHERE s.order_id = ANY($1::text[])
                  AND sl.role <> 'unassigned'
                GROUP BY s.order_id, sl.operator_id
                """,
                all_ids,
            )
            for r in split_rows:
                split_earn_by_order[f"{r['order_id']}:{int(r['operator_id'])}"] = float(r["amount"] or 0)

        shift_ids = [s["id"] for s in shift_rows]
        usdt_by_shift: dict[int, float] = {}
        if shift_ids:
            usdt_rows = await conn.fetch(
                """
                SELECT shift_id, COALESCE(SUM(amount_usdt), 0)::float AS total
                FROM operator_usdt_issuances
                WHERE shift_id = ANY($1::int[])
                GROUP BY shift_id
                """,
                shift_ids,
            )
            for u in usdt_rows:
                usdt_by_shift[int(u["shift_id"])] = float(u["total"])

        shifts_out = []
        for s in shift_rows:
            started = s["started_at"]
            ended = s["ended_at"]
            percent = float(s["percent"] or 0)
            op_id = s["operator_id"]
            op_orders = by_op_orders.get(op_id, [])
            matched_stats = [
                o for o in op_orders if order_completed_in_shift(o, started, ended)
            ]
            split_earn = {
                str(o["order_id"]): split_earn_by_order.get(f"{o['order_id']}:{op_id}", 0.0)
                for o in matched_stats
                if o.get("order_id") is not None
            }
            st = stats_from_operator_orders(matched_stats, percent, accruals, split_earn)
            if not can_view_finance_admin(admin):
                st = strip_operator_profit_fields(st)

            def _completed_key(o: dict):
                t = operator_order_completed_at(o)
                return utc_aware(t) or datetime.min.replace(tzinfo=timezone.utc)

            shift_orders = []
            for o in sorted(matched_stats, key=_completed_key, reverse=True):
                completed = operator_order_completed_at(o)
                buyer_username = o.get("buyer_username")
                if buyer_username and not str(buyer_username).startswith("@"):
                    buyer_username = f"@{buyer_username}"
                shift_orders.append(
                    {
                        "order_id": o["order_id"],
                        "user_id": o.get("user_id"),
                        "buyer_username": buyer_username,
                        "buyer_first_name": o.get("buyer_first_name"),
                        "direction": o.get("direction"),
                        "crypto": o.get("crypto"),
                        "fiat_amount": float(o["fiat_amount"] or 0),
                        "crypto_amount": float(o["crypto_amount"] or 0)
                        if o.get("crypto_amount") is not None
                        else None,
                        "status": o.get("status"),
                        "completed_at": completed.isoformat()
                        if completed and hasattr(completed, "isoformat")
                        else completed,
                    }
                )

            usdt_total = usdt_by_shift.get(int(s["id"]), 0.0)
            shifts_out.append(
                {
                    "id": s["id"],
                    "operator_id": op_id,
                    "operator_username": s["username"],
                    "operator_display_name": s["display_name"],
                    "started_at": started.isoformat() if hasattr(started, "isoformat") else started,
                    "ended_at": ended.isoformat() if ended and hasattr(ended, "isoformat") else ended,
                    "note": s.get("note"),
                    "usdt_issued": round(usdt_total, 8) if usdt_total > 0 else None,
                    "is_active": ended is None,
                    **st,
                    "orders": shift_orders,
                }
            )

    return {
        "shifts": shifts_out,
        "limit": limit,
        "offset": offset,
        "can_view_finance": can_view_finance_admin(admin),
    }


# ---------------------------------------------------------------------------
# POST /api/admin/operators/{id}/shift/close — принудительно закрыть зависшую смену
# ---------------------------------------------------------------------------

@router.post("/operators/{operator_id}/shift/close")
async def admin_close_operator_shift(
    operator_id: int,
    _admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE operator_shifts
            SET ended_at = now(), note = COALESCE(note, '') || ' [закрыто админом]'
            WHERE operator_id = $1 AND ended_at IS NULL
            RETURNING *
            """,
            operator_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Активная смена не найдена")
        try:
            from operator_shift_store import sync_active_shift_user_ids_from_db

            await sync_active_shift_user_ids_from_db(conn)
        except Exception:
            logger.warning(
                "shift store sync after admin close failed",
                exc_info=True,
            )
        from operator_shift_notify import notify_operator_shift

        op_name = await conn.fetchval(
            "SELECT COALESCE(display_name, username) FROM operator_accounts WHERE id = $1",
            operator_id,
        )
        await notify_operator_shift(
            conn,
            operator_name=str(op_name or f"id {operator_id}"),
            action="close",
            admin_closed=True,
        )

    # Алерт отправляется только после успешного закрытия и не влияет на результат операции.
    try:
        from security_alerts import send_security_alert

        admin_identity = str(
            _admin.get("username")
            or _admin.get("display_name")
            or _admin.get("id")
            or "unknown"
        )
        send_security_alert(
            threat_type="admin_force_close_shift",
            ip="admin-action",
            path=f"/api/admin/operators/{operator_id}/shift/close",
            method="POST",
            status_code=200,
            zone="admin",
            extra={
                "severity": "high",
                "admin": f"{admin_identity} (id={_admin.get('id')})",
                "operator": str(op_name or f"id {operator_id}"),
                "operator_id": operator_id,
                "shift_id": row["id"],
            },
        )
    except Exception:
        logger.exception(
            "force-close shift security alert failed operator=%s shift=%s",
            operator_id,
            row["id"],
        )

    ended = row["ended_at"]
    return {
        "shift": {
            "id": row["id"],
            "operator_id": row["operator_id"],
            "ended_at": ended.isoformat() if ended and hasattr(ended, "isoformat") else ended,
        }
    }


# ---------------------------------------------------------------------------
# GET /api/admin/operators/{id}/stats — история смен + прибыль за период
# ---------------------------------------------------------------------------

@router.get("/operators/{operator_id}/stats")
async def operator_stats(
    operator_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        op = await conn.fetchrow(
            "SELECT * FROM operator_accounts WHERE id = $1", operator_id
        )
        if not op:
            raise HTTPException(status_code=404, detail="Оператор не найден")

        if date_from is None or date_to is None:
            d_from, d_to = default_period_range(30)
        else:
            d_from = date_from
            d_to = date_to

        shift_rows = await conn.fetch(
            f"""
            SELECT * FROM operator_shifts s
            WHERE s.operator_id = $1
              AND {moscow_date_expr('s.started_at')} BETWEEN $2 AND $3
            ORDER BY s.started_at DESC
            """,
            operator_id,
            d_from,
            d_to,
        )

        order_dicts: list[dict] = []
        split_earn: dict[str, float] = {}
        if shift_rows:
            min_start = min(s["started_at"] for s in shift_rows)
            max_end = max(
                (s["ended_at"] or datetime.now(timezone.utc)) for s in shift_rows
            )
            order_dicts = await fetch_operator_shift_orders(
                conn, operator_id, min_start, max_end
            )
            split_earn = await fetch_role_split_earnings_by_order(
                conn, operator_id, min_start, max_end
            )

        percent = float(op["percent"] or 0)
        accruals = await fetch_accruals_for_orders(
            conn, [str(o["order_id"]) for o in order_dicts if o.get("order_id")]
        )

        shift_ids = [s["id"] for s in shift_rows]
        bal_by_shift: dict[int, list] = {}
        if shift_ids:
            bal_rows = await conn.fetch(
                """
                SELECT shift_id, crypto, balance_start, balance_end
                FROM operator_shift_balances
                WHERE shift_id = ANY($1::int[])
                ORDER BY shift_id, crypto
                """,
                shift_ids,
            )
            for b in bal_rows:
                bal_by_shift.setdefault(b["shift_id"], []).append(dict(b))

        shifts_out = []
        shifts_for_balances = []
        total_orders = 0
        total_fiat = 0.0
        total_profit = 0.0
        total_earnings = 0.0

        for s in shift_rows:
            matched = match_orders_to_shift(order_dicts, s)
            matched_flow = match_orders_to_shift_by_created(order_dicts, s)
            st = stats_from_operator_orders(matched, percent, accruals, split_earn)
            total_orders += st["orders_count"]
            total_fiat += st["fiat_total"]
            total_profit += st["profit_rub"]
            total_earnings += st["earnings_rub"]

            balance_summary = compute_balance_summary(
                bal_by_shift.get(s["id"], []), matched_flow
            )
            shifts_for_balances.append(
                {
                    "id": s["id"],
                    "started_at": s["started_at"],
                    "ended_at": s["ended_at"],
                    "balance_summary": balance_summary,
                }
            )

            d = dict(s)
            for k in ("started_at", "ended_at"):
                v = d.get(k)
                if v and hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            shift_data = dict(st)
            if not can_view_finance_admin(admin):
                shift_data = strip_operator_profit_fields(shift_data)
                shift_data.pop("earnings_rub", None)
            d.update(shift_data)
            d["balance_summary"] = balance_summary
            shifts_out.append(d)

        can_finance = can_view_finance_admin(admin)
        daily, summary = build_daily_stats(
            [dict(s) for s in shift_rows],
            order_dicts,
            percent,
            accruals,
            d_from,
            d_to,
            include_earnings=can_finance,
            role_split_earnings_by_order=split_earn,
        )

        from operator_balance_fiat import enrich_balance_summary, market_prices_rub

        market = await market_prices_rub()
        for sh in shifts_for_balances:
            if sh["balance_summary"]:
                sh["balance_summary"] = enrich_balance_summary(
                    sh["balance_summary"], market
                )
        # Same enriched rows for shift history (shared by shift id).
        bal_enriched = {sh["id"]: sh["balance_summary"] for sh in shifts_for_balances}
        for sh in shifts_out:
            sh["balance_summary"] = bal_enriched.get(sh["id"], [])
        daily_balances = build_daily_balance_stats(shifts_for_balances, d_from, d_to)

        payroll = None
        payroll_ledger: list[dict] = []
        if can_finance:
            from operator_payroll_pool import (
                backfill_accruals,
                operator_payroll_snapshot,
                serialize_payroll_ledger_row,
            )

            await backfill_accruals(conn)
            payroll = await operator_payroll_snapshot(conn, operator_id)
            ledger_rows = await conn.fetch(
                """
                SELECT id, type, amount_rub, shift_id, note, created_at
                FROM operator_payroll_ledger
                WHERE operator_id = $1
                ORDER BY created_at DESC, id DESC
                LIMIT 30
                """,
                operator_id,
            )
            payroll_ledger = [serialize_payroll_ledger_row(r) for r in ledger_rows]

    totals = {
        "orders": total_orders,
        "fiat": round(total_fiat, 2),
    }
    if can_finance:
        totals["earnings_rub"] = round(total_earnings, 2)
        totals["profit_rub"] = round(total_profit, 2)

    out = {
        "operator": _op_out(op),
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "can_view_finance": can_finance,
        "summary": summary,
        "daily": daily,
        "daily_balances": daily_balances,
        "shifts": shifts_out,
        "totals": totals,
    }
    if can_finance:
        out["payroll"] = payroll
        out["payroll_ledger"] = payroll_ledger
    return out


class OperatorPenaltyBody(BaseModel):
    amount_rub: float = Field(..., gt=0, le=10_000_000)
    reason: str = Field(..., min_length=2, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        s = (v or "").strip()
        if len(s) < 2:
            raise ValueError("Укажите причину штрафа")
        return s


@router.post("/operators/{operator_id}/penalty")
async def operator_penalty(
    operator_id: int,
    body: OperatorPenaltyBody,
    admin=Depends(get_current_admin),
):
    if not can_view_finance_admin(admin):
        raise HTTPException(status_code=403, detail="Нет доступа к финансам")

    admin_label = str(admin.get("username") or admin.get("display_name") or admin.get("id") or "")
    from operator_payroll_pool import (
        apply_operator_penalty,
        operator_payroll_snapshot,
        serialize_payroll_ledger_row,
    )

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                row = await apply_operator_penalty(
                    conn,
                    operator_id,
                    body.amount_rub,
                    body.reason,
                    admin_label=admin_label,
                )
            except ValueError as exc:
                msg = str(exc)
                code = 404 if "не найден" in msg.lower() else 400
                raise HTTPException(status_code=code, detail=msg) from exc
            payroll = await operator_payroll_snapshot(conn, operator_id)
            op = await conn.fetchrow(
                "SELECT display_name, username, telegram_user_id FROM operator_accounts WHERE id = $1",
                operator_id,
            )

    penalty = serialize_payroll_ledger_row(row)
    tg = op["telegram_user_id"] if op else None
    if tg:
        try:
            import html as html_mod
            from telegram_notify import send_admin_message

            name = html_mod.escape(str((op["display_name"] or op["username"] or operator_id)))
            reason = html_mod.escape(body.reason)
            text = (
                f"<b>Штраф</b>\n"
                f"Оператор: {name}\n"
                f"Сумма: <b>{float(body.amount_rub):,.2f} ₽</b>\n"
                f"Причина: {reason}\n"
                f"Доступно: {payroll['available_rub']:,.2f} ₽"
            )
            await send_admin_message(text, chat_id=int(tg))
        except Exception:
            logger.exception("operator penalty telegram notify failed op=%s", operator_id)

    # Security alert для собственника
    try:
        from runtime_settings import reports_telegram_group_id

        reports_group = await reports_telegram_group_id()
        if reports_group:
            import html as html_mod

            op_name = html_mod.escape(str((op["display_name"] or op["username"] or operator_id))) if op else str(operator_id)
            admin_name = html_mod.escape(admin_label)
            alert_text = (
                f"⚠️ <b>Штраф оператору</b>\n"
                f"Админ: {admin_name}\n"
                f"Оператор: {op_name}\n"
                f"Сумма: <b>{float(body.amount_rub):,.0f} ₽</b>\n"
                f"Причина: {html_mod.escape(body.reason)}"
            )
            await send_admin_message(alert_text, chat_id=int(reports_group))
    except Exception:
        logger.exception("penalty security alert failed")

    return {"penalty": penalty, "payroll": payroll}


# ---------------------------------------------------------------------------
# GET /api/admin/operators/sla/summary — SLA метрики всех операторов
# ---------------------------------------------------------------------------

@router.get("/operators/sla/summary")
async def get_all_operators_sla_summary(
    days: int = Query(30, ge=1, le=365, description="Период в днях"),
    admin: dict = Depends(get_current_admin),
):
    """Получить SLA метрики всех активных операторов (сортировка по breach rate)."""
    from operator_stats import compute_all_operators_sla

    pool = await get_pool()
    async with pool.acquire() as conn:
        results = await compute_all_operators_sla(conn, days)

        return {
            "period_days": days,
            "operators_count": len(results),
            "operators": results,
        }


# ---------------------------------------------------------------------------
# GET /api/admin/operators/{operator_id}/sla — SLA метрики оператора
# ---------------------------------------------------------------------------

@router.get("/operators/{operator_id}/sla")
async def get_operator_sla_stats(
    operator_id: int,
    days: int = Query(30, ge=1, le=365, description="Период в днях"),
    admin: dict = Depends(get_current_admin),
):
    """Получить SLA метрики оператора: time_to_claim, time_to_complete, breach counts."""
    from operator_stats import compute_operator_sla

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Проверить что оператор существует
        op = await conn.fetchrow(
            "SELECT username, display_name FROM operator_accounts WHERE id = $1",
            operator_id,
        )
        if not op:
            raise HTTPException(status_code=404, detail="Оператор не найден")

        sla = await compute_operator_sla(conn, operator_id, days)
        sla["username"] = op["username"]
        sla["display_name"] = op.get("display_name")

        return sla
