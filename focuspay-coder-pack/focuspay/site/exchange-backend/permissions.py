"""Единая RBAC-модель: роли ADMIN/OPERATOR + атомарные permissions.

Опирается на существующие operator_roles (client/finance) и admin Telegram finance ACL.
Не дублирует auth — только матрица прав и серверные проверки.
"""
from __future__ import annotations

from typing import Iterable

from fastapi import Depends, HTTPException

# ---------------------------------------------------------------------------
# Permission catalog
# ---------------------------------------------------------------------------

PERM_TEMPLATES_VIEW = "templates.view"
PERM_TEMPLATES_CREATE = "templates.create"
PERM_TEMPLATES_EDIT_OWN = "templates.edit_own"
PERM_TEMPLATES_EDIT_ANY = "templates.edit_any"
PERM_TEMPLATES_DELETE_OWN = "templates.delete_own"
PERM_TEMPLATES_DELETE_ANY = "templates.delete_any"
PERM_TEMPLATES_EDIT_SYSTEM = "templates.edit_system"
PERM_TEMPLATES_MANAGE_PRIORITY = "templates.manage_priority"

PERM_EXTERNAL_VIEW = "external_deals.view"
PERM_EXTERNAL_CREATE = "external_deals.create"
PERM_EXTERNAL_PREVIEW = "external_deals.preview"
PERM_EXTERNAL_CONFIRM = "external_deals.confirm"
PERM_EXTERNAL_CANCEL = "external_deals.cancel"
PERM_EXTERNAL_CONFIRM_ANY = "external_deals.confirm_any"
PERM_EXTERNAL_CANCEL_ANY = "external_deals.cancel_any"

PERM_FINANCE_PAYOUT = "finance.payout"
PERM_FINANCE_ANALYTICS = "finance.analytics"
PERM_PAYOUT_REQUISITES = "payout.requisites"
PERM_PAYOUT_REQUISITES_CONFIRM = "payout.requisites.confirm"
PERM_CASINO_PAYOUT = "casino.payout"
PERM_ANTISPAM_PHRASES = "antispam.phrases"
PERM_ORDERS_HISTORY = "orders.history"

PERM_AI_AUDIT_VIEW = "ai.audit.view"
PERM_AI_AUDIT_DELETE = "ai.audit.delete"
PERM_NEWS_BROADCAST = "news.broadcast"

# Sticker AI (isolated from Ops AI) — default deny for operators.
PERM_STICKER_CREATE = "sticker.create"
PERM_STICKER_VIEW_OWN = "sticker.view_own"
PERM_STICKER_VIEW_ANY = "sticker.view_any"
PERM_STICKER_EDIT_OWN = "sticker.edit_own"
PERM_STICKER_SUBMIT_REVIEW = "sticker.submit_review"
PERM_STICKER_MODERATE = "sticker.moderate"
PERM_STICKER_PUBLISH = "sticker.publish"
PERM_STICKER_AUDIT_VIEW = "sticker.audit.view"

ALL_PERMISSIONS: frozenset[str] = frozenset(
    {
        PERM_TEMPLATES_VIEW,
        PERM_TEMPLATES_CREATE,
        PERM_TEMPLATES_EDIT_OWN,
        PERM_TEMPLATES_EDIT_ANY,
        PERM_TEMPLATES_DELETE_OWN,
        PERM_TEMPLATES_DELETE_ANY,
        PERM_TEMPLATES_EDIT_SYSTEM,
        PERM_TEMPLATES_MANAGE_PRIORITY,
        PERM_EXTERNAL_VIEW,
        PERM_EXTERNAL_CREATE,
        PERM_EXTERNAL_PREVIEW,
        PERM_EXTERNAL_CONFIRM,
        PERM_EXTERNAL_CANCEL,
        PERM_EXTERNAL_CONFIRM_ANY,
        PERM_EXTERNAL_CANCEL_ANY,
        PERM_FINANCE_PAYOUT,
        PERM_FINANCE_ANALYTICS,
        PERM_PAYOUT_REQUISITES,
        PERM_PAYOUT_REQUISITES_CONFIRM,
        PERM_CASINO_PAYOUT,
        PERM_ANTISPAM_PHRASES,
        PERM_ORDERS_HISTORY,
        PERM_AI_AUDIT_VIEW,
        PERM_AI_AUDIT_DELETE,
        PERM_NEWS_BROADCAST,
        PERM_STICKER_CREATE,
        PERM_STICKER_VIEW_OWN,
        PERM_STICKER_VIEW_ANY,
        PERM_STICKER_EDIT_OWN,
        PERM_STICKER_SUBMIT_REVIEW,
        PERM_STICKER_MODERATE,
        PERM_STICKER_PUBLISH,
        PERM_STICKER_AUDIT_VIEW,
    }
)

# Базовые права клиентского оператора (без финансов/аналитики).
_CLIENT_DEFAULT: frozenset[str] = frozenset(
    {
        PERM_TEMPLATES_VIEW,
        PERM_TEMPLATES_CREATE,
        PERM_TEMPLATES_EDIT_OWN,
        PERM_TEMPLATES_DELETE_OWN,
        PERM_TEMPLATES_MANAGE_PRIORITY,
        PERM_EXTERNAL_VIEW,
        PERM_EXTERNAL_CREATE,
        PERM_EXTERNAL_PREVIEW,
        PERM_EXTERNAL_CONFIRM,
        PERM_EXTERNAL_CANCEL,
        PERM_ANTISPAM_PHRASES,
        # Доска реквизитов: смотреть/ставить карту. «Включить»/апрув чеков — confirm.
        PERM_PAYOUT_REQUISITES,
    }
)

# Финансовый оператор: выплаты; аналитика — только явным grant / admin.
_FINANCE_DEFAULT: frozenset[str] = frozenset(
    {
        PERM_TEMPLATES_VIEW,
        PERM_EXTERNAL_VIEW,
        PERM_EXTERNAL_PREVIEW,
        PERM_FINANCE_PAYOUT,
        PERM_PAYOUT_REQUISITES,
        PERM_ANTISPAM_PHRASES,
        # confirm/cancel чужих external — только с *_any (по умолчанию нет)
    }
)

_ADMIN_DEFAULT: frozenset[str] = ALL_PERMISSIONS


def _operator_roles(operator: dict) -> set[str]:
    assigned = operator.get("operator_roles")
    if isinstance(assigned, str):
        assigned = [assigned]
    if not assigned:
        assigned = [operator.get("operator_role") or "client"]
    return {str(r) for r in assigned if r}


def permissions_for_operator_roles(roles: Iterable[str]) -> set[str]:
    out: set[str] = set()
    role_set = {str(r) for r in roles}
    if "client" in role_set:
        out |= set(_CLIENT_DEFAULT)
    if "finance" in role_set:
        out |= set(_FINANCE_DEFAULT)
    if not role_set:
        out |= set(_CLIENT_DEFAULT)
    return out


def operator_is_senior(operator: dict, grades: dict | None = None) -> bool:
    """Грейд «Старший» в любой текущей роли (client/finance)."""
    source = grades if isinstance(grades, dict) else operator.get("role_grades")
    if not isinstance(source, dict):
        return False
    return any(str(grade).strip().lower() == "senior" for grade in source.values())


def operator_is_finance_senior(operator: dict, grades: dict | None = None) -> bool:
    """Авто-право подтверждения выплат: роль finance + грейд senior."""
    if "finance" not in _operator_roles(operator):
        return False
    source = grades if isinstance(grades, dict) else operator.get("role_grades")
    if not isinstance(source, dict):
        return False
    return str(source.get("finance") or "").strip().lower() == "senior"


def _apply_grade_permissions(
    base: set[str], operator: dict, grades: dict | None = None
) -> set[str]:
    out = set(base)
    if operator_is_senior(operator, grades):
        out.add(PERM_ORDERS_HISTORY)
    if operator_is_finance_senior(operator, grades):
        out.add(PERM_PAYOUT_REQUISITES_CONFIRM)
    return out


def apply_permission_grants(base: set[str], grants: Iterable[tuple[str, bool]]) -> set[str]:
    """grants: (permission, granted). granted=False снимает право."""
    out = set(base)
    for perm, granted in grants:
        p = str(perm)
        if p not in ALL_PERMISSIONS:
            continue
        if granted:
            out.add(p)
        else:
            out.discard(p)
    return out


async def load_operator_role_grades(operator_id: int) -> dict[str, str]:
    try:
        from db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, grade
                FROM operator_role_profiles
                WHERE operator_id = $1 AND valid_to IS NULL
                """,
                int(operator_id),
            )
        return {str(r["role"]): str(r["grade"]) for r in rows}
    except Exception:
        return {}


async def load_operator_permission_grants(operator_id: int) -> list[tuple[str, bool]]:
    try:
        from db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT permission, granted
                FROM operator_permission_grants
                WHERE operator_id = $1
                """,
                int(operator_id),
            )
        return [(str(r["permission"]), bool(r["granted"])) for r in rows]
    except Exception:
        # Таблица может ещё не быть накатана — не ломаем auth.
        return []


async def resolve_operator_permissions(operator: dict) -> set[str]:
    base = permissions_for_operator_roles(_operator_roles(operator))
    grades = operator.get("role_grades")
    if not isinstance(grades, dict):
        grades = await load_operator_role_grades(int(operator["id"]))
    base = _apply_grade_permissions(base, operator, grades)
    grants = await load_operator_permission_grants(int(operator["id"]))
    return apply_permission_grants(base, grants)


def resolve_admin_permissions(admin: dict) -> set[str]:
    from finance_access import can_view_finance_admin

    perms = set(_ADMIN_DEFAULT)
    # Аналитика уже в ADMIN_DEFAULT; если когда-нибудь сузим admin —
    # can_view_finance_admin останется источником истины для finance.analytics.
    if not can_view_finance_admin(admin):
        perms.discard(PERM_FINANCE_ANALYTICS)
    return perms


def principal_permissions(principal: dict) -> set[str]:
    """Синхронный снимок: если permissions уже резолвнуты — вернуть их."""
    cached = principal.get("permissions")
    if isinstance(cached, (set, frozenset, list, tuple)):
        return set(cached)
    if principal.get("is_admin"):
        return resolve_admin_permissions(principal)
    perms = permissions_for_operator_roles(_operator_roles(principal))
    perms = _apply_grade_permissions(perms, principal)
    return perms


def has_permission(principal: dict, permission: str) -> bool:
    return permission in principal_permissions(principal)


def require_permission(principal: dict, *permissions: str) -> dict:
    """Все перечисленные permissions обязательны."""
    if not permissions:
        return principal
    have = principal_permissions(principal)
    missing = [p for p in permissions if p not in have]
    if missing:
        raise HTTPException(
            status_code=403,
            detail=f"Недостаточно прав: {', '.join(missing)}",
        )
    return principal


def require_any_permission(principal: dict, *permissions: str) -> dict:
    have = principal_permissions(principal)
    if permissions and not any(p in have for p in permissions):
        raise HTTPException(
            status_code=403,
            detail=f"Недостаточно прав: нужно одно из {', '.join(permissions)}",
        )
    return principal


def attach_operator_permissions_sync(operator: dict) -> dict:
    """Без DB grants (для тестов / hot path без await)."""
    out = dict(operator)
    perms = permissions_for_operator_roles(_operator_roles(out))
    perms = _apply_grade_permissions(perms, out)
    out["permissions"] = sorted(perms)
    out["rbac_role"] = "OPERATOR"
    return out


async def enrich_operator_permissions(operator: dict) -> dict:
    out = dict(operator)
    out["permissions"] = sorted(await resolve_operator_permissions(out))
    out["rbac_role"] = "OPERATOR"
    return out


async def enrich_admin_permissions(admin: dict) -> dict:
    out = dict(admin)
    out["permissions"] = sorted(resolve_admin_permissions(out))
    out["rbac_role"] = "ADMIN"
    return out


def RequirePermission(*permissions: str):
    """FastAPI Depends: оператор + обязательные permissions."""
    from auth import get_current_operator

    async def _dep(op: dict = Depends(get_current_operator)):
        enriched = await enrich_operator_permissions(op)
        return require_permission(enriched, *permissions)

    return _dep


def RequireAdminPermission(*permissions: str):
    from auth import get_current_admin

    async def _dep(admin: dict = Depends(get_current_admin)):
        enriched = await enrich_admin_permissions(admin)
        return require_permission(enriched, *permissions)

    return _dep
