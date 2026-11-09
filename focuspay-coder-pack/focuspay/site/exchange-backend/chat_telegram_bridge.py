"""Исходящие ответы оператора в личку клиента через Telegram Business API."""
from __future__ import annotations

import logging
from pathlib import Path

import aiohttp

from chat_attachments import attachment_mime_type, resolve_attachment_path
from config import settings

logger = logging.getLogger("chat_telegram_bridge")

_TG_MEDIA_METHOD = {
    "image": "sendPhoto",
    "video": "sendVideo",
    "document": "sendDocument",
    "audio": "sendAudio",
}

_TG_MEDIA_FIELD = {
    "image": "photo",
    "video": "video",
    "document": "document",
    "audio": "audio",
}


def _can_mirror(thread: dict) -> bool:
    return bool(
        thread.get("telegram_dm_chat_id")
        and thread.get("business_connection_id")
        and settings.telegram_bot_token
    )


async def _post_telegram(method: str, payload: dict) -> bool:
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return False
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as r:
                data = await r.json()
                if not data.get("ok"):
                    logger.warning(
                        "telegram %s failed chat=%s: %s",
                        method,
                        payload.get("chat_id"),
                        data,
                    )
                    return False
                return True
    except Exception as e:
        logger.warning("telegram %s error: %s", method, e)
        return False


async def mirror_admin_text_to_telegram(thread: dict, body: str) -> None:
    if not _can_mirror(thread):
        return
    await _post_telegram(
        "sendMessage",
        {
            "chat_id": int(thread["telegram_dm_chat_id"]),
            "text": body,
            "business_connection_id": thread["business_connection_id"],
        },
    )


async def mirror_admin_sticker_to_telegram(thread: dict, sticker_file_id: str) -> None:
    if not _can_mirror(thread):
        return
    fid = (sticker_file_id or "").strip()
    if not fid:
        return
    await _post_telegram(
        "sendSticker",
        {
            "chat_id": int(thread["telegram_dm_chat_id"]),
            "sticker": fid,
            "business_connection_id": thread["business_connection_id"],
        },
    )


async def mirror_admin_image_to_telegram(
    thread: dict,
    attachment_id: str,
    caption: str,
) -> None:
    await mirror_admin_attachment_to_telegram(
        thread, attachment_id, "image", caption, None
    )


async def mirror_admin_attachment_to_telegram(
    thread: dict,
    attachment_id: str,
    message_type: str,
    caption: str,
    attachment_filename: str | None,
) -> None:
    if not _can_mirror(thread):
        return
    if message_type not in _TG_MEDIA_METHOD:
        return
    path = resolve_attachment_path(attachment_id)
    if not path or not path.is_file():
        logger.warning("mirror attachment: %s not found", attachment_id)
        return

    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return

    method = _TG_MEDIA_METHOD[message_type]
    field = _TG_MEDIA_FIELD[message_type]
    chat_id = int(thread["telegram_dm_chat_id"])
    connection_id = thread["business_connection_id"]
    url = f"https://api.telegram.org/bot{token}/{method}"

    media_type = attachment_mime_type(attachment_id)
    filename = attachment_filename or path.name

    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    data.add_field("business_connection_id", connection_id)
    if caption:
        data.add_field("caption", caption)
    data.add_field(
        field,
        path.read_bytes(),
        filename=filename,
        content_type=media_type,
    )

    try:
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=data) as r:
                resp = await r.json()
                if not resp.get("ok"):
                    logger.warning("telegram %s failed: %s", method, resp)
    except Exception as e:
        logger.warning("telegram %s error: %s", method, e)


def save_telegram_image(content: bytes, content_type: str | None) -> str:
    """Сохранить фото из TG в общий каталог чата (для internal API)."""
    from chat_attachments import save_chat_image

    return save_chat_image(content, content_type, "telegram.jpg")


def save_telegram_attachment(
    content: bytes,
    content_type: str | None,
    filename: str | None,
    message_type: str,
) -> str:
    from chat_attachments import save_chat_attachment

    attachment_id, _ = save_chat_attachment(
        content, content_type, filename, message_type=message_type
    )
    return attachment_id
