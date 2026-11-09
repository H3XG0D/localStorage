"""Чат поддержки для кабинета оператора (те же треды, что у админа)."""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from auth import bearer_scheme, decode_token, get_current_operator, get_operator_by_id
from chat_attachments import (
    attachment_mime_type,
    resolve_attachment_path,
    save_chat_attachment,
    save_chat_image,
    verify_attachment_access_token,
)
from chat_events_hub import subscribe, unsubscribe
from chat_service import (
    admin_get_thread,
    admin_initiate_thread,
    admin_list_threads,
    admin_send_attachment,
    admin_send_image,
    admin_send_message,
    admin_send_sticker,
    admin_unread_count,
    admin_unread_counts_by_source,
    verify_attachment_access,
)
from chat_stickers import (
    add_operator_sticker_set,
    fetch_operator_sticker_sets,
    list_my_sticker_sets,
    remove_operator_sticker_set,
)
from chat_templates import (
    create_global_template,
    create_personal_template,
    delete_global_template,
    delete_personal_template,
    list_global_templates_admin,
    list_templates_for_operator,
    swap_global_template_priorities,
    update_global_template,
    update_personal_template,
)
from permissions import (
    PERM_TEMPLATES_CREATE,
    PERM_TEMPLATES_VIEW,
    enrich_operator_permissions,
    require_permission,
)

router = APIRouter()
logger = logging.getLogger("chat_operator")


class OperatorSendBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)


class OperatorStickerBody(BaseModel):
    file_id: str = Field(..., min_length=1, max_length=256)


class OperatorStickerSetBody(BaseModel):
    set_name: str = Field(..., min_length=1, max_length=256)


class QuickReplyBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=64)
    body: str = Field(..., min_length=1, max_length=2000)
    trigger_phrase: Optional[str] = Field(None, max_length=256)
    sort_order: int = Field(0, ge=0, le=9999)


class QuickReplyPatchBody(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=64)
    body: Optional[str] = Field(None, min_length=1, max_length=2000)
    trigger_phrase: Optional[str] = Field(None, max_length=256)
    sort_order: Optional[int] = Field(None, ge=0, le=9999)
    is_active: Optional[bool] = None
    version: Optional[int] = Field(None, ge=1)


class TemplateReorderBody(BaseModel):
    a_id: int = Field(..., gt=0)
    b_id: int = Field(..., gt=0)
    a_version: Optional[int] = Field(None, ge=1)
    b_version: Optional[int] = Field(None, ge=1)


class TemplateDeleteBody(BaseModel):
    version: Optional[int] = Field(None, ge=1)


async def _require_operator_scope(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    access_token: Optional[str] = Query(None),
) -> None:
    """SSE / attachment: Bearer, panel cookie, or (legacy) short-lived query token.

    Query token is accepted for backward compatibility but should not be used by
    new clients — prefer HttpOnly cookie (EventSource sends cookies same-origin).
    """
    token = None
    if credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    if not token:
        from panel_cookies import read_panel_token

        token = read_panel_token(request, "operator")
    if not token and access_token:
        token = access_token
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(token)
    if payload.get("scope") != "operator":
        raise HTTPException(status_code=403, detail="Operator access required")
    op = await get_operator_by_id(int(payload["sub"]))
    if not op or not op.get("is_active"):
        raise HTTPException(status_code=403, detail="Operator access required")


class OperatorInitiateBody(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=64)
    body: str = Field(..., min_length=1, max_length=2000)


@router.post("/chat/initiate")
async def initiate_chat(
    body: OperatorInitiateBody,
    op: dict = Depends(get_current_operator),
):
    """Оператор создаёт чат с клиентом по заявке: пишет первым.

    Находит существующий тред (по order_id, затем по владельцу заявки)
    или создаёт новый, отправляет первое сообщение. Покупатель получает
    уведомление через buyer-SSE (канал web_chat_buyer).
    """
    return await admin_initiate_thread(
        order_id=body.order_id,
        body=body.body,
        admin_user_id=int(op["id"]),
    )


@router.get("/chat/unread-count")
async def chat_unread_count(_op: dict = Depends(get_current_operator)):
    del _op
    return {"count": await admin_unread_count()}


@router.get("/chat/unread-by-source")
async def chat_unread_by_source(_op: dict = Depends(get_current_operator)):
    del _op
    return await admin_unread_counts_by_source()


@router.get("/chat/events")
async def chat_events_stream(
    _: None = Depends(_require_operator_scope),
):
    async def event_stream():
        queue = subscribe()
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    event = {"type": "new_message", **payload}
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/threads")
async def list_threads(
    unread_only: bool = False,
    source: Optional[str] = Query(None, pattern="^(web|telegram|exchanger|all)$"),
    limit: int = 50,
    offset: int = 0,
    _op: dict = Depends(get_current_operator),
):
    del _op
    source_filter = None if not source or source == "all" else source
    return await admin_list_threads(
        unread_only=unread_only,
        source_filter=source_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/chat/threads/{thread_id}")
async def get_thread(
    thread_id: int,
    before_id: int = 0,
    after_id: int = 0,
    limit: int = 100,
    _op: dict = Depends(get_current_operator),
):
    del _op
    return await admin_get_thread(
        thread_id, before_id=before_id, after_id=after_id, limit=limit
    )


@router.post("/chat/threads/{thread_id}/messages")
async def reply_thread(
    thread_id: int,
    body: OperatorSendBody,
    op: dict = Depends(get_current_operator),
):
    msg = await admin_send_message(
        thread_id,
        body.body,
        admin_user_id=int(op["id"]),
    )
    return {"message": msg}


@router.post("/chat/threads/{thread_id}/messages/image")
async def reply_image(
    thread_id: int,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    op: dict = Depends(get_current_operator),
):
    content = await file.read()
    attachment_id = save_chat_image(content, file.content_type, file.filename)
    msg = await admin_send_image(
        thread_id,
        attachment_id,
        caption=caption,
        admin_user_id=int(op["id"]),
    )
    return {"message": msg}


@router.get("/chat/sticker-sets")
async def chat_sticker_sets(op: dict = Depends(get_current_operator)):
    sets = await fetch_operator_sticker_sets(int(op["id"]))
    return {"sets": sets}


@router.get("/chat/my-sticker-sets")
async def chat_my_sticker_sets(op: dict = Depends(get_current_operator)):
    items = await list_my_sticker_sets(int(op["id"]))
    return {"items": items}


@router.post("/chat/my-sticker-sets")
async def chat_add_my_sticker_set(
    body: OperatorStickerSetBody,
    op: dict = Depends(get_current_operator),
):
    item = await add_operator_sticker_set(int(op["id"]), body.set_name)
    return {"item": item}


@router.delete("/chat/my-sticker-sets/{row_id}")
async def chat_remove_my_sticker_set(
    row_id: int,
    op: dict = Depends(get_current_operator),
):
    await remove_operator_sticker_set(int(op["id"]), row_id)
    return {"ok": True}


@router.get("/chat/quick-replies")
async def chat_quick_replies(op: dict = Depends(get_current_operator)):
    return await list_templates_for_operator(int(op["id"]))


@router.post("/chat/quick-replies")
async def chat_create_quick_reply(
    body: QuickReplyBody,
    op: dict = Depends(get_current_operator),
):
    item = await create_personal_template(
        int(op["id"]),
        title=body.title,
        body=body.body,
        trigger_phrase=body.trigger_phrase,
        sort_order=body.sort_order,
    )
    return {"item": item}


@router.patch("/chat/quick-replies/{template_id}")
async def chat_update_quick_reply(
    template_id: int,
    body: QuickReplyPatchBody,
    op: dict = Depends(get_current_operator),
):
    item = await update_personal_template(
        int(op["id"]),
        template_id,
        title=body.title,
        body=body.body,
        trigger_phrase=body.trigger_phrase,
        sort_order=body.sort_order,
        is_active=body.is_active,
        version=body.version,
    )
    return {"item": item}


@router.delete("/chat/quick-replies/{template_id}")
async def chat_delete_quick_reply(
    template_id: int,
    op: dict = Depends(get_current_operator),
):
    await delete_personal_template(int(op["id"]), template_id)
    return {"ok": True}


@router.get("/chat/templates")
async def chat_list_shared_templates(op: dict = Depends(get_current_operator)):
    """Общие шаблоны для всех операторов (scope=global)."""
    principal = await enrich_operator_permissions(op)
    require_permission(principal, PERM_TEMPLATES_VIEW)
    items = await list_global_templates_admin()
    return {
        "items": items,
        "permissions": principal["permissions"],
    }


@router.post("/chat/templates")
async def chat_create_shared_template(
    body: QuickReplyBody,
    op: dict = Depends(get_current_operator),
):
    principal = await enrich_operator_permissions(op)
    require_permission(principal, PERM_TEMPLATES_CREATE)
    try:
        item = await create_global_template(
            title=body.title,
            body=body.body,
            trigger_phrase=body.trigger_phrase,
            sort_order=body.sort_order,
            principal=principal,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("create shared template failed")
        raise HTTPException(status_code=500, detail="Не удалось сохранить шаблон")
    return {"item": item}


@router.patch("/chat/templates/{template_id}")
async def chat_update_shared_template(
    template_id: int,
    body: QuickReplyPatchBody,
    op: dict = Depends(get_current_operator),
):
    principal = await enrich_operator_permissions(op)
    try:
        item = await update_global_template(
            template_id,
            title=body.title,
            body=body.body,
            trigger_phrase=body.trigger_phrase,
            sort_order=body.sort_order,
            is_active=body.is_active,
            version=body.version,
            principal=principal,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("update shared template failed id=%s", template_id)
        raise HTTPException(status_code=500, detail="Не удалось обновить шаблон")
    return {"item": item}


@router.post("/chat/templates/reorder")
async def chat_reorder_shared_templates(
    body: TemplateReorderBody,
    op: dict = Depends(get_current_operator),
):
    principal = await enrich_operator_permissions(op)
    try:
        return await swap_global_template_priorities(
            body.a_id,
            body.b_id,
            principal=principal,
            version_a=body.a_version,
            version_b=body.b_version,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("reorder shared templates failed")
        raise HTTPException(status_code=500, detail="Не удалось изменить порядок")


@router.delete("/chat/templates/{template_id}")
async def chat_delete_shared_template(
    template_id: int,
    op: dict = Depends(get_current_operator),
    version: Optional[int] = Query(None, ge=1),
):
    principal = await enrich_operator_permissions(op)
    try:
        await delete_global_template(
            template_id,
            principal=principal,
            version=version,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("delete shared template failed id=%s", template_id)
        raise HTTPException(status_code=500, detail="Не удалось удалить шаблон")
    return {"ok": True}


@router.post("/chat/threads/{thread_id}/messages/sticker")
async def reply_sticker(
    thread_id: int,
    body: OperatorStickerBody,
    op: dict = Depends(get_current_operator),
):
    msg = await admin_send_sticker(
        thread_id,
        body.file_id,
        admin_user_id=int(op["id"]),
        operator_id=int(op["id"]),
    )
    return {"message": msg}


@router.post("/chat/threads/{thread_id}/messages/file")
async def reply_file(
    thread_id: int,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    op: dict = Depends(get_current_operator),
):
    content = await file.read()
    attachment_id, message_type = save_chat_attachment(
        content, file.content_type, file.filename
    )
    msg = await admin_send_attachment(
        thread_id,
        attachment_id,
        message_type=message_type,
        caption=caption,
        attachment_filename=file.filename,
        admin_user_id=int(op["id"]),
    )
    return {"message": msg}


@router.get("/chat/attachments/{attachment_id}")
async def get_attachment(
    attachment_id: str,
    access: Optional[str] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    if access and verify_attachment_access_token(attachment_id, access):
        pass
    else:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Not authenticated")
        payload = decode_token(credentials.credentials)
        if payload.get("scope") != "operator":
            raise HTTPException(status_code=403, detail="Operator access required")
        op = await get_operator_by_id(int(payload["sub"]))
        if not op or not op.get("is_active"):
            raise HTTPException(status_code=403, detail="Operator access required")
        await verify_attachment_access(attachment_id, admin=True)
    path = resolve_attachment_path(attachment_id)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type=attachment_mime_type(attachment_id))
