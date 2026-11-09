"""Чат поддержки для админки (те же треды, что у оператора)."""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from auth import bearer_scheme, decode_token, get_current_admin, get_web_user_by_id
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
    admin_list_threads,
    admin_send_attachment,
    admin_send_image,
    admin_send_message,
    admin_send_sticker,
    admin_unread_count,
    admin_unread_counts_by_source,
    verify_attachment_access,
)
from chat_stickers import fetch_operator_sticker_sets
from chat_templates import (
    create_global_template,
    delete_global_template,
    list_global_templates_admin,
    update_global_template,
)

router = APIRouter()


class AdminSendBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)


class AdminStickerBody(BaseModel):
    file_id: str = Field(..., min_length=1, max_length=256)


class AdminQuickReplyBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=64)
    body: str = Field(..., min_length=1, max_length=2000)
    trigger_phrase: Optional[str] = Field(None, max_length=256)
    sort_order: int = Field(0, ge=0, le=9999)


class AdminQuickReplyPatchBody(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=64)
    body: Optional[str] = Field(None, min_length=1, max_length=2000)
    trigger_phrase: Optional[str] = Field(None, max_length=256)
    sort_order: Optional[int] = Field(None, ge=0, le=9999)
    is_active: Optional[bool] = None


@router.get("/chat/unread-count")
async def chat_unread_count(_admin: dict = Depends(get_current_admin)):
    del _admin
    return {"count": await admin_unread_count()}


@router.get("/chat/unread-by-source")
async def chat_unread_by_source(_admin: dict = Depends(get_current_admin)):
    del _admin
    return await admin_unread_counts_by_source()


@router.get("/chat/events")
async def chat_events_stream(_admin: dict = Depends(get_current_admin)):
    del _admin

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
    admin: dict = Depends(get_current_admin),
):
    del admin
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
    admin: dict = Depends(get_current_admin),
):
    del admin
    return await admin_get_thread(
        thread_id, before_id=before_id, after_id=after_id, limit=limit
    )


@router.post("/chat/threads/{thread_id}/messages")
async def reply_thread(
    thread_id: int,
    body: AdminSendBody,
    admin: dict = Depends(get_current_admin),
):
    msg = await admin_send_message(
        thread_id,
        body.body,
        admin_user_id=admin.get("id"),
    )
    return {"message": msg}


@router.post("/chat/threads/{thread_id}/messages/image")
async def reply_image(
    thread_id: int,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    admin: dict = Depends(get_current_admin),
):
    content = await file.read()
    attachment_id = save_chat_image(content, file.content_type, file.filename)
    msg = await admin_send_image(
        thread_id,
        attachment_id,
        caption=caption,
        admin_user_id=admin.get("id"),
    )
    return {"message": msg}


@router.post("/chat/threads/{thread_id}/messages/file")
async def reply_file(
    thread_id: int,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    admin: dict = Depends(get_current_admin),
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
        admin_user_id=admin.get("id"),
    )
    return {"message": msg}


@router.get("/chat/sticker-sets")
async def chat_sticker_sets(_admin: dict = Depends(get_current_admin)):
    del _admin
    sets = await fetch_operator_sticker_sets(None)
    return {"sets": sets}


@router.post("/chat/threads/{thread_id}/messages/sticker")
async def reply_sticker(
    thread_id: int,
    body: AdminStickerBody,
    admin: dict = Depends(get_current_admin),
):
    msg = await admin_send_sticker(
        thread_id,
        body.file_id,
        admin_user_id=admin.get("id"),
        operator_id=None,
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
        if payload.get("scope") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        user = await get_web_user_by_id(int(payload["sub"]))
        if not user or not user.get("is_admin"):
            raise HTTPException(status_code=403, detail="Admin access required")
        await verify_attachment_access(attachment_id, admin=True)
    path = resolve_attachment_path(attachment_id)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type=attachment_mime_type(attachment_id))


@router.get("/chat/quick-replies")
async def admin_list_quick_replies(admin: dict = Depends(get_current_admin)):
    from permissions import PERM_TEMPLATES_VIEW, enrich_admin_permissions, require_permission

    principal = await enrich_admin_permissions(admin)
    require_permission(principal, PERM_TEMPLATES_VIEW)
    items = await list_global_templates_admin()
    return {"items": items, "permissions": principal["permissions"]}


@router.post("/chat/quick-replies")
async def admin_create_quick_reply(
    body: AdminQuickReplyBody,
    admin: dict = Depends(get_current_admin),
):
    from permissions import enrich_admin_permissions

    principal = await enrich_admin_permissions(admin)
    item = await create_global_template(
        title=body.title,
        body=body.body,
        trigger_phrase=body.trigger_phrase,
        sort_order=body.sort_order,
        principal=principal,
        is_system=False,
    )
    return {"item": item}


@router.patch("/chat/quick-replies/{template_id}")
async def admin_update_quick_reply(
    template_id: int,
    body: AdminQuickReplyPatchBody,
    admin: dict = Depends(get_current_admin),
):
    from permissions import enrich_admin_permissions

    principal = await enrich_admin_permissions(admin)
    item = await update_global_template(
        template_id,
        title=body.title,
        body=body.body,
        trigger_phrase=body.trigger_phrase,
        sort_order=body.sort_order,
        is_active=body.is_active,
        principal=principal,
    )
    return {"item": item}


@router.delete("/chat/quick-replies/{template_id}")
async def admin_delete_quick_reply(
    template_id: int,
    admin: dict = Depends(get_current_admin),
):
    from permissions import enrich_admin_permissions

    principal = await enrich_admin_permissions(admin)
    await delete_global_template(template_id, principal=principal)
    return {"ok": True}
