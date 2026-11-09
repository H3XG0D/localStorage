"""Admin Sticker AI — health/list + gated mutations (isolated from Ops AI).

Permissions are enforced on every endpoint (not UI-only).
Mutations require STICKER_AI_ENABLED + STICKER_AI_MUTATIONS_ENABLED.
Publish without approve is rejected by workflow (409).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import get_current_admin
from permissions import (
    PERM_STICKER_AUDIT_VIEW,
    PERM_STICKER_CREATE,
    PERM_STICKER_EDIT_OWN,
    PERM_STICKER_MODERATE,
    PERM_STICKER_PUBLISH,
    PERM_STICKER_SUBMIT_REVIEW,
    PERM_STICKER_VIEW_ANY,
    PERM_STICKER_VIEW_OWN,
    enrich_admin_permissions,
    require_any_permission,
    require_permission,
)
from sticker_ai import runtime as sticker_runtime

router = APIRouter(prefix="/sticker-ai", tags=["Admin Sticker AI"])


async def _admin_principal(admin: dict = Depends(get_current_admin)) -> dict:
    return await enrich_admin_permissions(admin)


class CreateTaskBody(BaseModel):
    idea: str = Field(..., min_length=1, max_length=2000)
    n_variants: int = Field(2, ge=1, le=4)
    idempotency_key: str | None = Field(None, max_length=128)


class EditBody(BaseModel):
    source_asset_key: str = Field(..., min_length=1, max_length=512)
    prompt: str = Field(..., min_length=1, max_length=2000)
    mask_asset_key: str | None = Field(None, max_length=512)


class RejectBody(BaseModel):
    reason: str = Field("", max_length=500)


class GenerateBody(BaseModel):
    idempotency_key: str | None = Field(None, max_length=128)


@router.get("/health")
async def sticker_ai_health(admin: dict = Depends(_admin_principal)):
    """Always reachable for admins; reports flags and observation reasons. No secrets."""
    return sticker_runtime.health_payload(principal=admin)


@router.get("/tasks")
async def list_sticker_tasks(
    status: str = Query("all"),
    limit: int = Query(50, ge=1, le=100),
    admin: dict = Depends(_admin_principal),
):
    sticker_runtime.require_enabled()
    require_any_permission(admin, PERM_STICKER_VIEW_OWN, PERM_STICKER_VIEW_ANY)
    svc = sticker_runtime.get_service()
    return svc.list_tasks(admin, status=status, limit=limit)


@router.get("/tasks/{task_id}")
async def get_sticker_task(task_id: str, admin: dict = Depends(_admin_principal)):
    sticker_runtime.require_enabled()
    require_any_permission(admin, PERM_STICKER_VIEW_OWN, PERM_STICKER_VIEW_ANY)
    svc = sticker_runtime.get_service()
    return svc.get_task(admin, task_id)


@router.get("/tasks/{task_id}/asset")
async def get_sticker_asset(
    task_id: str,
    key: str = Query(..., min_length=1, max_length=512),
    admin: dict = Depends(_admin_principal),
):
    """Serve a generated sticker preview. ACL + task membership required. No secrets."""
    sticker_runtime.require_enabled()
    require_any_permission(admin, PERM_STICKER_VIEW_OWN, PERM_STICKER_VIEW_ANY)
    svc = sticker_runtime.get_service()
    blob, ctype = svc.get_asset(admin, task_id, key)
    return Response(
        content=blob,
        media_type=ctype,
        headers={"Cache-Control": "private, max-age=120", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/audit")
async def list_sticker_audit(
    limit: int = Query(50, ge=1, le=200),
    admin: dict = Depends(_admin_principal),
):
    sticker_runtime.require_enabled()
    require_permission(admin, PERM_STICKER_AUDIT_VIEW)
    svc = sticker_runtime.get_service()
    return svc.list_audit(admin, limit=limit)


@router.post("/tasks")
async def create_sticker_task(body: CreateTaskBody, admin: dict = Depends(_admin_principal)):
    sticker_runtime.require_mutations()
    require_permission(admin, PERM_STICKER_CREATE)
    svc = sticker_runtime.get_service()
    return svc.create_task(
        admin,
        idea=body.idea,
        n_variants=body.n_variants,
        idempotency_key=body.idempotency_key,
    )


@router.post("/tasks/{task_id}/generate")
async def generate_sticker_task(
    task_id: str,
    body: GenerateBody | None = None,
    admin: dict = Depends(_admin_principal),
):
    sticker_runtime.require_mutations()
    require_permission(admin, PERM_STICKER_EDIT_OWN)
    svc = sticker_runtime.get_service()
    return await svc.enqueue_generate(
        admin,
        task_id,
        idempotency_key=(body.idempotency_key if body else None),
    )


@router.post("/tasks/{task_id}/edit")
async def edit_sticker_task(task_id: str, body: EditBody, admin: dict = Depends(_admin_principal)):
    sticker_runtime.require_mutations()
    require_permission(admin, PERM_STICKER_EDIT_OWN)
    svc = sticker_runtime.get_service()
    return await svc.edit_variant(
        admin,
        task_id,
        source_asset_key=body.source_asset_key,
        prompt=body.prompt,
        mask_asset_key=body.mask_asset_key,
    )


@router.post("/tasks/{task_id}/submit-review")
async def submit_sticker_review(task_id: str, admin: dict = Depends(_admin_principal)):
    sticker_runtime.require_mutations()
    require_permission(admin, PERM_STICKER_SUBMIT_REVIEW)
    svc = sticker_runtime.get_service()
    return svc.submit_review(admin, task_id)


@router.post("/tasks/{task_id}/approve")
async def approve_sticker_task(task_id: str, admin: dict = Depends(_admin_principal)):
    sticker_runtime.require_mutations()
    require_permission(admin, PERM_STICKER_MODERATE)
    svc = sticker_runtime.get_service()
    return await svc.approve(admin, task_id)


@router.post("/tasks/{task_id}/reject")
async def reject_sticker_task(
    task_id: str,
    body: RejectBody | None = None,
    admin: dict = Depends(_admin_principal),
):
    sticker_runtime.require_mutations()
    require_permission(admin, PERM_STICKER_MODERATE)
    svc = sticker_runtime.get_service()
    return svc.reject(admin, task_id, reason=(body.reason if body else ""))


@router.post("/tasks/{task_id}/publish")
async def publish_sticker_task(task_id: str, admin: dict = Depends(_admin_principal)):
    """Publish only after approve. Without approve → 409 from workflow."""
    sticker_runtime.require_mutations()
    require_permission(admin, PERM_STICKER_PUBLISH)
    svc = sticker_runtime.get_service()
    return await svc.publish(admin, task_id)
