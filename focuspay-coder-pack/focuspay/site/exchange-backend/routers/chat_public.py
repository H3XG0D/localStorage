import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from auth import bearer_scheme, get_web_user_by_id
from buyer_events_hub import subscribe, unsubscribe
from chat_attachments import (
    attachment_mime_type,
    resolve_attachment_path,
    save_chat_attachment,
    save_chat_image,
    verify_attachment_access_token,
)
from chat_service import (
    buyer_get_conversation,
    buyer_send_attachment,
    buyer_send_image,
    buyer_send_message,
    resolve_buyer_ids,
    verify_attachment_access,
)
from panel_cookies import guest_session_trusted

router = APIRouter()


class SendMessageBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)
    order_id: Optional[str] = None


async def _telegram_user_id(
    request: Request,
    guest_session: Optional[str] = Header(None, alias="X-Guest-Session"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> tuple[Optional[int], Optional[str]]:
    """Определить Telegram user ID из Bearer-токена или guest session.

    Проверяет HttpOnly cookie для защиты от кражи guest UUID.
    """
    tg_id = None
    if credentials and credentials.scheme.lower() == "bearer":
        from auth import decode_token

        payload = decode_token(credentials.credentials)
        if payload.get("scope") == "user" and payload.get("sub"):
            user = await get_web_user_by_id(int(payload["sub"]))
            if user and user.get("telegram_user_id"):
                tg_id = int(user["telegram_user_id"])

    if not guest_session and not tg_id:
        raise HTTPException(
            status_code=401,
            detail="Provide X-Guest-Session or log in with Telegram",
        )

    # Проверка HttpOnly cookie для guest session (защита от кражи UUID)
    if guest_session and not guest_session_trusted(request, guest_session):
        raise HTTPException(
            status_code=403,
            detail="Guest session validation failed",
        )

    await resolve_buyer_ids(guest_session, tg_id)
    return tg_id, guest_session


@router.get("/chat")
async def get_chat(
    response: Response,
    order_id: Optional[str] = None,
    after_id: int = 0,
    before_id: int = 0,
    limit: int = 100,
    ctx: tuple = Depends(_telegram_user_id),
):
    tg_id, guest = ctx

    # Установить HttpOnly cookie для защиты guest session
    if guest:
        from panel_cookies import set_guest_cookie
        from fastapi import Request
        # Request уже есть в _telegram_user_id, но для set_guest_cookie нужен явный
        # Используем упрощённую версию без request параметра
        from panel_cookies import GUEST_COOKIE, GUEST_COOKIE_MAX_AGE, _cookie_secure
        response.set_cookie(
            key=GUEST_COOKIE,
            value=guest,
            httponly=True,
            secure=True,  # Всегда secure для prod
            samesite="lax",
            max_age=GUEST_COOKIE_MAX_AGE,
            path="/",
        )

    return await buyer_get_conversation(
        session_token=guest,
        telegram_user_id=tg_id,
        order_id=order_id,
        after_id=after_id,
        before_id=before_id,
        limit=limit,
    )


@router.post("/chat/messages")
async def post_message(
    response: Response,
    body: SendMessageBody,
    ctx: tuple = Depends(_telegram_user_id),
):
    tg_id, guest = ctx

    # Установить HttpOnly cookie
    if guest:
        from panel_cookies import GUEST_COOKIE, GUEST_COOKIE_MAX_AGE
        response.set_cookie(
            key=GUEST_COOKIE,
            value=guest,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=GUEST_COOKIE_MAX_AGE,
            path="/",
        )

    msg = await buyer_send_message(
        session_token=guest,
        telegram_user_id=tg_id,
        body=body.body,
        order_id=body.order_id,
    )
    return {"message": msg}


@router.post("/chat/messages/image")
async def post_image(
    response: Response,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    order_id: Optional[str] = Form(None),
    ctx: tuple = Depends(_telegram_user_id),
):
    content = await file.read()
    attachment_id = save_chat_image(content, file.content_type, file.filename)
    tg_id, guest = ctx

    # Установить HttpOnly cookie
    if guest:
        from panel_cookies import GUEST_COOKIE, GUEST_COOKIE_MAX_AGE
        response.set_cookie(
            key=GUEST_COOKIE,
            value=guest,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=GUEST_COOKIE_MAX_AGE,
            path="/",
        )

    msg = await buyer_send_image(
        session_token=guest,
        telegram_user_id=tg_id,
        attachment_id=attachment_id,
        caption=caption,
        order_id=order_id,
    )
    return {"message": msg}


@router.post("/chat/messages/file")
async def post_file(
    response: Response,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    order_id: Optional[str] = Form(None),
    ctx: tuple = Depends(_telegram_user_id),
):
    content = await file.read()
    attachment_id, message_type = save_chat_attachment(
        content, file.content_type, file.filename
    )
    tg_id, guest = ctx

    # Установить HttpOnly cookie
    if guest:
        from panel_cookies import GUEST_COOKIE, GUEST_COOKIE_MAX_AGE
        response.set_cookie(
            key=GUEST_COOKIE,
            value=guest,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=GUEST_COOKIE_MAX_AGE,
            path="/",
        )

    msg = await buyer_send_attachment(
        session_token=guest,
        telegram_user_id=tg_id,
        attachment_id=attachment_id,
        message_type=message_type,
        caption=caption,
        attachment_filename=file.filename,
        order_id=order_id,
    )
    return {"message": msg}


@router.get("/chat/events")
async def chat_events_stream(order_id: Optional[str] = Query(None)):
    """SSE-поток событий для покупателя (ответы оператора + смена статуса заявки).

    EventSource не умеет слать кастомные заголовки, поэтому здесь НЕ отдаём
    содержимое сообщений — только «пинг» с order_id, по которому клиент дёргает
    авторизованные /chat и /orders. Если order_id задан, фильтруем по нему.
    """
    async def event_stream():
        queue = subscribe()
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    if order_id and str(payload.get("order_id") or "") != str(order_id):
                        continue
                    event = {"type": payload.get("kind", "event"), **payload}
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


@router.get("/chat/attachments/{attachment_id}")
async def get_attachment(
    attachment_id: str,
    request: Request,
    access: Optional[str] = None,
    guest_session: Optional[str] = Header(None, alias="X-Guest-Session"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    if not (access and verify_attachment_access_token(attachment_id, access)):
        tg_id = None
        if credentials and credentials.scheme.lower() == "bearer":
            from auth import decode_token

            payload = decode_token(credentials.credentials)
            if payload.get("scope") == "user" and payload.get("sub"):
                user = await get_web_user_by_id(int(payload["sub"]))
                if user and user.get("telegram_user_id"):
                    tg_id = int(user["telegram_user_id"])
        if not guest_session and not tg_id:
            raise HTTPException(
                status_code=401,
                detail="Provide X-Guest-Session or log in with Telegram",
            )
        if guest_session and not guest_session_trusted(request, guest_session):
            raise HTTPException(
                status_code=403,
                detail="Guest session validation failed",
            )
        await verify_attachment_access(
            attachment_id,
            guest_session=guest_session,
            telegram_user_id=tg_id,
        )
    path = resolve_attachment_path(attachment_id)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type=attachment_mime_type(attachment_id))
