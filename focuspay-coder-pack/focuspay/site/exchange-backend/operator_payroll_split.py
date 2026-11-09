"""Role-aware operator payroll allocation and its persistence helpers."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

logger = logging.getLogger("operator_payroll_split")

CENT = Decimal("0.01")
DEFAULT_SETTINGS = {
    "operator_pool_percent": Decimal("30"),
    "client_operator_share_percent": Decimal("30"),
    "finance_operator_share_percent": Decimal("70"),
    "unassigned_policy": "ledger",
    "autopilot_presence_percent": Decimal("5"),
    "autopilot_manual_percent": Decimal("10"),
    "autopilot_hourly_enabled": False,
    "autopilot_hourly_rate_rub": Decimal("0"),
}
DEFAULT_GRADE_WEIGHTS = {
    ("client", "trainee"): Decimal("0.75"),
    ("client", "junior"): Decimal("1.00"),
    ("client", "senior"): Decimal("1.25"),
    ("finance", "trainee"): Decimal("0.75"),
    ("finance", "junior"): Decimal("1.00"),
    ("finance", "senior"): Decimal("1.25"),
}
ROLE_VALUES = {"client", "finance"}
GRADE_VALUES = {"trainee", "junior", "senior"}
GRADE_RANKS = {"trainee": Decimal("0"), "junior": Decimal("1"), "senior": Decimal("2")}
ROLE_PAIR_BASE_FINANCE_SHARE = Decimal("60")
ROLE_PAIR_GRADE_STEP = Decimal("10")
ROLE_PAIR_MIN_FINANCE_SHARE = Decimal("40")
ROLE_PAIR_MAX_FINANCE_SHARE = Decimal("80")
REQUIRED_SHIFT_ROLES = ("client", "finance")


def money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def _positive_decimal(value: Any, name: str) -> Decimal:
    parsed = Decimal(str(value))
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


def _percent(value: Any, name: str) -> Decimal:
    parsed = Decimal(str(value))
    if parsed < 0 or parsed > 100:
        raise ValueError(f"{name} must be between 0 and 100")
    return parsed


def _operator_roles(value, fallback: str = "client") -> set[str]:
    if isinstance(value, str):
        value = [value]
    roles = {str(role).strip().lower() for role in (value or [])}
    roles.intersection_update(REQUIRED_SHIFT_ROLES)
    return roles or {fallback}


def resolve_shift_role_assignments(operators: list[dict] | None) -> list[dict]:
    """Assign each active operator to one shift role where possible.

    A dual-role operator fills a role that is otherwise absent. This prevents
    the same person from being counted in both pools when a client-only
    operator is paired with a client+finance operator. A single dual-role
    operator is the only valid exception: it covers both roles and remains one
    payee for the purpose of the shift preview.
    """
    normalised: list[dict] = []
    for value in operators or []:
        item = dict(value)
        roles = _operator_roles(
            item.get("operator_roles"),
            str(item.get("operator_role") or "client"),
        )
        primary = str(item.get("operator_role") or "").strip().lower()
        if primary not in roles:
            primary = next(role for role in REQUIRED_SHIFT_ROLES if role in roles)
        item["declared_roles"] = tuple(
            role for role in REQUIRED_SHIFT_ROLES if role in roles
        )
        item["_primary_role"] = primary
        item["assigned_roles"] = []
        normalised.append(item)

    single_role_coverage = {
        role
        for item in normalised
        if len(item["declared_roles"]) == 1
        for role in item["declared_roles"]
    }
    missing_roles = [
        role for role in REQUIRED_SHIFT_ROLES if role not in single_role_coverage
    ]
    duals = [item for item in normalised if len(item["declared_roles"]) == 2]

    for item in normalised:
        if len(item["declared_roles"]) == 1:
            item["assigned_roles"] = list(item["declared_roles"])
            item["assignment_reason"] = "declared_role"

    # Give missing roles to different dual-role operators when possible. If
    # there is only one dual-role operator, it legitimately covers both.
    missing_owners: dict[str, int] = {}
    for index, role in enumerate(missing_roles):
        missing_owners[role] = min(index, len(duals) - 1) if duals else -1
    for index, item in enumerate(duals):
        assigned = [
            role
            for role in REQUIRED_SHIFT_ROLES
            if missing_owners.get(role) == index
        ]
        if not assigned:
            assigned = [item["_primary_role"]]
        item["assigned_roles"] = assigned
        item["assignment_reason"] = "missing_role" if any(
            role in missing_owners for role in assigned
        ) else "declared_role"

    for item in normalised:
        item.pop("_primary_role", None)
    return normalised


def assigned_operator_ids_for_role(operators: list[dict] | None, role: str) -> list[int]:
    """Operator ids assigned to one shift role after dual-role resolution."""
    if role not in ROLE_VALUES:
        raise ValueError(f"unsupported role: {role}")
    ids: list[int] = []
    seen: set[int] = set()
    for item in resolve_shift_role_assignments(operators):
        if role not in (item.get("assigned_roles") or []):
            continue
        operator_id = int(item["operator_id"])
        if operator_id in seen:
            continue
        seen.add(operator_id)
        ids.append(operator_id)
    return ids


def _average_grade_rank(participants: list[dict]) -> Decimal | None:
    if not participants:
        return None
    ranks = []
    for participant in participants:
        grade = str(participant.get("grade") or "junior")
        ranks.append(GRADE_RANKS.get(grade, GRADE_RANKS["junior"]))
    return sum(ranks, Decimal("0")) / Decimal(len(ranks))


def resolve_role_pair_shares(
    client_participants: list[dict] | None,
    finance_participants: list[dict] | None,
    fallback_client_share,
) -> dict:
    """Resolve the role split from active grades, with a legacy fallback.

    Equal grades start at 60/40 in favour of the finance role. Every grade
    advantage held by the finance role adds 10 percentage points to the
    finance share, producing: trainee/senior = 20/80, junior/senior = 30/70
    and senior/senior = 40/60. Configured grade coefficients are used later
    to split each role's pool between its participants and do not change this
    role-pair formula.
    """
    fallback = _percent(fallback_client_share, "client_share_percent")
    clients = client_participants or []
    finances = finance_participants or []
    client_rank = _average_grade_rank(clients)
    finance_rank = _average_grade_rank(finances)
    if client_rank is None or finance_rank is None:
        client_share = fallback
        mode = "fallback"
    else:
        finance_share = ROLE_PAIR_BASE_FINANCE_SHARE + (
            finance_rank - client_rank
        ) * ROLE_PAIR_GRADE_STEP
        finance_share = max(
            ROLE_PAIR_MIN_FINANCE_SHARE,
            min(ROLE_PAIR_MAX_FINANCE_SHARE, finance_share),
        )
        client_share = Decimal("100") - finance_share
        mode = "grade_pair"

    return {
        "client_operator_share_percent": client_share,
        "finance_operator_share_percent": Decimal("100") - client_share,
        "mode": mode,
        "client_grade_rank": client_rank,
        "finance_grade_rank": finance_rank,
        "complete": client_rank is not None and finance_rank is not None,
    }


def _normalise_participants(values, role: str, *, source: str) -> list[dict]:
    if role not in ROLE_VALUES:
        raise ValueError(f"unsupported role: {role}")

    result: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for value in values or []:
        if isinstance(value, dict):
            operator_id = value.get("operator_id", value.get("id"))
            participant_role = str(value.get("role") or role)
            grade = str(value.get("grade") or "junior")
            grade_weight = value.get("grade_weight", value.get("weight_multiplier", 1))
            weight = value.get("weight", grade_weight)
            snapshot = {
                key: value[key]
                for key in ("display_name", "username", "grade", "role")
                if value.get(key) is not None
            }
        else:
            operator_id = value
            participant_role = role
            grade = "junior"
            grade_weight = 1
            weight = 1
            snapshot = {}

        if operator_id is None:
            raise ValueError(f"{role} participant must have operator_id")
        try:
            operator_id = int(operator_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {role} participant operator_id") from exc
        if participant_role != role:
            raise ValueError(f"participant role mismatch: expected {role}")
        if grade not in GRADE_VALUES:
            raise ValueError(f"unsupported grade: {grade}")
        key = (operator_id, role)
        if key in seen:
            raise ValueError(f"duplicate participant: {operator_id}/{role}")
        seen.add(key)
        grade_weight = _positive_decimal(grade_weight, "grade_weight")
        weight = _positive_decimal(weight, "weight")
        snapshot.update(
            operator_id=operator_id,
            role=role,
            grade=grade,
            grade_weight=str(grade_weight),
            weight=str(weight),
            source=source,
        )
        result.append(
            {
                "operator_id": operator_id,
                "role": role,
                "grade": grade,
                "grade_weight": grade_weight,
                "weight": weight,
                "participant_snapshot": snapshot,
            }
        )
    return result


def _allocate(amount: Decimal, participants: list[dict], role: str) -> tuple[list[dict], Decimal]:
    if not participants:
        return [
            {
                "operator_id": None,
                "role": "unassigned",
                "unassigned_for": role,
                "amount_rub": amount,
                "weight": Decimal("0"),
                "participant_snapshot": {"role": role, "unassigned": True},
            }
        ], amount

    total_weight = sum((item["weight"] for item in participants), Decimal("0"))
    if total_weight <= 0:
        raise ValueError(f"{role} participant weights must total greater than zero")

    lines: list[dict] = []
    allocated = Decimal("0")
    for index, participant in enumerate(participants):
        value = amount - allocated if index == len(participants) - 1 else money(
            amount * participant["weight"] / total_weight
        )
        value = money(value)
        lines.append({**participant, "role": role, "amount_rub": value})
        allocated += value
    return lines, Decimal("0")


def split_pool(
    profit_rub,
    operator_pool_percent,
    client_share_percent,
    *,
    source="manual",
    intake_operator_id=None,
    client_participants=None,
    finance_participants=None,
):
    """Calculate an exact-cent split. The last participant receives rounding remainder."""
    pool_percent = _percent(operator_pool_percent, "operator_pool_percent")
    client_percent = _percent(client_share_percent, "client_share_percent")
    if client_percent > 100:
        raise ValueError("client_share_percent must be between 0 and 100")
    finance_percent = Decimal("100") - client_percent
    profit = max(Decimal("0"), money(profit_rub))
    pool = money(profit * pool_percent / Decimal("100"))
    client_pool = money(pool * client_percent / Decimal("100"))
    finance_pool = money(pool - client_pool)

    source_value = str(source or "manual")
    clients_input = client_participants
    if not clients_input and intake_operator_id is not None and source_value.startswith("manual"):
        clients_input = [intake_operator_id]
    clients = _normalise_participants(clients_input, "client", source=source_value)
    finances = _normalise_participants(finance_participants, "finance", source=source_value)
    client_lines, unassigned_client = _allocate(client_pool, clients, "client")
    finance_lines, unassigned_finance = _allocate(finance_pool, finances, "finance")
    return {
        "profit_rub": profit,
        "operator_pool_percent": pool_percent,
        "pool_rub": pool,
        "client_operator_share_percent": client_percent,
        "finance_operator_share_percent": finance_percent,
        "client_pool_rub": client_pool,
        "finance_pool_rub": finance_pool,
        "unassigned_client_pool_rub": unassigned_client,
        "unassigned_finance_pool_rub": unassigned_finance,
        "lines": client_lines + finance_lines,
    }


def _json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _row_dict(row) -> dict:
    return {str(key): _json_value(value) for key, value in dict(row).items()}


async def fetch_current_payroll_settings(conn, effective_at=None) -> dict:
    row = await conn.fetchrow(
        """
        SELECT * FROM operator_payroll_settings
        WHERE valid_from <= COALESCE($1::timestamptz, now())
          AND (valid_to IS NULL OR valid_to > COALESCE($1::timestamptz, now()))
        ORDER BY valid_from DESC, id DESC
        LIMIT 1
        """,
        effective_at,
    )
    if not row:
        return {**DEFAULT_SETTINGS, "id": None}
    data = {
        **DEFAULT_SETTINGS,
        "id": row.get("id"),
        "operator_pool_percent": Decimal(str(row["operator_pool_percent"])),
        "client_operator_share_percent": Decimal(str(row["client_operator_share_percent"])),
        "finance_operator_share_percent": Decimal(str(row["finance_operator_share_percent"])),
        "unassigned_policy": row.get("unassigned_policy") or "ledger",
        "valid_from": row.get("valid_from"),
        "valid_to": row.get("valid_to"),
    }
    if row.get("autopilot_presence_percent") is not None:
        data["autopilot_presence_percent"] = Decimal(str(row["autopilot_presence_percent"]))
    if row.get("autopilot_manual_percent") is not None:
        data["autopilot_manual_percent"] = Decimal(str(row["autopilot_manual_percent"]))
    if row.get("autopilot_hourly_enabled") is not None:
        data["autopilot_hourly_enabled"] = bool(row["autopilot_hourly_enabled"])
    if row.get("autopilot_hourly_rate_rub") is not None:
        data["autopilot_hourly_rate_rub"] = Decimal(str(row["autopilot_hourly_rate_rub"]))
    return data


async def fetch_grade_weights(conn, effective_at=None) -> dict[tuple[str, str], Decimal]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (role, grade) role, grade, weight_multiplier
        FROM operator_payroll_grade_settings
        WHERE valid_from <= COALESCE($1::timestamptz, now())
          AND (valid_to IS NULL OR valid_to > COALESCE($1::timestamptz, now()))
        ORDER BY role, grade, valid_from DESC, id DESC
        """,
        effective_at,
    )
    result = dict(DEFAULT_GRADE_WEIGHTS)
    for row in rows:
        result[(str(row["role"]), str(row["grade"]))] = Decimal(str(row["weight_multiplier"]))
    return result


async def _profile_for_operator(conn, operator_id: int, role: str, effective_at=None) -> dict:
    row = await conn.fetchrow(
        """
        SELECT p.grade, p.grade_weight, oa.username, oa.display_name
        FROM operator_accounts oa
        LEFT JOIN operator_role_profiles p
          ON p.operator_id = oa.id AND p.role = $2
         AND p.valid_from <= COALESCE($3::timestamptz, now())
         AND (p.valid_to IS NULL OR p.valid_to > COALESCE($3::timestamptz, now()))
        WHERE oa.id = $1
        ORDER BY p.valid_from DESC NULLS LAST
        LIMIT 1
        """,
        operator_id,
        role,
        effective_at,
    )
    if not row:
        return {
            "operator_id": operator_id,
            "role": role,
            "grade": "junior",
            "grade_weight": Decimal("1"),
            "weight": Decimal("1"),
            "participant_snapshot": {"operator_id": operator_id, "role": role, "grade": "junior"},
        }
    grade = str(row.get("grade") or "junior")
    weight = Decimal(str(row.get("grade_weight") or 1))
    return {
        "operator_id": operator_id,
        "role": role,
        "grade": grade,
        "grade_weight": weight,
        "weight": weight,
        "participant_snapshot": {
            "operator_id": operator_id,
            "role": role,
            "grade": grade,
            "grade_weight": float(weight),
            "username": row.get("username"),
            "display_name": row.get("display_name"),
        },
    }


async def ensure_order_participant(
    conn,
    order_id: str,
    operator_id: int,
    role: str,
    participation_type: str,
    assigned_by: int | None = None,
) -> dict:
    if role not in ROLE_VALUES:
        raise ValueError("unsupported participant role")
    if participation_type not in {"intake", "payout", "helper"}:
        raise ValueError("unsupported participation type")
    existing = await conn.fetchrow(
        """
        SELECT * FROM order_operator_participants
        WHERE order_id = $1 AND operator_id = $2 AND role = $3
          AND participation_type = $4 AND released_at IS NULL
        ORDER BY assigned_at DESC LIMIT 1
        """,
        order_id,
        operator_id,
        role,
        participation_type,
    )
    if existing:
        return dict(existing)
    operator = await conn.fetchrow(
        "SELECT id, operator_roles, operator_role FROM operator_accounts WHERE id = $1",
        operator_id,
    )
    if not operator:
        raise ValueError("operator not found")
    roles = operator.get("operator_roles") or [operator.get("operator_role") or "client"]
    if role not in roles:
        raise ValueError(f"operator {operator_id} does not have role {role}")
    participant = await _profile_for_operator(conn, operator_id, role)
    row = await conn.fetchrow(
        """
        INSERT INTO order_operator_participants (
            order_id, operator_id, role, participation_type, grade,
            grade_weight, weight, participant_snapshot, assigned_by
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
        ON CONFLICT (order_id, operator_id, role, participation_type)
        WHERE released_at IS NULL
        DO NOTHING
        RETURNING *
        """,
        order_id,
        operator_id,
        role,
        participation_type,
        participant["grade"],
        participant["grade_weight"],
        participant["weight"],
        json.dumps(participant["participant_snapshot"]),
        assigned_by,
    )
    if row:
        return dict(row)
    row = await conn.fetchrow(
        """
        SELECT * FROM order_operator_participants
        WHERE order_id = $1 AND operator_id = $2 AND role = $3
          AND participation_type = $4 AND released_at IS NULL
        ORDER BY assigned_at DESC LIMIT 1
        """,
        order_id,
        operator_id,
        role,
        participation_type,
    )
    return dict(row) if row else participant


async def _order_participants(conn, order: dict, effective_at=None) -> tuple[list[dict], list[dict]]:
    rows = await conn.fetch(
        """
        SELECT p.*, oa.username, oa.display_name
        FROM order_operator_participants p
        JOIN operator_accounts oa ON oa.id = p.operator_id
        WHERE p.order_id = $1 AND p.released_at IS NULL
        ORDER BY p.role, p.assigned_at, p.id
        """,
        order["order_id"],
    )
    by_role = {"client": [], "finance": []}
    for row in rows:
        snapshot = row.get("participant_snapshot") or {}
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        snapshot = dict(snapshot) if isinstance(snapshot, dict) else {}
        snapshot.update(
            operator_id=int(row["operator_id"]),
            role=str(row["role"]),
            grade=str(row["grade"]),
            grade_weight=float(row["grade_weight"]),
            weight=float(row["weight"]),
            username=row.get("username"),
            display_name=row.get("display_name"),
        )
        by_role[str(row["role"])].append(
            {
                "operator_id": int(row["operator_id"]),
                "role": str(row["role"]),
                "grade": str(row["grade"]),
                "grade_weight": Decimal(str(row["grade_weight"])),
                "weight": Decimal(str(row["weight"])),
                "participant_snapshot": snapshot,
            }
        )

    # Older role-split rows may predate participant inserts. Reconstruct only
    # from the explicit role columns; never treat a legacy operator_id as both roles.
    if not by_role["client"] and order.get("intake_operator_id"):
        by_role["client"].append(
            await _profile_for_operator(conn, int(order["intake_operator_id"]), "client", effective_at)
        )
    if not by_role["finance"] and order.get("finance_operator_id"):
        by_role["finance"].append(
            await _profile_for_operator(conn, int(order["finance_operator_id"]), "finance", effective_at)
        )
    return by_role["client"], by_role["finance"]


async def fetch_operators_on_shift_at(conn, at=None) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (oa.id)
               oa.id AS operator_id, oa.username, oa.display_name,
               oa.operator_role, oa.operator_roles
        FROM operator_shifts s
        JOIN operator_accounts oa ON oa.id = s.operator_id
        WHERE oa.is_active
          AND s.started_at <= COALESCE($1::timestamptz, now())
          AND (s.ended_at IS NULL OR s.ended_at >= COALESCE($1::timestamptz, now()))
        ORDER BY oa.id
        """,
        at,
    )
    return [dict(row) for row in rows]


async def shift_assigned_role_participants(
    conn, role: str, effective_at=None
) -> list[dict]:
    operators = await fetch_operators_on_shift_at(conn, effective_at)
    result: list[dict] = []
    for operator_id in assigned_operator_ids_for_role(operators, role):
        result.append(await _profile_for_operator(conn, operator_id, role, effective_at))
    return result


async def attach_shift_clients_if_missing(conn, order: dict, effective_at=None) -> list[dict]:
    """Freeze on-shift client operators onto bot/unclaimed orders before split."""
    clients, _finances = await _order_participants(conn, order, effective_at)
    if clients or order.get("intake_operator_id"):
        return clients
    attached: list[dict] = []
    for item in await shift_assigned_role_participants(conn, "client", effective_at):
        await ensure_order_participant(
            conn,
            str(order["order_id"]),
            int(item["operator_id"]),
            "client",
            "helper",
            None,
        )
        attached.append(item)
    return attached


async def assign_unassigned_client_pool_to_operator(
    conn,
    *,
    operator_id: int,
    order_ids: list[str],
) -> dict:
    """Move frozen unassigned client lines onto one operator and accrue them."""
    if not order_ids:
        return {"orders": 0, "lines": 0, "amount_rub": 0.0}
    profile = await _profile_for_operator(conn, operator_id, "client")
    snapshot = json.dumps(profile["participant_snapshot"])
    rows = await conn.fetch(
        """
        SELECT sl.id AS line_id, sl.split_id, sl.amount_rub, sl.ledger_id, s.order_id
        FROM order_payroll_split_lines sl
        JOIN order_payroll_splits s ON s.id = sl.split_id
        WHERE s.order_id = ANY($1::text[])
          AND sl.role = 'unassigned'
          AND sl.unassigned_for = 'client'
          AND sl.operator_id IS NULL
        ORDER BY sl.id
        """,
        order_ids,
    )
    moved = 0
    amount = Decimal("0")
    touched_splits: set[int] = set()
    for row in rows:
        line_id = int(row["line_id"])
        split_id = int(row["split_id"])
        order_id = str(row["order_id"])
        line_amount = money(row["amount_rub"])
        await ensure_order_participant(
            conn, order_id, operator_id, "client", "helper", None
        )
        updated = await conn.fetchrow(
            """
            UPDATE order_payroll_split_lines
            SET operator_id = $2, role = 'client', unassigned_for = NULL,
                weight = $3, participant_snapshot = $4::jsonb
            WHERE id = $1 AND role = 'unassigned' AND operator_id IS NULL
            RETURNING id
            """,
            line_id,
            operator_id,
            profile["weight"],
            snapshot,
        )
        if not updated:
            continue
        note = f"Распределение заявки {order_id} (client)"
        ledger_id = row["ledger_id"]
        if ledger_id:
            await conn.execute(
                """
                UPDATE operator_payroll_ledger
                SET operator_id = $2, note = $3
                WHERE id = $1 AND type = 'accrual'
                """,
                int(ledger_id),
                operator_id,
                note,
            )
        elif line_amount > 0:
            ledger = await conn.fetchrow(
                """
                INSERT INTO operator_payroll_ledger (
                    type, amount_rub, operator_id, payroll_split_line_id, note
                ) VALUES ('accrual', $1, $2, $3, $4)
                RETURNING id
                """,
                line_amount,
                operator_id,
                line_id,
                note,
            )
            ledger_id = int(ledger["id"]) if ledger else None
            if ledger_id:
                await conn.execute(
                    "UPDATE order_payroll_split_lines SET ledger_id = $2 WHERE id = $1",
                    line_id,
                    ledger_id,
                )
        await conn.execute(
            """
            UPDATE order_payroll_splits
            SET unassigned_client_pool_rub = GREATEST(0, unassigned_client_pool_rub - $2)
            WHERE id = $1
            """,
            split_id,
            line_amount,
        )
        touched_splits.add(split_id)
        moved += 1
        amount += line_amount
    return {
        "orders": len({str(row["order_id"]) for row in rows}),
        "lines": moved,
        "amount_rub": float(amount),
        "splits": len(touched_splits),
    }


def primary_pay_role(operator: dict) -> str:
    """Grade weight for the presence pool uses the operator's main role."""
    raw_roles = operator.get("operator_roles") or []
    if isinstance(raw_roles, str):
        raw_roles = [raw_roles]
    roles = {str(role).strip().lower() for role in raw_roles}
    roles.intersection_update(ROLE_VALUES)
    primary = str(operator.get("operator_role") or "").strip().lower()
    if primary in ROLE_VALUES and (not roles or primary in roles):
        return primary
    if "client" in roles:
        return "client"
    if "finance" in roles:
        return "finance"
    return "client"


def order_autopilot_paid(order: dict) -> bool:
    """True when autopilot both served the order and confirmed the payout."""
    if not order.get("auto_served"):
        return False
    return str(order.get("payout_confirmed_by") or "").strip().lower() == "auto"


def _allocate_keep_roles(amount: Decimal, participants: list[dict]) -> list[dict]:
    total_weight = sum((item["weight"] for item in participants), Decimal("0"))
    if total_weight <= 0:
        raise ValueError("participant weights must total greater than zero")
    lines: list[dict] = []
    allocated = Decimal("0")
    for index, participant in enumerate(participants):
        value = amount - allocated if index == len(participants) - 1 else money(
            amount * participant["weight"] / total_weight
        )
        value = money(value)
        role = str(participant.get("role") or "client")
        if role not in ROLE_VALUES:
            role = "client"
        lines.append({**participant, "role": role, "amount_rub": value})
        allocated += value
    return lines


def _pool_shell(profit: Decimal, percent: Decimal, *, pay_mode: str) -> dict:
    return {
        "pay_mode": pay_mode,
        "profit_rub": profit,
        "operator_pool_percent": percent,
        "pool_rub": Decimal("0"),
        "house_retained_rub": Decimal("0"),
        "client_operator_share_percent": Decimal("0"),
        "finance_operator_share_percent": Decimal("0"),
        "client_pool_rub": Decimal("0"),
        "finance_pool_rub": Decimal("0"),
        "unassigned_client_pool_rub": Decimal("0"),
        "unassigned_finance_pool_rub": Decimal("0"),
        "lines": [],
    }


def _drop_unassigned(result: dict) -> dict:
    """Autopilot leftovers stay with the house and cannot be claimed later."""
    kept = [
        line for line in result.get("lines") or []
        if line.get("operator_id") is not None and line.get("role") != "unassigned"
    ]
    dropped = money(sum(
        (money(line.get("amount_rub")) for line in result.get("lines") or [] if line not in kept),
        Decimal("0"),
    ))
    client_pool = money(sum(
        (money(line["amount_rub"]) for line in kept if line["role"] == "client"),
        Decimal("0"),
    ))
    finance_pool = money(sum(
        (money(line["amount_rub"]) for line in kept if line["role"] == "finance"),
        Decimal("0"),
    ))
    retained = money(Decimal(str(result.get("house_retained_rub") or 0)) + dropped)
    return {
        **result,
        "lines": kept,
        "client_pool_rub": client_pool,
        "finance_pool_rub": finance_pool,
        "pool_rub": money(client_pool + finance_pool),
        "house_retained_rub": retained,
        "unassigned_client_pool_rub": Decimal("0"),
        "unassigned_finance_pool_rub": Decimal("0"),
    }


def split_presence_pool(profit_rub, presence_percent, participants: list[dict] | None) -> dict:
    """One presence fund, split by grade weight. Nobody on shift means the house keeps it."""
    percent = _percent(presence_percent, "autopilot_presence_percent")
    profit = max(Decimal("0"), money(profit_rub))
    theoretical = money(profit * percent / Decimal("100"))
    people = list(participants or [])
    result = _pool_shell(profit, percent, pay_mode="autopilot_presence")
    if not people:
        result["house_retained_rub"] = theoretical
        return result
    lines = _allocate_keep_roles(theoretical, people)
    result["lines"] = lines
    return _drop_unassigned(result)


def split_autopilot_manual(
    profit_rub,
    manual_percent,
    clients,
    finances,
    *,
    source="manual",
    intake_operator_id=None,
    fallback_client_share=Decimal("30"),
) -> dict:
    """Manual percent goes only to this order's participants, not the whole shift."""
    percent = _percent(manual_percent, "autopilot_manual_percent")
    profit = max(Decimal("0"), money(profit_rub))
    theoretical = money(profit * percent / Decimal("100"))
    client_rows = list(clients or [])
    finance_rows = list(finances or [])
    if client_rows and finance_rows:
        shares = resolve_role_pair_shares(client_rows, finance_rows, fallback_client_share)
        result = split_pool(
            profit,
            percent,
            shares["client_operator_share_percent"],
            source=source,
            intake_operator_id=intake_operator_id,
            client_participants=client_rows,
            finance_participants=finance_rows,
        )
        result["pay_mode"] = "autopilot_manual"
        result["house_retained_rub"] = Decimal("0")
        return _drop_unassigned(result)
    people = client_rows or finance_rows
    role = "client" if client_rows else "finance"
    result = _pool_shell(profit, percent, pay_mode="autopilot_manual")
    if not people:
        result["house_retained_rub"] = theoretical
        return result
    result["lines"] = _allocate(theoretical, people, role)[0]
    return _drop_unassigned(result)


def calculate_order_pay(
    profit_rub,
    settings: dict,
    *,
    autopilot_on: bool,
    autopilot_paid: bool,
    clients=None,
    finances=None,
    shift_participants=None,
    source="manual",
    intake_operator_id=None,
) -> dict | None:
    """None means the caller keeps the pre-autopilot 30% role split."""
    if not autopilot_on:
        return None
    if autopilot_paid:
        return split_presence_pool(
            profit_rub,
            settings.get("autopilot_presence_percent", DEFAULT_SETTINGS["autopilot_presence_percent"]),
            shift_participants,
        )
    return split_autopilot_manual(
        profit_rub,
        settings.get("autopilot_manual_percent", DEFAULT_SETTINGS["autopilot_manual_percent"]),
        clients,
        finances,
        source=source,
        intake_operator_id=intake_operator_id,
        fallback_client_share=settings.get(
            "client_operator_share_percent",
            DEFAULT_SETTINGS["client_operator_share_percent"],
        ),
    )


def _split_public(split: dict, lines: list[dict]) -> dict:
    return {
        key: _json_value(value)
        for key, value in split.items()
        if key not in {"settings_snapshot"}
    } | {"lines": lines, "settings_snapshot": split.get("settings_snapshot") or {}}


async def ensure_order_payroll_split(conn, order_id: str) -> dict | None:
    """Persist one order split and ledger accruals; caller must hold a transaction."""
    order = await conn.fetchrow(
        "SELECT * FROM orders WHERE order_id = $1 FOR UPDATE",
        order_id,
    )
    if not order:
        raise ValueError("order not found")
    order = dict(order)
    if order.get("payroll_split_id"):
        split = await conn.fetchrow(
            "SELECT * FROM order_payroll_splits WHERE id = $1",
            order["payroll_split_id"],
        )
        if split:
            lines = await conn.fetch("SELECT * FROM order_payroll_split_lines WHERE split_id = $1 ORDER BY id", split["id"])
            return _split_public(dict(split), [_row_dict(line) for line in lines])
    existing_split = await conn.fetchrow(
        "SELECT * FROM order_payroll_splits WHERE order_id = $1",
        order_id,
    )
    if existing_split:
        await conn.execute(
            "UPDATE orders SET payroll_split_id = $2, payroll_split_required = FALSE WHERE order_id = $1",
            order_id,
            existing_split["id"],
        )
        lines = await conn.fetch(
            "SELECT * FROM order_payroll_split_lines WHERE split_id = $1 ORDER BY id",
            existing_split["id"],
        )
        return _split_public(dict(existing_split), [_row_dict(line) for line in lines])
    from auto_settings import auto_mode_enabled

    autopilot_on = auto_mode_enabled()
    autopilot_paid = order_autopilot_paid(order)
    if (
        order.get("payroll_model") != "role_split"
        and not order.get("payroll_split_required")
        and not (autopilot_on and autopilot_paid)
    ):
        return None
    if str(order.get("status") or "").upper() not in {"PAID", "COMPLETED"}:
        return None

    effective_at = order.get("payout_confirmed_at") or order.get("updated_at") or order.get("created_at")
    settings = await fetch_current_payroll_settings(conn, effective_at)
    grade_weights = await fetch_grade_weights(conn, effective_at)
    from payroll_base import fetch_accruals_for_orders, order_payroll_base_rub

    accruals = await fetch_accruals_for_orders(conn, [str(order["order_id"])])
    profit = Decimal(str(order_payroll_base_rub(order, accruals)))
    clients: list[dict] = []
    finances: list[dict] = []
    if autopilot_on:
        if autopilot_paid:
            shift_participants = []
            for operator in await fetch_operators_on_shift_at(conn, effective_at):
                role = primary_pay_role(operator)
                shift_participants.append(
                    await _profile_for_operator(conn, int(operator["operator_id"]), role, effective_at)
                )
            calculation = split_presence_pool(
                profit,
                settings["autopilot_presence_percent"],
                shift_participants,
            )
        else:
            clients, finances = await _order_participants(conn, order, effective_at)
            if not clients and not finances and order.get("operator_id"):
                clients = [
                    await _profile_for_operator(
                        conn, int(order["operator_id"]), "client", effective_at
                    )
                ]
            calculation = split_autopilot_manual(
                profit,
                settings["autopilot_manual_percent"],
                clients,
                finances,
                source=order.get("order_source") or "manual",
                intake_operator_id=order.get("intake_operator_id"),
                fallback_client_share=settings["client_operator_share_percent"],
            )
        role_shares = {
            "mode": calculation["pay_mode"],
            "client_operator_share_percent": calculation["client_operator_share_percent"],
            "finance_operator_share_percent": calculation["finance_operator_share_percent"],
        }
        snapshot_participants = [
            item.get("participant_snapshot") or {}
            for item in calculation["lines"]
        ]
    else:
        await attach_shift_clients_if_missing(conn, order, effective_at)
        clients, finances = await _order_participants(conn, order, effective_at)
        # Participant rows freeze their own grade weight. The settings snapshot
        # still records the grade table used for audit and future reconciliation.
        role_shares = resolve_role_pair_shares(
            clients,
            finances,
            settings["client_operator_share_percent"],
        )
        calculation = split_pool(
            profit,
            settings["operator_pool_percent"],
            role_shares["client_operator_share_percent"],
            source=order.get("order_source") or "manual",
            intake_operator_id=order.get("intake_operator_id"),
            client_participants=clients,
            finance_participants=finances,
        )
        calculation["pay_mode"] = "role_split"
        snapshot_participants = [
            item["participant_snapshot"]
            for item in clients + finances
        ]
    pay_mode = str(calculation.get("pay_mode") or "role_split")
    settings_snapshot = {
        "settings_id": settings.get("id"),
        "pay_mode": pay_mode,
        "operator_pool_percent": float(settings["operator_pool_percent"]),
        "client_operator_share_percent": float(settings["client_operator_share_percent"]),
        "finance_operator_share_percent": float(settings["finance_operator_share_percent"]),
        "autopilot_presence_percent": float(settings["autopilot_presence_percent"]),
        "autopilot_manual_percent": float(settings["autopilot_manual_percent"]),
        "applied_pool_percent": float(calculation["operator_pool_percent"]),
        "house_retained_rub": float(calculation.get("house_retained_rub") or 0),
        "role_share_mode": role_shares["mode"],
        "calculated_client_operator_share_percent": float(
            role_shares["client_operator_share_percent"]
        ),
        "calculated_finance_operator_share_percent": float(
            role_shares["finance_operator_share_percent"]
        ),
        "unassigned_policy": (
            "business" if pay_mode != "role_split" else (settings.get("unassigned_policy") or "ledger")
        ),
        "grade_weights": {
            f"{role}:{grade}": float(weight)
            for (role, grade), weight in grade_weights.items()
        },
        "participants": snapshot_participants,
    }
    split = await conn.fetchrow(
        """
        INSERT INTO order_payroll_splits (
            order_id, profit_rub, operator_pool_percent, pool_rub,
            client_pool_rub, finance_pool_rub, unassigned_client_pool_rub,
            unassigned_finance_pool_rub, source, settings_id, settings_snapshot
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
        ON CONFLICT (order_id) DO UPDATE SET order_id = EXCLUDED.order_id
        RETURNING *
        """,
        order_id,
        calculation["profit_rub"],
        calculation["operator_pool_percent"],
        calculation["pool_rub"],
        calculation["client_pool_rub"],
        calculation["finance_pool_rub"],
        calculation["unassigned_client_pool_rub"],
        calculation["unassigned_finance_pool_rub"],
        order.get("order_source") or "manual",
        settings.get("id"),
        json.dumps(settings_snapshot, default=_json_value),
    )
    if not split:
        raise RuntimeError("payroll split was not persisted")
    split_id = int(split["id"])
    public_lines: list[dict] = []
    for line in calculation["lines"]:
        snapshot = line.get("participant_snapshot") or {}
        inserted = await conn.fetchrow(
            """
            INSERT INTO order_payroll_split_lines (
                split_id, operator_id, role, amount_rub, weight,
                participant_snapshot, unassigned_for
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            RETURNING *
            """,
            split_id,
            line.get("operator_id"),
            line["role"],
            line["amount_rub"],
            line.get("weight") or 0,
            json.dumps(snapshot, default=_json_value),
            line.get("unassigned_for"),
        )
        if not inserted:
            continue
        line_id = int(inserted["id"])
        ledger_id = None
        ledger_unassigned = (
            pay_mode == "role_split" and settings.get("unassigned_policy") == "ledger"
        )
        if pay_mode == "autopilot_presence":
            line_note = f"За смену · заявка {order_id}"
        elif pay_mode == "autopilot_manual":
            line_note = f"Ручная заявка · {order_id} ({line['role']})"
        else:
            line_note = f"Распределение заявки {order_id} ({line['role']})"
        if (
            line["amount_rub"] > 0
            and (
                line.get("operator_id") is not None
                or (line["role"] == "unassigned" and ledger_unassigned)
            )
        ):
            ledger = await conn.fetchrow(
                """
                INSERT INTO operator_payroll_ledger (
                    type, amount_rub, operator_id, payroll_split_line_id, note
                ) VALUES ('accrual', $1, $2, $3, $4)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                line["amount_rub"],
                line["operator_id"],
                line_id,
                line_note,
            )
            ledger_id = int(ledger["id"]) if ledger else await conn.fetchval(
                "SELECT id FROM operator_payroll_ledger WHERE payroll_split_line_id = $1",
                line_id,
            )
            await conn.execute(
                "UPDATE order_payroll_split_lines SET ledger_id = $2 WHERE id = $1",
                line_id,
                ledger_id,
            )
        public_line = _row_dict(dict(inserted))
        public_line["ledger_id"] = ledger_id
        public_lines.append(public_line)

    await conn.execute(
        """
        UPDATE orders
        SET payroll_split_id = $2, payroll_split_required = FALSE,
            payroll_model = 'role_split', updated_at = now()
        WHERE order_id = $1
        """,
        order_id,
        split_id,
    )
    return _split_public(dict(split), public_lines)


async def accrue_autopilot_paid_order(conn, order_id: str) -> dict | None:
    """Accrue presence pay after an autopilot buy payout. Idempotent.

    A failed attempt is flagged for the existing role-split backfill.
    Orders that were already paid before this scheme are not flagged.
    """
    from auto_settings import auto_mode_enabled

    if not auto_mode_enabled():
        return None
    try:
        async with conn.transaction():
            return await ensure_order_payroll_split(conn, order_id)
    except Exception:
        logger.exception("autopilot payroll split failed order=%s", order_id)
        await conn.execute(
            """
            UPDATE orders
            SET payroll_model = 'role_split',
                payroll_split_required = TRUE,
                updated_at = now()
            WHERE order_id = $1 AND payroll_split_id IS NULL
            """,
            order_id,
        )
        return None


async def backfill_operator_pending_splits(
    conn, operator_id: int, since, *, limit: int = 10
) -> int:
    """Retry role_split accrual for this operator's completed orders on the active shift."""
    rows = await conn.fetch(
        """
        SELECT o.order_id
        FROM orders o
        WHERE COALESCE(o.payroll_model, 'legacy') = 'role_split'
          AND o.payroll_split_required = TRUE
          AND o.status IN ('PAID', 'COMPLETED')
          AND COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at) >= $2::timestamptz
          AND (
            o.operator_id = $1
            OR o.intake_operator_id = $1
            OR o.finance_operator_id = $1
            OR EXISTS (
                SELECT 1 FROM order_operator_participants p
                WHERE p.order_id = o.order_id
                  AND p.operator_id = $1
                  AND p.released_at IS NULL
            )
          )
        ORDER BY COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at), o.order_id
        LIMIT $3
        """,
        operator_id,
        since,
        max(1, min(int(limit), 50)),
    )
    count = 0
    for row in rows:
        try:
            if await ensure_order_payroll_split(conn, str(row["order_id"])):
                count += 1
        except Exception:
            logger.exception(
                "operator payroll split backfill failed order=%s operator=%s",
                row["order_id"],
                operator_id,
            )
    return count


async def backfill_order_payroll_splits(conn, limit: int = 200) -> int:
    rows = await conn.fetch(
        """
        SELECT order_id FROM orders
        WHERE payroll_model = 'role_split'
          AND payroll_split_required = TRUE
          AND status IN ('PAID', 'COMPLETED')
        ORDER BY COALESCE(payout_confirmed_at, updated_at, created_at), order_id
        LIMIT $1
        """,
        max(1, min(int(limit), 1000)),
    )
    count = 0
    for row in rows:
        try:
            if await ensure_order_payroll_split(conn, str(row["order_id"])):
                count += 1
        except Exception:
            logger.exception("order payroll split backfill failed order=%s", row["order_id"])
    return count


async def on_shift_payroll_distribution(conn) -> dict:
    """Return share-only data for the operator panel; no earnings are exposed."""
    settings = await fetch_current_payroll_settings(conn)
    rows = await conn.fetch(
        """
        SELECT oa.id, oa.username, oa.display_name,
               oa.operator_role, oa.operator_roles,
               roles.role,
               COALESCE(p.grade, 'junior') AS grade,
               COALESCE(p.grade_weight, 1.0) AS grade_weight
        FROM operator_shifts s
        JOIN operator_accounts oa ON oa.id = s.operator_id AND oa.is_active
        CROSS JOIN LATERAL unnest(
            COALESCE(oa.operator_roles, ARRAY[COALESCE(oa.operator_role, 'client')])
        ) AS roles(role)
        LEFT JOIN operator_role_profiles p
          ON p.operator_id = oa.id AND p.role = roles.role AND p.valid_to IS NULL
        WHERE s.ended_at IS NULL
        ORDER BY roles.role, oa.id
        """
    )
    operators: dict[int, dict] = {}
    for row in rows:
        operator_id = int(row["id"])
        item = operators.setdefault(
            operator_id,
            {
                "operator_id": operator_id,
                "username": row.get("username"),
                "display_name": row.get("display_name") or row.get("username"),
                "operator_role": row.get("operator_role"),
                "operator_roles": row.get("operator_roles"),
                "role_profiles": {},
            },
        )
        role = str(row["role"])
        item["role_profiles"][role] = {
            "grade": str(row["grade"] or "junior"),
            "grade_weight": Decimal(str(row["grade_weight"] or 1)),
        }

    assignments = resolve_shift_role_assignments(list(operators.values()))
    participants: list[dict] = []
    totals = {"client": Decimal("0"), "finance": Decimal("0")}
    for item in assignments:
        for role in item["assigned_roles"]:
            profile = item["role_profiles"].get(role) or {
                "grade": "junior",
                "grade_weight": Decimal("1"),
            }
            weight = Decimal(str(profile["grade_weight"] or 1))
            totals[role] += weight
            participants.append(
                {
                    "operator_id": item["operator_id"],
                    "username": item.get("username"),
                    "display_name": item.get("display_name"),
                    "role": role,
                    "grade": profile["grade"],
                    "weight": float(weight),
                    "grade_weight": float(weight),
                    "declared_roles": list(item["declared_roles"]),
                    "assigned_roles": list(item["assigned_roles"]),
                    "assignment_reason": item["assignment_reason"],
                }
            )
    role_shares = resolve_role_pair_shares(
        [p for p in participants if p["role"] == "client"],
        [p for p in participants if p["role"] == "finance"],
        settings["client_operator_share_percent"],
    )
    client_share = role_shares["client_operator_share_percent"]
    finance_share = role_shares["finance_operator_share_percent"]
    for item in participants:
        role = item["role"]
        role_share = (Decimal(str(item["weight"])) / totals[role] * Decimal("100")) if totals[role] else Decimal("0")
        fund_share = role_share * (client_share if role == "client" else finance_share) / Decimal("100")
        item["role_share_percent"] = float(money(role_share))
        item["fund_share_percent"] = float(money(fund_share))

    public_participants = participants
    participant_ids = {item["operator_id"] for item in participants}
    if participant_ids and len(participant_ids) == 1 and len(participants) > 1:
        # One dual-role operator covers both pools; show one 100% payee in the
        # panel even though the internal role buckets remain auditable.
        first = participants[0]
        public_participants = [{
            **first,
            "role": "both",
            "role_share_percent": 100.0,
            "fund_share_percent": 100.0,
        }]

    from auto_settings import auto_mode_enabled

    pay_mode = "autopilot" if auto_mode_enabled() else "role_split"
    presence_participants: list[dict] = []
    if pay_mode == "autopilot" and operators:
        people: list[dict] = []
        for item in operators.values():
            role = primary_pay_role(item)
            profile = item["role_profiles"].get(role) or {
                "grade": "junior",
                "grade_weight": Decimal("1"),
            }
            people.append(
                {
                    "operator_id": item["operator_id"],
                    "username": item.get("username"),
                    "display_name": item.get("display_name"),
                    "role": role,
                    "grade": profile["grade"],
                    "weight": Decimal(str(profile["grade_weight"] or 1)),
                }
            )
        people.sort(key=lambda person: int(person["operator_id"]))
        total_weight = sum((person["weight"] for person in people), Decimal("0"))
        allocated_share = Decimal("0")
        for index, person in enumerate(people):
            if total_weight <= 0:
                share = Decimal("0")
            elif index == len(people) - 1:
                share = Decimal("100") - allocated_share
            else:
                share = money(person["weight"] / total_weight * Decimal("100"))
                allocated_share += share
            person["fund_share_percent"] = float(share)
            person["weight"] = float(person["weight"])
            presence_participants.append(person)

    public = {
        "pay_mode": pay_mode,
        "operator_pool_percent": float(settings["operator_pool_percent"]),
        "client_operator_share_percent": float(client_share),
        "finance_operator_share_percent": float(finance_share),
        "autopilot_presence_percent": float(settings["autopilot_presence_percent"]),
        "autopilot_manual_percent": float(settings["autopilot_manual_percent"]),
        "autopilot_hourly_enabled": bool(settings.get("autopilot_hourly_enabled")),
        "autopilot_hourly_rate_rub": float(settings.get("autopilot_hourly_rate_rub") or 0),
        "role_share_mode": role_shares["mode"],
        "role_pair_complete": role_shares["complete"],
        "role_share_formula": "60% + 10 п.п. за каждый уровень преимущества финансовой роли",
        "unassigned_policy": settings.get("unassigned_policy") or "ledger",
        "participants": public_participants,
        "presence_participants": presence_participants,
    }
    public["client_participants"] = [p for p in participants if p["role"] == "client"]
    public["finance_participants"] = [p for p in participants if p["role"] == "finance"]
    return public
