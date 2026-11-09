"""Ops AI — чат-подсказки и задачи от оператора."""
from __future__ import annotations

import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import get_current_operator
import ops_ai_service as svc

router = APIRouter()


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


def _op_id(op: dict) -> int:
    return int(op.get("id") or op.get("operator_id") or 0)


@router.get("/ai/status")
async def ai_status(_op: dict = Depends(get_current_operator)):
    del _op
    import ops_ai_llm

    return {
        "provider": __import__("config", fromlist=["settings"]).settings.ops_ai_provider,
        "configured": ops_ai_llm.provider_configured(),
        "pending_review": await svc.pending_review_count(),
    }


@router.get("/ai/sessions")
async def ai_sessions(_op: dict = Depends(get_current_operator)):
    return {"sessions": await svc.list_sessions(_op_id(_op))}


@router.post("/ai/sessions")
async def ai_create_session(
    body: SessionCreateBody,
    _op: dict = Depends(get_current_operator),
):
    return await svc.create_session(_op_id(_op), body.title)


@router.get("/ai/sessions/{session_id}/messages")
async def ai_messages(session_id: int, _op: dict = Depends(get_current_operator)):
    sess = await svc.get_session(session_id, _op_id(_op))
    if not sess:
        raise HTTPException(404, "Чат не найден")
    return {"session": sess, "messages": await svc.list_messages(session_id, _op_id(_op))}


@router.post("/ai/sessions/{session_id}/messages")
async def ai_send(session_id: int, request: Request, _op: dict = Depends(get_current_operator)):
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
                except Exception:
                    ui = None
            # images / images[]
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
            ui = body.ui_context.model_dump(exclude_none=True) if body.ui_context else None

        return await svc.chat_send(
            operator_id=_op_id(_op),
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
    _op: dict = Depends(get_current_operator),
):
    try:
        return await svc.mark_chat_useful(
            operator_id=_op_id(_op),
            session_id=session_id,
            message_id=message_id,
            note=body.note,
        )
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/ai/tasks")
async def ai_list_my_tasks(
    status: str = Query("all"),
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    _op: dict = Depends(get_current_operator),
):
    offset = (page - 1) * limit
    return await svc.list_tasks(
        status=status if status != "all" else None,
        operator_id=_op_id(_op),
        limit=limit,
        offset=offset,
    )


@router.get("/ai/tasks/{task_id}")
async def ai_get_my_task(task_id: int, _op: dict = Depends(get_current_operator)):
    task = await svc.get_task(task_id)
    if not task or int(task.get("operator_id") or 0) != _op_id(_op):
        raise HTTPException(404, "Задача не найдена")
    return task


@router.post("/ai/tasks")
async def ai_create_task(body: DevTaskCreateBody, _op: dict = Depends(get_current_operator)):
    try:
        return await svc.create_dev_task(
            operator_id=_op_id(_op),
            request_text=body.request_text,
            priority=body.priority,
            title=body.title,
            source_session_id=body.source_session_id,
            source_message_id=body.source_message_id,
            ui_context=body.ui_context.model_dump(exclude_none=True) if body.ui_context else None,
        )
    except PermissionError as e:
        raise HTTPException(429, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class MemoryCreateBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=4000)
    kind: Literal["person", "project", "shift", "incident", "decision"] = "person"
    importance: int = Field(2, ge=1, le=5)


class DigestSettingsBody(BaseModel):
    enabled: Optional[bool] = None
    hour: Optional[int] = Field(None, ge=0, le=23)


@router.get("/ai/telegram")
async def ai_telegram_status(_op: dict = Depends(get_current_operator)):
    import ops_ai_memory

    return await ops_ai_memory.get_bind_status(_op_id(_op))


@router.post("/ai/telegram/bind-link")
async def ai_telegram_bind_link(_op: dict = Depends(get_current_operator)):
    import ops_ai_memory

    return await ops_ai_memory.create_bind_link(_op_id(_op))


@router.delete("/ai/telegram")
async def ai_telegram_unbind(_op: dict = Depends(get_current_operator)):
    import ops_ai_memory

    await ops_ai_memory.unbind_operator_telegram(_op_id(_op))
    return await ops_ai_memory.get_bind_status(_op_id(_op))


@router.patch("/ai/telegram/digest")
async def ai_telegram_digest(body: DigestSettingsBody, _op: dict = Depends(get_current_operator)):
    import ops_ai_memory

    try:
        return await ops_ai_memory.update_digest_settings(
            _op_id(_op), enabled=body.enabled, hour=body.hour
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/ai/memories")
async def ai_list_memories(
    kind: Optional[str] = Query(None),
    mine: bool = Query(True),
    limit: int = Query(40, ge=1, le=100),
    _op: dict = Depends(get_current_operator),
):
    import ops_ai_memory

    person_key = ops_ai_memory.person_key_for_operator(_op_id(_op)) if mine else None
    items = await ops_ai_memory.list_memories(
        person_key=person_key, kind=kind, limit=limit, since_days=180
    )
    if not mine and not kind:
        # общий срез: project + decision
        proj = await ops_ai_memory.list_memories(kind="project", limit=limit // 2, since_days=180)
        dec = await ops_ai_memory.list_memories(kind="decision", limit=limit // 2, since_days=180)
        items = (proj + dec)[:limit]
    return {"memories": items}


@router.post("/ai/memories")
async def ai_create_memory(body: MemoryCreateBody, _op: dict = Depends(get_current_operator)):
    import ops_ai_memory

    op_id = _op_id(_op)
    return await ops_ai_memory.add_memory(
        kind=body.kind,
        title=body.title,
        body=body.body,
        person_key=ops_ai_memory.person_key_for_operator(op_id)
        if body.kind in ("person", "shift")
        else None,
        person_label=f"op#{op_id}",
        source="manual",
        created_by_operator_id=op_id,
        importance=body.importance,
    )


class ConsentBody(BaseModel):
    scopes: list[str] = Field(default_factory=lambda: ["llm"])
    source: str = Field("ops_ui", max_length=120)


@router.get("/ai/privacy")
async def ai_privacy_status(_op: dict = Depends(get_current_operator)):
    import ops_ai_privacy
    from config import settings

    op_id = _op_id(_op)
    consent = await ops_ai_privacy.get_consent(subject_type="operator", subject_id=op_id)
    ok = await ops_ai_privacy.has_valid_consent(
        subject_type="operator", subject_id=op_id, need_scope="llm"
    )
    return {
        "consent_required_version": ops_ai_privacy.current_consent_version(),
        "has_valid_consent": ok,
        "consent": consent,
        "allow_images": bool(settings.ops_ai_allow_images),
        "audit_ttl_days": int(settings.ops_ai_audit_ttl_days),
    }


@router.post("/ai/consent")
async def ai_grant_consent(body: ConsentBody, _op: dict = Depends(get_current_operator)):
    import ops_ai_privacy

    op_id = _op_id(_op)
    return await ops_ai_privacy.record_consent(
        subject_type="operator",
        subject_id=op_id,
        scopes=body.scopes or ["llm"],
        source=body.source or "ops_ui",
        actor_id=op_id,
    )


@router.delete("/ai/consent")
async def ai_revoke_consent(_op: dict = Depends(get_current_operator)):
    import ops_ai_privacy

    n = await ops_ai_privacy.revoke_consent(
        subject_type="operator", subject_id=_op_id(_op)
    )
    return {"revoked": n}