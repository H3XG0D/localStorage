"""Object-level RBAC/ABAC for sticker tasks (IDOR → not found)."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from permissions import (
    PERM_STICKER_AUDIT_VIEW,
    PERM_STICKER_CREATE,
    PERM_STICKER_EDIT_OWN,
    PERM_STICKER_MODERATE,
    PERM_STICKER_PUBLISH,
    PERM_STICKER_SUBMIT_REVIEW,
    PERM_STICKER_VIEW_ANY,
    PERM_STICKER_VIEW_OWN,
    has_permission,
    require_permission,
)


def _actor_id(principal: dict) -> int:
    return int(principal.get("id") or 0)


def can_view_task(principal: dict, task: dict[str, Any]) -> bool:
    if has_permission(principal, PERM_STICKER_VIEW_ANY):
        return True
    if not has_permission(principal, PERM_STICKER_VIEW_OWN):
        return False
    return int(task.get("owner_id") or 0) == _actor_id(principal)


def require_view_task(principal: dict, task: dict[str, Any] | None) -> dict[str, Any]:
    if task is None or not can_view_task(principal, task):
        # IDOR hardening: do not reveal existence
        raise HTTPException(status_code=404, detail="not_found")
    return task


def require_edit_task(principal: dict, task: dict[str, Any] | None) -> dict[str, Any]:
    task = require_view_task(principal, task)
    require_permission(principal, PERM_STICKER_EDIT_OWN)
    if has_permission(principal, PERM_STICKER_VIEW_ANY):
        return task
    if int(task.get("owner_id") or 0) != _actor_id(principal):
        raise HTTPException(status_code=404, detail="not_found")
    return task


def require_create(principal: dict) -> dict:
    return require_permission(principal, PERM_STICKER_CREATE)


def require_submit_review(principal: dict, task: dict[str, Any] | None) -> dict[str, Any]:
    task = require_edit_task(principal, task)
    require_permission(principal, PERM_STICKER_SUBMIT_REVIEW)
    return task


def require_moderate(principal: dict) -> dict:
    return require_permission(principal, PERM_STICKER_MODERATE)


def require_publish(principal: dict) -> dict:
    return require_permission(principal, PERM_STICKER_PUBLISH)


def require_audit_view(principal: dict) -> dict:
    return require_permission(principal, PERM_STICKER_AUDIT_VIEW)
