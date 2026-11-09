"""Сохранение вложений чата (изображения, видео, документы, аудио)."""
import hashlib
import hmac
import mimetypes
import os
import time
import uuid
from pathlib import Path

from fastapi import HTTPException

from config import settings

CHAT_UPLOAD_DIR = Path(os.getenv("CHAT_UPLOAD_DIR", "/opt/tg_bot_btc/chat_uploads"))

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_AUDIO_BYTES = 10 * 1024 * 1024

IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
}

DOCUMENT_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

AUDIO_TYPES = {
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/webm": ".webm",
}

ALLOWED_TYPES = {**IMAGE_TYPES, **VIDEO_TYPES, **DOCUMENT_TYPES, **AUDIO_TYPES}

# Все расширения для поиска файла по UUID
ALL_EXTENSIONS = sorted(set(ALLOWED_TYPES.values()))

MESSAGE_TYPE_LIMITS = {
    "image": (IMAGE_TYPES, MAX_IMAGE_BYTES, "Допустимы только JPG, PNG, WEBP, GIF (макс. 5 МБ)"),
    "video": (VIDEO_TYPES, MAX_VIDEO_BYTES, "Допустимы MP4, WEBM, MOV (макс. 50 МБ)"),
    "document": (DOCUMENT_TYPES, MAX_DOCUMENT_BYTES, "Допустимы PDF, DOC, DOCX, изображения (макс. 20 МБ)"),
    "audio": (AUDIO_TYPES, MAX_AUDIO_BYTES, "Допустимы OGG, MP3, M4A (макс. 10 МБ)"),
}


def _normalize_mime(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def _guess_mime_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    guessed, _ = mimetypes.guess_type(filename)
    return guessed.lower() if guessed else None


def detect_message_type(content_type: str | None, filename: str | None) -> str:
    ct = _normalize_mime(content_type) or _guess_mime_from_filename(filename) or ""
    if ct in IMAGE_TYPES:
        return "image"
    if ct in VIDEO_TYPES:
        return "video"
    if ct in AUDIO_TYPES:
        return "audio"
    if ct in DOCUMENT_TYPES:
        return "document"
    raise HTTPException(status_code=400, detail="Неподдерживаемый тип файла")


def save_chat_attachment(
    content: bytes,
    content_type: str | None,
    filename: str | None,
    *,
    message_type: str | None = None,
) -> tuple[str, str]:
    """Сохранить вложение. Возвращает (attachment_id, message_type)."""
    mt = message_type or detect_message_type(content_type, filename)
    if mt not in MESSAGE_TYPE_LIMITS:
        raise HTTPException(status_code=400, detail="Неподдерживаемый тип сообщения")

    allowed, max_bytes, err_msg = MESSAGE_TYPE_LIMITS[mt]
    ct = _normalize_mime(content_type) or _guess_mime_from_filename(filename) or ""

    if mt == "image":
        from image_validation import validate_image_bytes

        ct = validate_image_bytes(content, content_type)
    elif ct not in allowed:
        raise HTTPException(status_code=400, detail=err_msg)

    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail=err_msg)

    ext = allowed.get(ct)
    if not ext:
        raise HTTPException(status_code=400, detail=err_msg)

    file_id = uuid.uuid4().hex
    path = CHAT_UPLOAD_DIR / f"{file_id}{ext}"
    CHAT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return file_id, mt


def save_chat_image(content: bytes, content_type: str | None, filename: str | None) -> str:
    attachment_id, _ = save_chat_attachment(
        content, content_type, filename, message_type="image"
    )
    return attachment_id


# Bucket issuance so signed URLs stay identical across list/thread polls.
# Otherwise every refresh changes `?access=` and the browser re-fetches all avatars.
_TOKEN_EXP_BUCKET_SECONDS = 3600


def make_attachment_access_token(attachment_id: str, *, ttl_seconds: int = 86400) -> str:
    ttl = max(int(ttl_seconds), 60)
    bucket = min(_TOKEN_EXP_BUCKET_SECONDS, ttl)
    now_b = (int(time.time()) // bucket) * bucket
    exp = now_b + ttl
    payload = f"{attachment_id}:{exp}"
    sig = hmac.new(
        settings.secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{exp}.{sig}"


def verify_attachment_access_token(attachment_id: str, token: str) -> bool:
    if not token or "." not in token:
        return False
    try:
        exp_s, sig = token.split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    if time.time() > exp:
        return False
    payload = f"{attachment_id}:{exp}"
    expected = hmac.new(
        settings.secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


def attachment_public_url(attachment_id: str) -> str:
    tok = make_attachment_access_token(attachment_id)
    return f"/api/public/chat/attachments/{attachment_id}?access={tok}"


def resolve_attachment_path(file_id: str) -> Path | None:
    if not file_id or len(file_id) != 32 or not all(c in "0123456789abcdef" for c in file_id):
        return None
    for ext in ALL_EXTENSIONS:
        p = CHAT_UPLOAD_DIR / f"{file_id}{ext}"
        if p.is_file():
            return p
    return None


def attachment_mime_type(attachment_id: str) -> str:
    path = resolve_attachment_path(attachment_id)
    if not path:
        return "application/octet-stream"
    ext = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".ogg": "audio/ogg",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
    }.get(ext, "application/octet-stream")
