"""Отправка сообщений в Telegram (Bot API)."""
import html
import logging
import re

import aiohttp

from config import settings
from finance_access import finance_owner_telegram_id

logger = logging.getLogger("telegram_notify")

PHOTO_CAPTION_MAX = 1024


def _broadcast_upload_chat_id() -> int:
    """Куда загружать фото перед рассылкой (нужен чат, где бот может sendPhoto)."""
    for candidate in (
        settings.telegram_ops_group_id,
        settings.telegram_admin_group_id,
        settings.telegram_reports_group_id,
    ):
        if candidate:
            return int(candidate)
    owner = finance_owner_telegram_id()
    return int(owner) if owner else 0


def _telegram_error(data: dict | None) -> str | None:
    if not data or data.get("ok"):
        return None
    return str(data.get("description") or "Telegram API error")


async def _post_telegram(method: str, *, json_payload: dict | None = None, form: aiohttp.FormData | None = None):
    if not settings.telegram_bot_token:
        return None, "Bot token not configured"
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if form is not None:
                async with session.post(url, data=form) as r:
                    data = await r.json(content_type=None)
            else:
                async with session.post(url, json=json_payload or {}) as r:
                    data = await r.json(content_type=None)
            if data.get("ok"):
                return data, None
            return data, _telegram_error(data)
    except Exception as e:
        logger.warning("telegram %s failed: %s", method, e)
        return None, str(e)


async def send_admin_message(
    text: str,
    *,
    chat_id: int | None = None,
    message_thread_id: int | None = None,
    reply_markup: dict | None = None,
    parse_mode: str = "HTML",
) -> int | None:
    target_chat = int(chat_id or settings.ops_telegram_group_id() or 0)
    if not settings.telegram_bot_token or not target_chat:
        return None
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload: dict = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if message_thread_id is not None:
        payload["message_thread_id"] = int(message_thread_id)
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as r:
                r.raise_for_status()
                data = await r.json()
                if data.get("ok"):
                    return data.get("result", {}).get("message_id")
    except Exception as e:
        logger.warning("telegram send failed chat=%s: %s", target_chat, e)
    return None


async def send_ops_message(
    text: str,
    *,
    chat_id: int,
    message_thread_id: int | None = None,
    parse_mode: str = "HTML",
) -> int | None:
    return await send_admin_message(
        text,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        parse_mode=parse_mode,
    )


_DOCUMENT_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


async def send_user_document(
    chat_id: int,
    file_path: str,
    caption: str,
    *,
    reply_markup: dict | None = None,
    parse_mode: str = "HTML",
) -> int | None:
    """sendDocument клиенту (чек выплаты). chat_id <= 0 — нет Telegram."""
    import json
    from pathlib import Path

    if not settings.telegram_bot_token or int(chat_id or 0) <= 0:
        return None
    path = Path(file_path)
    if not path.is_file():
        logger.warning("send_user_document: file missing %s", file_path)
        return None
    media = _DOCUMENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendDocument"
    data = aiohttp.FormData()
    data.add_field("chat_id", str(int(chat_id)))
    data.add_field("caption", caption[:1024])
    data.add_field("parse_mode", parse_mode)
    if reply_markup:
        data.add_field("reply_markup", json.dumps(reply_markup, ensure_ascii=False))
    data.add_field(
        "document",
        path.read_bytes(),
        filename=path.name,
        content_type=media,
    )
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=data) as r:
                r.raise_for_status()
                body = await r.json()
                if body.get("ok"):
                    return body.get("result", {}).get("message_id")
                logger.warning("telegram sendDocument user=%s: %s", chat_id, body)
    except Exception as e:
        logger.warning("telegram sendDocument user=%s: %s", chat_id, e)
    return None


async def send_ops_document(
    chat_id: int,
    file_path: str,
    caption: str,
    *,
    message_thread_id: int | None = None,
    parse_mode: str = "HTML",
) -> int | None:
    """Отправить PDF/файл в ops-группу (sendDocument)."""
    from pathlib import Path

    if not settings.telegram_bot_token or not chat_id:
        return None
    path = Path(file_path)
    if not path.is_file():
        logger.warning("send_ops_document: file missing %s", file_path)
        return None
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendDocument"
    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    data.add_field("caption", caption[:1024])
    data.add_field("parse_mode", parse_mode)
    if message_thread_id is not None:
        data.add_field("message_thread_id", str(int(message_thread_id)))
    data.add_field(
        "document",
        path.read_bytes(),
        filename=path.name,
        content_type="application/pdf",
    )
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=data) as r:
                r.raise_for_status()
                body = await r.json()
                if body.get("ok"):
                    return body.get("result", {}).get("message_id")
    except Exception as e:
        logger.warning("telegram sendDocument failed chat=%s: %s", chat_id, e)
    return None


async def send_finance_owner_document(
    file_path: str,
    caption: str,
    *,
    parse_mode: str = "HTML",
) -> int | None:
    owner_id = finance_owner_telegram_id()
    if not settings.telegram_bot_token or not owner_id:
        return None
    from pathlib import Path

    path = Path(file_path)
    if not path.is_file():
        return None
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendDocument"
    data = aiohttp.FormData()
    data.add_field("chat_id", str(owner_id))
    data.add_field("caption", caption[:1024])
    data.add_field("parse_mode", parse_mode)
    data.add_field(
        "document",
        path.read_bytes(),
        filename=path.name,
        content_type="application/pdf",
    )
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=data) as r:
                r.raise_for_status()
                body = await r.json()
                if body.get("ok"):
                    return body.get("result", {}).get("message_id")
    except Exception as e:
        logger.warning("telegram finance owner sendDocument failed: %s", e)
    return None


async def send_finance_owner_message(
    text: str,
    *,
    reply_markup: dict | None = None,
    parse_mode: str = "HTML",
) -> int | None:
    """Личное сообщение владельцу (зарплаты операторов и т.п.)."""
    owner_id = finance_owner_telegram_id()
    if not settings.telegram_bot_token or not owner_id:
        return None
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload: dict = {
        "chat_id": owner_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as r:
                r.raise_for_status()
                data = await r.json()
                if data.get("ok"):
                    return data.get("result", {}).get("message_id")
    except Exception as e:
        logger.warning("telegram finance owner send failed: %s", e)
    return None


async def edit_finance_owner_message(
    message_id: int,
    text: str,
    *,
    reply_markup: dict | None = None,
    parse_mode: str = "HTML",
) -> bool:
    owner_id = finance_owner_telegram_id()
    if not settings.telegram_bot_token or not owner_id:
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/editMessageText"
    payload: dict = {
        "chat_id": owner_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as r:
                r.raise_for_status()
                data = await r.json()
                return bool(data.get("ok"))
    except Exception as e:
        logger.warning("telegram finance owner edit failed: %s", e)
    return False


def _telegram_html_to_plain(text: str) -> str:
    """Best-effort plain-text fallback for malformed Telegram HTML."""
    value = re.sub(r"<\s*br\b[^>]*?/?>", "\n", text or "", flags=re.I)
    value = re.sub(r"<\s*/\s*(p|div|li)\s*>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip()


async def send_user_message_detailed(
    user_id: int,
    text: str,
    *,
    parse_mode: str = "HTML",
    reply_markup: dict | None = None,
) -> tuple[bool, str | None]:
    if not settings.telegram_bot_token:
        return False, "Bot token not configured"
    payload: dict = {
        "chat_id": user_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    data, err = await _post_telegram("sendMessage", json_payload=payload)
    if data:
        return True, None

    # A malformed/unsupported HTML tag must not make the whole broadcast fail.
    # Retry once as plain text; Telegram still receives a readable message.
    if parse_mode == "HTML" and err and "parse entities" in err.lower():
        plain = _telegram_html_to_plain(text)
        if plain:
            payload["text"] = plain
            payload.pop("parse_mode", None)
            data2, err2 = await _post_telegram("sendMessage", json_payload=payload)
            if data2:
                logger.warning(
                    "telegram user send recovered as plain text uid=%s html_error=%s",
                    user_id,
                    err,
                )
                return True, None
            err = err2 or err

    logger.warning("telegram user send failed uid=%s: %s", user_id, err)
    return False, err


async def send_user_message(
    user_id: int,
    text: str,
    *,
    parse_mode: str = "HTML",
    reply_markup: dict | None = None,
) -> bool:
    ok, _ = await send_user_message_detailed(
        user_id,
        text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )
    return ok


async def send_focusvpn_user_message(user_id: int, text: str) -> bool:
    """Result of a VPN review belongs in @focusvpn1_bot, not the exchange bot."""
    import os

    token = (os.getenv("FOCUSVPN_BOT_TOKEN") or "").strip()
    if not token:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": int(user_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json(content_type=None)
                return bool(data.get("ok"))
    except Exception as e:
        logger.warning("vpn bot notify failed uid=%s: %s", user_id, type(e).__name__)
        return False


async def deliver_review_notice(user_id: int, text: str, product: str | None) -> None:
    if (product or "") == "vpn" and await send_focusvpn_user_message(user_id, text):
        return
    await send_user_message(user_id, text)


async def send_user_photo(
    user_id: int,
    photo_file_id: str,
    caption: str = "",
    *,
    parse_mode: str = "HTML",
) -> tuple[bool, str | None]:
    if not photo_file_id:
        return False, "photo_file_id is empty"
    cap = (caption or "")[:PHOTO_CAPTION_MAX]
    payload: dict = {
        "chat_id": user_id,
        "photo": photo_file_id,
    }
    if cap:
        payload["caption"] = cap
        payload["parse_mode"] = parse_mode
    data, err = await _post_telegram("sendPhoto", json_payload=payload)
    if data:
        return True, None
    if cap and parse_mode == "HTML" and err and "parse entities" in err.lower():
        payload.pop("parse_mode", None)
        data2, err2 = await _post_telegram("sendPhoto", json_payload=payload)
        if data2:
            return True, None
        err = err2 or err
    logger.warning("telegram user photo send failed uid=%s: %s", user_id, err)
    return False, err


async def send_user_photo_bytes(
    user_id: int,
    photo_bytes: bytes,
    caption: str = "",
    *,
    filename: str = "broadcast.jpg",
    content_type: str = "image/jpeg",
    parse_mode: str = "HTML",
) -> tuple[bool, str | None]:
    if not photo_bytes:
        return False, "photo bytes are empty"
    cap = (caption or "")[:PHOTO_CAPTION_MAX]
    form = aiohttp.FormData()
    form.add_field("chat_id", str(user_id))
    form.add_field(
        "photo",
        photo_bytes,
        filename=filename or "broadcast.jpg",
        content_type=content_type or "image/jpeg",
    )
    if cap:
        form.add_field("caption", cap)
        form.add_field("parse_mode", parse_mode)
    data, err = await _post_telegram("sendPhoto", form=form)
    if data:
        return True, None
    if cap and parse_mode == "HTML" and err and "parse entities" in err.lower():
        form = aiohttp.FormData()
        form.add_field("chat_id", str(user_id))
        form.add_field(
            "photo",
            photo_bytes,
            filename=filename or "broadcast.jpg",
            content_type=content_type or "image/jpeg",
        )
        form.add_field("caption", cap)
        data2, err2 = await _post_telegram("sendPhoto", form=form)
        if data2:
            return True, None
        err = err2 or err
    logger.warning("telegram user photo bytes send failed uid=%s: %s", user_id, err)
    return False, err


async def send_user_sticker(
    user_id: int,
    sticker_file_id: str,
) -> tuple[bool, str | None]:
    fid = (sticker_file_id or "").strip()
    if not fid:
        return False, "sticker is empty"
    data, err = await _post_telegram(
        "sendSticker",
        json_payload={"chat_id": user_id, "sticker": fid},
    )
    if data:
        return True, None
    logger.warning("telegram user sticker send failed uid=%s: %s", user_id, err)
    return False, err


async def upload_photo_get_file_id(file_bytes: bytes, filename: str) -> str | None:
    """Загружает фото в служебный чат и возвращает file_id для превью/истории."""
    chat_id = _broadcast_upload_chat_id()
    if not chat_id:
        logger.warning("upload_photo_get_file_id: no upload chat configured")
        return None
    form = aiohttp.FormData()
    form.add_field("chat_id", str(chat_id))
    form.add_field(
        "photo",
        file_bytes,
        filename=filename or "broadcast.jpg",
        content_type="image/jpeg",
    )
    form.add_field("caption", "📢 служебная загрузка для рассылки")
    data, err = await _post_telegram("sendPhoto", form=form)
    if not data:
        logger.warning("upload_photo failed chat=%s: %s", chat_id, err)
        return None
    photos = data.get("result", {}).get("photo") or []
    if not photos:
        return None
    return photos[-1].get("file_id")


async def download_telegram_file(file_id: str) -> tuple[bytes, str] | None:
    """Скачивает файл из Telegram по file_id. Возвращает (bytes, mime) или None."""
    if not settings.telegram_bot_token or not file_id:
        return None
    token = settings.telegram_bot_token.strip()
    get_url = f"https://api.telegram.org/bot{token}/getFile"
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(get_url, json={"file_id": file_id}) as r:
                r.raise_for_status()
                data = await r.json()
                if not data.get("ok"):
                    logger.warning("getFile failed: %s", data)
                    return None
                file_path = (data.get("result") or {}).get("file_path")
                if not file_path:
                    return None
            file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
                async with session.get(file_url) as r:
                    r.raise_for_status()
                    content = await r.read()
            ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else "jpg"
            if ext in ("jpg", "jpeg"):
                mime = "image/jpeg"
            elif ext == "png":
                mime = "image/png"
            elif ext == "webp":
                mime = "image/webp"
            elif ext == "gif":
                mime = "image/gif"
            else:
                mime = f"image/{ext}"
            return content, mime
    except Exception as e:
        logger.warning("download_telegram_file failed: %s", e)
    return None


async def edit_admin_message(
    message_id: int,
    text: str,
    *,
    chat_id: int | None = None,
    reply_markup: dict | None = None,
    parse_mode: str = "HTML",
) -> bool:
    target_chat = int(chat_id or settings.ops_telegram_group_id() or 0)
    if not settings.telegram_bot_token or not target_chat:
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/editMessageText"
    payload: dict = {
        "chat_id": target_chat,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as r:
                r.raise_for_status()
                data = await r.json()
                return bool(data.get("ok"))
    except Exception as e:
        logger.warning("telegram edit failed chat=%s msg=%s: %s", target_chat, message_id, e)
    return False


async def clear_message_reply_markup(chat_id: int, message_id: int) -> bool:
    """Убрать inline-кнопки, не меняя текст сообщения."""
    if not settings.telegram_bot_token or not chat_id or not message_id:
        return False
    url = (
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/editMessageReplyMarkup"
    )
    payload = {
        "chat_id": int(chat_id),
        "message_id": int(message_id),
        "reply_markup": {"inline_keyboard": []},
    }
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as r:
                r.raise_for_status()
                data = await r.json()
                return bool(data.get("ok"))
    except Exception as e:
        logger.warning(
            "telegram clear markup failed chat=%s msg=%s: %s",
            chat_id,
            message_id,
            e,
        )
    return False
