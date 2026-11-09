"""Ops AI — очередь задач для админа + чат FAB (как у оператора)."""
from __future__ import annotations

import json
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from auth import get_current_admin
import ops_ai_service as svc
from ops_ai_ui_context import UiContextValidationError, validate_ui_context

router = APIRouter()


class ReviewBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


class DoneBody(BaseModel):
    note: Optional[str] = Field(None, max_length=4000)


class UiContextBody(BaseModel):
    path: Optional[str] = Field(None, max_length=300)
    search: Optional[str] = Field(None, max_length=300)
    title: Optional[str] = Field(None, max_length=200)
    hint: Optional[str] = Field(None, max_length=500)
    order_id: Optional[str] = Field(None, max_length=64)
    client_id: Optional[int] = None


class ChatSendBody(BaseModel):
    content: str = Field("", max_length=4000)
    ui_context: Optional[UiContextBody] = None


class SessionCreateBody(BaseModel):
    title: str = Field("Чат", max_length=120)


class DevTaskCreateBody(BaseModel):
    request_text: str = Field(..., min_length=1, max_length=8000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    title: Optional[str] = Field(None, max_length=200)
    source_session_id: Optional[int] = None
    source_message_id: Optional[int] = None
    ui_context: Optional[UiContextBody] = None


class UsefulBody(BaseModel):
    note: Optional[str] = Field(None, max_length=2000)


class RegressionStartBody(BaseModel):
    """Client may attach safe observations from /x8/ai-tasks walk."""

    version: Optional[str] = Field(None, max_length=120)
    deployment_id: Optional[str] = Field(None, max_length=120)
    path: Optional[str] = Field("/x8/ai-tasks", max_length=300)
    hint: Optional[str] = Field("Очередь AI-задач", max_length=500)
    page_title: Optional[str] = Field(None, max_length=200)
    status_filter: Optional[str] = Field("review", max_length=32)
    selected_task_id: Optional[int] = None
    console_errors: list[str] = Field(default_factory=list, max_length=40)
    network_errors: list[str] = Field(default_factory=list, max_length=40)
    screenshot: Optional[str] = Field(None, max_length=4000)


class RegressionObsBody(BaseModel):
    page_title: Optional[str] = Field(None, max_length=200)
    status_filter: Optional[str] = Field(None, max_length=32)
    selected_task_id: Optional[int] = None
    console_errors: list[str] = Field(default_factory=list, max_length=40)
    network_errors: list[str] = Field(default_factory=list, max_length=40)
    screenshot: Optional[str] = Field(None, max_length=4000)


def _admin_id(admin: dict) -> int | None:
    try:
        return int(admin.get("id") or admin.get("admin_id") or 0) or None
    except (TypeError, ValueError):
        return None


def _require_admin_id(admin: dict) -> int:
    aid = _admin_id(admin)
    if not aid:
        raise HTTPException(401, "Admin re-auth required")
    return int(aid)


def _admin_chat_actor_id(admin: dict) -> int:
    """Сессии ops_ai привязаны к bigint operator_id без FK — для админа используем -id."""
    aid = _require_admin_id(admin)
    return -abs(int(aid))


def _validated_ui(ui: UiContextBody | None) -> dict[str, Any] | None:
    if not ui:
        return None
    try:
        return validate_ui_context(ui.model_dump(exclude_none=True))
    except UiContextValidationError as e:
        raise HTTPException(400, f"Invalid ui_context: {e}") from e


def _idem_header(idempotency_key: str | None) -> str | None:
    key = (idempotency_key or "").strip()
    return key[:128] if key else None


@router.get("/ai-tasks/pending-count")
async def pending_count(_admin: dict = Depends(get_current_admin)):
    del _admin
    return {"count": await svc.pending_review_count()}


@router.get("/ai-tasks")
async def list_tasks(
    status: str = Query("review"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    _admin: dict = Depends(get_current_admin),
):
    del _admin
    offset = (page - 1) * limit
    return await svc.list_tasks(
        status=None if status == "all" else status,
        limit=limit,
        offset=offset,
    )


# Regression routes BEFORE /ai-tasks/{task_id} so "regression" is not parsed as int.
@router.post("/ai-tasks/regression/start")
async def regression_start(
    body: RegressionStartBody,
    admin: dict = Depends(get_current_admin),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Запуск read-only UI-регрессии экрана /x8/ai-tasks (без Approve/Reject/Done)."""
    import ops_ai_regression as reg

    aid = _require_admin_id(admin)
    try:
        validate_ui_context(
            {"path": body.path or reg.REGRESSION_PATH, "hint": body.hint or reg.REGRESSION_HINT},
            require_path=reg.REGRESSION_PATH,
            require_hint_contains="AI-задач",
        )
    except UiContextValidationError as e:
        raise HTTPException(400, f"Regression UI context invalid: {e}") from e

    obs = {
        "path": body.path or reg.REGRESSION_PATH,
        "hint": body.hint or reg.REGRESSION_HINT,
        "page_title": body.page_title,
        "status_filter": body.status_filter or "review",
        "selected_task_id": body.selected_task_id,
        "console_errors": list(body.console_errors or [])[:40],
        "network_errors": list(body.network_errors or [])[:40],
        "screenshot": body.screenshot,
    }
    try:
        return await reg.start_run(
            admin_id=aid,
            tenant_scope="admin",
            deployment_meta={
                "version": body.version,
                "deployment_id": body.deployment_id,
            },
            client_observations=obs,
            idempotency_key=_idem_header(idempotency_key),
        )
    except PermissionError as e:
        raise HTTPException(429, str(e)) from e
    except reg.RegressionError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/ai-tasks/regression/latest")
async def regression_latest(admin: dict = Depends(get_current_admin)):
    import ops_ai_regression as reg

    aid = _require_admin_id(admin)
    run = reg.get_latest_for_admin(aid)
    if not run:
        return {"run": None, "capabilities": reg.agent_capabilities()}
    return {"run": reg._public_run(run), "capabilities": reg.agent_capabilities()}


@router.get("/ai-tasks/regression/{run_id}")
async def regression_get(run_id: str, admin: dict = Depends(get_current_admin)):
    import ops_ai_regression as reg

    aid = _require_admin_id(admin)
    run = reg.get_run(run_id, admin_id=aid)
    if not run:
        raise HTTPException(404, "Regression run not found")
    return {"run": reg._public_run(run)}


@router.get("/ai-tasks/regression/{run_id}/report")
async def regression_report(run_id: str, admin: dict = Depends(get_current_admin)):
    import ops_ai_regression as reg

    aid = _require_admin_id(admin)
    run = reg.get_run(run_id, admin_id=aid)
    if not run or not run.report:
        raise HTTPException(404, "Regression report not found")
    return run.report.to_dict()


@router.post("/ai-tasks/regression/{run_id}/observations")
async def regression_observations(
    run_id: str,
    body: RegressionObsBody,
    admin: dict = Depends(get_current_admin),
):
    import ops_ai_regression as reg

    aid = _require_admin_id(admin)
    obs = body.model_dump(exclude_none=True)
    try:
        return await reg.attach_client_observations(run_id, admin_id=aid, observations=obs)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except reg.RegressionError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/ai-tasks/selfcheck/latest")
async def selfcheck_latest(_admin: dict = Depends(get_current_admin)):
    """Latest nightly SAST run (bandit/pip-audit). Alarm statuses are not findings."""
    del _admin
    import ops_ai_selfcheck as sc

    row = await sc.get_latest()
    return {"run": sc.public_run(row)}


@router.get("/ai-tasks/selfcheck/{run_id}")
async def selfcheck_get(run_id: int, _admin: dict = Depends(get_current_admin)):
    del _admin
    import ops_ai_selfcheck as sc

    row = await sc.get_run(run_id)
    if not row:
        raise HTTPException(404, "Self-check run not found")
    return {"run": sc.public_run(row)}


@router.post("/ai-tasks/backfill-done-notify")
async def backfill_done_notify(
    limit: int = Query(100, ge=1, le=500),
    also_mark_approved: bool = Query(True),
    admin: dict = Depends(get_current_admin),
):
    """Одноразовый бэкап: mark done + notify постановщикам без done_notified_at."""
    aid = _require_admin_id(admin)
    return await svc.backfill_done_notifications(
        limit=limit,
        also_mark_approved=also_mark_approved,
        admin_id=aid,
    )


@router.get("/ai-tasks/{task_id}")
async def get_task(task_id: int, _admin: dict = Depends(get_current_admin)):
    del _admin
    task = await svc.get_task(task_id)
    if not task:
        raise HTTPException(404, "Задача не найдена")
    return task


@router.get("/ai-tasks/{task_id}/attachments/{index}")
async def get_task_attachment(
    task_id: int,
    index: int,
    _admin: dict = Depends(get_current_admin),
):
    del _admin
    try:
        path, media_type, filename = await svc.get_task_attachment_file(task_id, index)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except FileNotFoundError:
        raise HTTPException(404, "Файл отсутствует") from None
    return FileResponse(path, media_type=media_type, filename=filename)


@router.post("/ai-tasks/{task_id}/approve")
async def approve_task(
    task_id: int,
    admin: dict = Depends(get_current_admin),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    try:
        return await svc.review_task(
            task_id,
            action="approve",
            admin_id=_require_admin_id(admin),
            idempotency_key=_idem_header(idempotency_key),
        )
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except PermissionError as e:
        raise HTTPException(429, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/ai-tasks/{task_id}/reject")
async def reject_task(
    task_id: int,
    body: ReviewBody,
    admin: dict = Depends(get_current_admin),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    try:
        return await svc.review_task(
            task_id,
            action="reject",
            admin_id=_require_admin_id(admin),
            reason=body.reason,
            idempotency_key=_idem_header(idempotency_key),
        )
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except PermissionError as e:
        raise HTTPException(429, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/ai-tasks/{task_id}/done")
async def done_task(
    task_id: int,
    body: DoneBody,
    admin: dict = Depends(get_current_admin),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    try:
        return await svc.mark_task_done(
            task_id,
            note=body.note,
            admin_id=_require_admin_id(admin),
            idempotency_key=_idem_header(idempotency_key),
        )
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except PermissionError as e:
        raise HTTPException(429, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ---------------------------------------------------------------------------
# Admin chat FAB — те же сессии/LLM, что у оператора
# ---------------------------------------------------------------------------

@router.get("/ai/status")
async def ai_status(_admin: dict = Depends(get_current_admin)):
    del _admin
    import ops_ai_llm

    return {
        "provider": __import__("config", fromlist=["settings"]).settings.ops_ai_provider,
        "configured": ops_ai_llm.provider_configured(),
        "pending_review": await svc.pending_review_count(),
    }


@router.get("/ai/sessions")
async def ai_sessions(admin: dict = Depends(get_current_admin)):
    return {"sessions": await svc.list_sessions(_admin_chat_actor_id(admin))}


@router.post("/ai/sessions")
async def ai_create_session(
    body: SessionCreateBody,
    admin: dict = Depends(get_current_admin),
):
    return await svc.create_session(_admin_chat_actor_id(admin), body.title)


@router.get("/ai/sessions/{session_id}/messages")
async def ai_messages(session_id: int, admin: dict = Depends(get_current_admin)):
    actor = _admin_chat_actor_id(admin)
    sess = await svc.get_session(session_id, actor)
    if not sess:
        raise HTTPException(404, "Чат не найден")
    return {"session": sess, "messages": await svc.list_messages(session_id, actor)}


@router.post("/ai/sessions/{session_id}/messages")
async def ai_send(session_id: int, request: Request, admin: dict = Depends(get_current_admin)):
    actor = _admin_chat_actor_id(admin)
    ct = (request.headers.get("content-type") or "").lower()
    ui: dict | None = None
    content = ""
    image_files: list[tuple[bytes, str | None]] = []

    try:
        if "multipart/form-data" in ct:
            form = await request.form()
            content = str(form.get("content") or "")
            ui_raw = form.get("ui_context")
            if ui_raw:
                try:
                    parsed = json.loads(str(ui_raw))
                    if isinstance(parsed, dict):
                        ui = UiContextBody.model_validate(parsed).model_dump(exclude_none=True)
                        ui = _validated_ui(UiContextBody.model_validate(ui))
                except HTTPException:
                    raise
                except Exception:
                    ui = None
            candidates = []
            for key in form.keys():
                if key == "images" or key.startswith("images"):
                    val = form.getlist(key) if hasattr(form, "getlist") else [form.get(key)]
                    candidates.extend(val)
            seen = set()
            for item in candidates:
                if item is None or id(item) in seen:
                    continue
                seen.add(id(item))
                if hasattr(item, "read"):
                    raw = await item.read()
                    declared = getattr(item, "content_type", None)
                    if raw:
                        image_files.append((raw, declared))
        else:
            data = await request.json()
            body = ChatSendBody.model_validate(data)
            content = body.content or ""
            ui = _validated_ui(body.ui_context)

        return await svc.chat_send(
            operator_id=actor,
            session_id=session_id,
            content=content,
            ui_context=ui,
            image_files=image_files or None,
        )
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except PermissionError as e:
        raise HTTPException(429, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Не удалось разобрать запрос: {e}") from e


@router.post("/ai/sessions/{session_id}/messages/{message_id}/useful")
async def ai_mark_useful(
    session_id: int,
    message_id: int,
    body: UsefulBody,
    admin: dict = Depends(get_current_admin),
):
    try:
        return await svc.mark_chat_useful(
            operator_id=_admin_chat_actor_id(admin),
            session_id=session_id,
            message_id=message_id,
            note=body.note,
        )
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/ai/tasks")
async def ai_create_task(body: DevTaskCreateBody, admin: dict = Depends(get_current_admin)):
    """Админ создаёт задачу в ту же очередь review."""
    actor = _admin_chat_actor_id(admin)
    try:
        return await svc.create_dev_task(
            operator_id=actor,
            request_text=body.request_text,
            priority=body.priority,
            title=body.title,
            source_session_id=body.source_session_id,
            source_message_id=body.source_message_id,
            ui_context=_validated_ui(body.ui_context),
        )
    except PermissionError as e:
        raise HTTPException(429, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class ConsentBody(BaseModel):
    scopes: list[str] = Field(default_factory=lambda: ["llm"])
    source: str = Field("admin_ui", max_length=120)


@router.get("/ai/privacy")
async def ai_privacy_status(admin: dict = Depends(get_current_admin)):
    import ops_ai_privacy
    from config import settings

    actor = _admin_chat_actor_id(admin)
    consent = await ops_ai_privacy.get_consent(subject_type="operator", subject_id=actor)
    ok = await ops_ai_privacy.has_valid_consent(
        subject_type="operator", subject_id=actor, need_scope="llm"
    )
    return {
        "consent_required_version": ops_ai_privacy.current_consent_version(),
        "has_valid_consent": ok,
        "consent": consent,
        "allow_images": bool(settings.ops_ai_allow_images),
        "audit_ttl_days": int(settings.ops_ai_audit_ttl_days),
    }


@router.post("/ai/consent")
async def ai_grant_consent(body: ConsentBody, admin: dict = Depends(get_current_admin)):
    import ops_ai_privacy

    actor = _admin_chat_actor_id(admin)
    return await ops_ai_privacy.record_consent(
        subject_type="operator",
        subject_id=actor,
        scopes=body.scopes or ["llm"],
        source=body.source or "admin_ui",
        actor_id=abs(actor),
    )


@router.get("/ai/audit")
async def ai_audit_list(
    actor_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(get_current_admin),
):
    import ops_ai_audit
    from permissions import enrich_admin_permissions

    principal = await enrich_admin_permissions({**admin, "is_admin": True})
    items = await ops_ai_audit.list_events(
        principal=principal, actor_id=actor_id, limit=limit, offset=offset
    )
    return {"items": items}


@router.get("/ai/audit/{event_id}")
async def ai_audit_get(event_id: int, admin: dict = Depends(get_current_admin)):
    import ops_ai_audit
    from permissions import enrich_admin_permissions

    principal = await enrich_admin_permissions({**admin, "is_admin": True})
    return await ops_ai_audit.get_event(event_id, principal=principal)


@router.delete("/ai/audit/subject/{actor_type}/{actor_id}")
async def ai_audit_delete_subject(
    actor_type: str,
    actor_id: int,
    admin: dict = Depends(get_current_admin),
):
    import ops_ai_audit
    from permissions import PERM_AI_AUDIT_DELETE, enrich_admin_permissions, require_permission

    principal = await enrich_admin_permissions({**admin, "is_admin": True})
    require_permission(principal, PERM_AI_AUDIT_DELETE)
    n = await ops_ai_audit.delete_for_subject(
        actor_type=actor_type,
        actor_id=actor_id,
        deleted_by_type="admin",
        deleted_by_id=int(admin.get("id") or 0),
    )
    return {"deleted": n}


@router.post("/ai/audit/purge-expired")
async def ai_audit_purge(admin: dict = Depends(get_current_admin)):
    import ops_ai_audit
    from permissions import PERM_AI_AUDIT_DELETE, enrich_admin_permissions, require_permission

    principal = await enrich_admin_permissions({**admin, "is_admin": True})
    require_permission(principal, PERM_AI_AUDIT_DELETE)
    return {"purged": await ops_ai_audit.purge_expired()}