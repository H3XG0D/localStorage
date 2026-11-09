"""Мост Telegram Business (@focus_operator) → exchange API."""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

import aiohttp
from telegram import Update
from telegram.ext import (
    BusinessConnectionHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)

EXCHANGE_API_URL = (os.getenv("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = (
    os.getenv("INTERNAL_API_SECRET") or os.getenv("WEBHOOK_SECRET") or ""
).strip()
CHAT_UPLOAD_DIR = Path(os.getenv("CHAT_UPLOAD_DIR", "/opt/tg_bot_btc/chat_uploads"))

_ALLOWED_IMAGE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

_ALLOWED_VIDEO = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}

_ALLOWED_DOCUMENT = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    **_ALLOWED_IMAGE,
}

_ALLOWED_AUDIO = {
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
}

_MAX_BYTES = {
    "image": 5 * 1024 * 1024,
    "video": 50 * 1024 * 1024,
    "document": 20 * 1024 * 1024,
    "audio": 10 * 1024 * 1024,
}


async def _post_internal(path: str, payload: dict) -> bool:
    if not INTERNAL_TOKEN:
        logger.warning("business chat bridge: INTERNAL_API_SECRET/WEBHOOK_SECRET not set")
        return False
    url = f"{EXCHANGE_API_URL}/api/internal{path}"
    headers = {"X-Internal-Token": INTERNAL_TOKEN}
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as r:
                if r.status >= 400:
                    text = await r.text()
                    logger.warning("internal API %s -> %s: %s", path, r.status, text[:300])
                    return False
                return True
    except Exception as e:
        logger.warning("internal API %s failed: %s", path, e)
        return False


def _save_bytes(
    content: bytes,
    content_type: str | None,
    allowed: dict[str, str],
    max_bytes: int,
) -> str | None:
    ct = (content_type or "").split(";")[0].strip().lower()
    ext = allowed.get(ct)
    if not ext:
        return None
    if len(content) > max_bytes:
        return None
    file_id = uuid.uuid4().hex
    CHAT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (CHAT_UPLOAD_DIR / f"{file_id}{ext}").write_bytes(content)
    return file_id


async def _download_tg_file(context, file_id: str) -> bytes | None:
    from services.receipts_storage import download_telegram_file_bytes

    try:
        return await download_telegram_file_bytes(context.bot, file_id)
    except Exception as e:
        logger.warning("tg file download failed: %s", e)
        return None


async def business_connection_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    conn = update.business_connection
    if not conn:
        return
    await _post_internal(
        "/chat/business-connection",
        {
            "connection_id": conn.id,
            "user_id": conn.user.id,
            "is_enabled": conn.is_enabled,
            "user_chat_id": conn.user_chat_id,
        },
    )
    logger.info(
        "business connection %s enabled=%s user=%s",
        conn.id,
        conn.is_enabled,
        conn.user.id,
    )


async def business_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.business_message or update.edited_business_message
    if not msg or not msg.from_user:
        return

    connection_id = msg.business_connection_id
    if not connection_id:
        return

    chat_id = msg.chat.id
    user_id = msg.from_user.id
    message_id = msg.message_id

    payload: dict = {
        "connection_id": connection_id,
        "chat_id": chat_id,
        "user_id": user_id,
        "message_id": message_id,
    }

    caption = (msg.caption or "").strip() or None

    if msg.photo:
        photo = msg.photo[-1]
        data = await _download_tg_file(context, photo.file_id)
        if not data:
            return
        attachment_id = _save_bytes(data, "image/jpeg", _ALLOWED_IMAGE, _MAX_BYTES["image"])
        if not attachment_id:
            logger.warning("business photo save failed msg=%s", message_id)
            return
        payload["attachment_id"] = attachment_id
        payload["message_type"] = "image"
        payload["caption"] = caption
    elif msg.video or msg.animation:
        media = msg.video or msg.animation
        data = await _download_tg_file(context, media.file_id)
        if not data:
            return
        mime = getattr(media, "mime_type", None) or "video/mp4"
        attachment_id = _save_bytes(data, mime, _ALLOWED_VIDEO, _MAX_BYTES["video"])
        if not attachment_id:
            logger.warning("business video save failed msg=%s", message_id)
            return
        payload["attachment_id"] = attachment_id
        payload["message_type"] = "video"
        payload["caption"] = caption
        payload["attachment_filename"] = getattr(media, "file_name", None) or "video.mp4"
    elif msg.video_note:
        data = await _download_tg_file(context, msg.video_note.file_id)
        if not data:
            return
        attachment_id = _save_bytes(data, "video/mp4", _ALLOWED_VIDEO, _MAX_BYTES["video"])
        if not attachment_id:
            return
        payload["attachment_id"] = attachment_id
        payload["message_type"] = "video"
        payload["attachment_filename"] = "video_note.mp4"
    elif msg.document:
        doc = msg.document
        data = await _download_tg_file(context, doc.file_id)
        if not data:
            return
        mime = doc.mime_type or "application/octet-stream"
        if mime.startswith("audio/"):
            attachment_id = _save_bytes(data, mime, _ALLOWED_AUDIO, _MAX_BYTES["audio"])
            msg_type = "audio"
        else:
            attachment_id = _save_bytes(data, mime, _ALLOWED_DOCUMENT, _MAX_BYTES["document"])
            msg_type = "document"
        if not attachment_id:
            logger.warning("business document save failed msg=%s", message_id)
            return
        payload["attachment_id"] = attachment_id
        payload["message_type"] = msg_type
        payload["caption"] = caption
        payload["attachment_filename"] = doc.file_name
    elif msg.voice or msg.audio:
        media = msg.voice or msg.audio
        data = await _download_tg_file(context, media.file_id)
        if not data:
            return
        mime = getattr(media, "mime_type", None) or "audio/ogg"
        attachment_id = _save_bytes(data, mime, _ALLOWED_AUDIO, _MAX_BYTES["audio"])
        if not attachment_id:
            logger.warning("business audio save failed msg=%s", message_id)
            return
        payload["attachment_id"] = attachment_id
        payload["message_type"] = "audio"
        payload["caption"] = caption
        payload["attachment_filename"] = getattr(media, "file_name", None) or "audio.ogg"
    elif msg.sticker:
        st = msg.sticker
        data = await _download_tg_file(context, st.file_id)
        attachment_id = None
        if data:
            attachment_id = _save_bytes(
                data, "image/webp", _ALLOWED_IMAGE, _MAX_BYTES["image"]
            )
        payload["message_type"] = "sticker"
        payload["sticker_file_id"] = st.file_id
        payload["sticker_emoji"] = st.emoji or ""
        payload["sticker_set_name"] = getattr(st, "set_name", None) or ""
        if attachment_id:
            payload["attachment_id"] = attachment_id
        payload["body"] = st.emoji or ""
    else:
        text = (msg.text or msg.caption or "").strip()
        if not text:
            return
        payload["body"] = text

    ok = await _post_internal("/chat/telegram-inbound", payload)
    if ok:
        logger.info(
            "telegram inbound ok user=%s chat=%s msg=%s type=%s",
            user_id,
            chat_id,
            message_id,
            payload.get("message_type", "text"),
        )
        try:
            await context.bot.read_business_message(
                business_connection_id=connection_id,
                chat_id=chat_id,
                message_id=message_id,
            )
        except Exception as e:
            logger.debug("read_business_message: %s", e)


def register_business_chat_handlers(app) -> None:
    """Регистрация обработчиков Business API (группа -2 — раньше FSM)."""
    app.add_handler(BusinessConnectionHandler(business_connection_handler), group=-2)
    app.add_handler(
        MessageHandler(filters.UpdateType.BUSINESS_MESSAGE, business_message_handler),
        group=-2,
    )
    app.add_handler(
        MessageHandler(
            filters.UpdateType.EDITED_BUSINESS_MESSAGE, business_message_handler
        ),
        group=-2,
    )
