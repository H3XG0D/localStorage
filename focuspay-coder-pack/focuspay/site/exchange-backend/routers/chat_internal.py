"""Внутренний API: бот → exchange (Telegram Business inbound)."""
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from chat_service import admin_send_from_telegram, buyer_send_from_telegram, upsert_business_connection
from config import settings

router = APIRouter()


def _verify_internal_token(token: str | None) -> None:
    expected = (settings.internal_api_secret or settings.webhook_secret or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Internal API not configured")
    if not token or token.strip() != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


class BusinessConnectionBody(BaseModel):
    connection_id: str = Field(..., min_length=1, max_length=256)
    user_id: int
    is_enabled: bool = True
    user_chat_id: Optional[int] = None


class TelegramInboundBody(BaseModel):
    connection_id: str = Field(..., min_length=1, max_length=256)
    chat_id: int
    user_id: int
    message_id: int
    body: Optional[str] = Field(None, max_length=4000)
    attachment_id: Optional[str] = Field(None, max_length=64)
    caption: Optional[str] = Field(None, max_length=2000)
    message_type: Optional[str] = Field("image", max_length=16)
    attachment_filename: Optional[str] = Field(None, max_length=255)
    sticker_file_id: Optional[str] = Field(None, max_length=256)
    sticker_emoji: Optional[str] = Field(None, max_length=32)
    sticker_set_name: Optional[str] = Field(None, max_length=256)


class BuyPayoutNotifyBody(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=64)
    explorer_url: Optional[str] = Field(None, max_length=512)


@router.post("/chat/business-connection")
async def register_business_connection(
    body: BusinessConnectionBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    await upsert_business_connection(
        connection_id=body.connection_id,
        user_id=body.user_id,
        is_enabled=body.is_enabled,
        user_chat_id=body.user_chat_id,
    )
    return {"ok": True}


@router.post("/chat/telegram-inbound")
async def telegram_inbound(
    body: TelegramInboundBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    if not body.body and not body.attachment_id and not body.sticker_file_id:
        raise HTTPException(status_code=400, detail="body, attachment_id or sticker_file_id required")

    from chat_support_scope import is_support_operator_user, support_operator_user_ids
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        exclude = await support_operator_user_ids(conn)
        is_admin = is_support_operator_user(body.user_id, exclude)

    if is_admin:
        msg = await admin_send_from_telegram(
            connection_id=body.connection_id,
            chat_id=body.chat_id,
            user_id=body.user_id,
            message_id=body.message_id,
            body=body.body,
            attachment_id=body.attachment_id,
            caption=body.caption,
            message_type=body.message_type or "image",
            attachment_filename=body.attachment_filename,
            sticker_file_id=body.sticker_file_id,
            sticker_emoji=body.sticker_emoji,
            sticker_set_name=body.sticker_set_name,
        )
    else:
        msg = await buyer_send_from_telegram(
            connection_id=body.connection_id,
            chat_id=body.chat_id,
            user_id=body.user_id,
            message_id=body.message_id,
            body=body.body,
            attachment_id=body.attachment_id,
            caption=body.caption,
            message_type=body.message_type or "image",
            attachment_filename=body.attachment_filename,
            sticker_file_id=body.sticker_file_id,
            sticker_emoji=body.sticker_emoji,
            sticker_set_name=body.sticker_set_name,
        )
    if msg is None:
        return {"ok": True, "duplicate": True}
    return {"ok": True, "message": msg}


@router.post("/buyer/buy-payout-notify")
async def buyer_buy_payout_notify(
    body: BuyPayoutNotifyBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Авто-сообщение клиенту со ссылкой на транзакцию после BUY PAID."""
    _verify_internal_token(x_internal_token)
    from db import get_pool
    from buyer_payout_notify import deliver_buy_payout_chat_message

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1",
            body.order_id.strip().upper(),
        )
    if not row:
        return {"ok": False, "reason": "not_found"}
    if str(row.get("direction") or "").lower() != "buy":
        return {"ok": False, "reason": "not_buy"}
    if str(row.get("status") or "").upper() != "PAID":
        return {"ok": False, "reason": "not_paid"}
    delivered = await deliver_buy_payout_chat_message(
        dict(row),
        explorer_url=(body.explorer_url or "").strip() or None,
    )
    return {"ok": delivered}


class PayoutPushAnswerBody(BaseModel):
    bump_id: int = Field(..., gt=0)
    telegram_user_id: int
    accept: bool


@router.post("/payout-push/answer")
async def payout_push_answer(
    body: PayoutPushAnswerBody,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Ответ оператора: пропушить чужой Bitcoin или вернуть оплату клиенту."""
    _verify_internal_token(x_internal_token)
    from payout_track import PushError, answer_operator_push

    try:
        return await answer_operator_push(body.bump_id, body.telegram_user_id, body.accept)
    except PushError as exc:
        status = 403 if exc.code == "forbidden" else 404 if exc.code == "not_found" else 400
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message}) from exc
