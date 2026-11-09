"""Чат внештатник ↔ оператор."""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field

from auth import get_current_exchanger
from chat_attachments import save_chat_attachment, save_chat_image
from chat_service import (
    exchanger_get_conversation,
    exchanger_send_attachment,
    exchanger_send_message,
)

router = APIRouter()


class ExchangerSendBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)


@router.get("/chat")
async def get_chat(
    after_id: int = Query(0, ge=0),
    before_id: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    exchanger=Depends(get_current_exchanger),
):
    return await exchanger_get_conversation(
        exchanger_id=int(exchanger["external_exchanger_id"]),
        after_id=after_id,
        before_id=before_id,
        limit=limit,
    )


@router.post("/chat")
async def post_chat(body: ExchangerSendBody, exchanger=Depends(get_current_exchanger)):
    msg = await exchanger_send_message(
        exchanger_id=int(exchanger["external_exchanger_id"]),
        body=body.body,
    )
    return {"message": msg}


@router.post("/chat/messages/image")
async def post_chat_image(
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    exchanger=Depends(get_current_exchanger),
):
    content = await file.read()
    attachment_id = save_chat_image(content, file.content_type, file.filename)
    msg = await exchanger_send_attachment(
        exchanger_id=int(exchanger["external_exchanger_id"]),
        attachment_id=attachment_id,
        message_type="image",
        caption=caption,
        attachment_filename=file.filename,
    )
    return {"message": msg}


@router.post("/chat/messages/file")
async def post_chat_file(
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    exchanger=Depends(get_current_exchanger),
):
    content = await file.read()
    attachment_id, message_type = save_chat_attachment(
        content, file.content_type, file.filename
    )
    msg = await exchanger_send_attachment(
        exchanger_id=int(exchanger["external_exchanger_id"]),
        attachment_id=attachment_id,
        message_type=message_type,
        caption=caption,
        attachment_filename=file.filename,
    )
    return {"message": msg}
