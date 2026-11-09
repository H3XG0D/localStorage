"""Check that both operator roles are represented on active shifts."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from services import config_rates
from services.operator_shift_store import (
    canonical_telegram_user_id,
    list_active_shift_user_ids,
)

logger = logging.getLogger("operator_availability")

REQUIRED_OPERATOR_ROLES = ("client", "finance")
ROLE_LABELS = {
    "client": "клиентский",
    "finance": "финансовый",
}

NO_REQUISITES_NO_SHIFT_TEXT = (
    "⚠️ <b>Сейчас нет свободных реквизитов.</b>\n\n"
    "На смене должны быть клиентский и финансовый оператор.\n"
    "Попробуйте позже через 30–60 минут."
)


def normalise_operator_roles(value, fallback: str = "client") -> set[str]:
    """Return only supported roles, preserving legacy single-role records."""
    if hasattr(value, "get"):
        roles = value.get("operator_roles")
        legacy_role = value.get("operator_role")
        if not roles:
            roles = legacy_role
        fallback = str(legacy_role or fallback)
    else:
        roles = value
    if isinstance(roles, str):
        roles = [roles]
    result = {str(role).strip().lower() for role in (roles or [])}
    result.intersection_update(REQUIRED_OPERATOR_ROLES)
    return result or {fallback}


def missing_operator_roles(shifts: Iterable) -> tuple[str, ...]:
    covered: set[str] = set()
    for shift in shifts or ():
        covered.update(normalise_operator_roles(shift))
    return tuple(role for role in REQUIRED_OPERATOR_ROLES if role not in covered)


def _shift_mapping(value) -> dict:
    if value is None:
        return {}
    if hasattr(value, "items"):
        try:
            return dict(value)
        except Exception:
            logger.debug("shift mapping dict() failed", exc_info=True)
    if hasattr(value, "get"):
        return {
            "telegram_user_id": value.get("telegram_user_id"),
            "operator_roles": value.get("operator_roles"),
            "operator_role": value.get("operator_role"),
        }
    return {}


@dataclass(frozen=True)
class ShiftGate:
    allow: bool
    reason: str
    active_count: int
    missing_roles: tuple[str, ...]
    telegram_user_ids: tuple[int, ...]
    unbound_count: int
    store_user_ids: tuple[int, ...] = ()


def evaluate_shift_gate(
    shifts: Iterable,
    *,
    failed: bool = False,
    store_user_ids: Iterable[int] | None = None,
) -> ShiftGate:
    store_ids = tuple(_canonical_unique(store_user_ids))
    if failed:
        return ShiftGate(
            allow=False,
            reason="check_failed",
            active_count=0,
            missing_roles=REQUIRED_OPERATOR_ROLES,
            telegram_user_ids=(),
            unbound_count=0,
            store_user_ids=store_ids,
        )
    rows = list(shifts or ())
    missing = missing_operator_roles(rows)
    tg_ids: list[int] = []
    unbound = 0
    for row in rows:
        cid = canonical_telegram_user_id(_shift_mapping(row).get("telegram_user_id"))
        if cid is None:
            unbound += 1
        elif cid not in tg_ids:
            tg_ids.append(cid)
    if not rows:
        reason = "no_shift"
    elif missing:
        reason = "incomplete_shift"
    else:
        reason = "ok"
    return ShiftGate(
        allow=not missing,
        reason=reason,
        active_count=len(rows),
        missing_roles=missing,
        telegram_user_ids=tuple(tg_ids),
        unbound_count=unbound,
        store_user_ids=store_ids,
    )


def _canonical_unique(values: Iterable | None) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for raw in values or ():
        cid = canonical_telegram_user_id(raw)
        if cid is None or cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


def log_shift_gate(gate: ShiftGate, *, buyer_user_id: int | None = None) -> None:
    logger.info(
        "shift_gate allow=%s reason=%s active=%s missing=%s tg_ids=%s unbound=%s store_tg=%s buyer=%s",
        gate.allow,
        gate.reason,
        gate.active_count,
        ",".join(gate.missing_roles) or "-",
        list(gate.telegram_user_ids),
        gate.unbound_count,
        list(gate.store_user_ids),
        buyer_user_id if buyer_user_id else "-",
    )


async def get_active_operator_shifts():
    from services.db import get_active_operator_shifts as fetch_shifts

    return await fetch_shifts()


async def get_shift_gate() -> ShiftGate:
    store_ids = list_active_shift_user_ids()
    try:
        shifts = await get_active_operator_shifts()
    except Exception as exc:
        logger.warning("get_shift_gate check failed: %s", exc)
        gate = evaluate_shift_gate((), failed=True, store_user_ids=store_ids)
        log_shift_gate(gate)
        return gate
    return evaluate_shift_gate(shifts, store_user_ids=store_ids)


async def get_missing_operator_roles() -> tuple[str, ...]:
    return (await get_shift_gate()).missing_roles


async def has_operator_on_shift() -> bool:
    """True only when both client and finance roles are on active shifts."""
    return (await get_shift_gate()).allow


def bypasses_operator_shift_check(user_id: int) -> bool:
    return user_id in getattr(config_rates, "TELEGRAM_ADMIN_IDS", [])


async def missing_requisite_roles(user_id: int) -> tuple[str, ...]:
    if bypasses_operator_shift_check(user_id):
        return ()
    gate = await get_shift_gate()
    if not gate.allow:
        log_shift_gate(gate, buyer_user_id=user_id)
    return gate.missing_roles


async def should_block_requisites_no_shift(user_id: int) -> bool:
    return bool(await missing_requisite_roles(user_id))
