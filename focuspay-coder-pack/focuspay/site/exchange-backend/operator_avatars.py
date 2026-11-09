"""Загрузка и раздача аватаров операторов."""
import os
import uuid
from pathlib import Path

from fastapi import HTTPException

from chat_attachments import (
    ALLOWED_TYPES,
    make_attachment_access_token,
    verify_attachment_access_token,
)

OPERATOR_AVATAR_DIR = Path(
    os.getenv("OPERATOR_AVATAR_DIR", "/opt/tg_bot_btc/operator_avatars")
)
MAX_AVATAR_BYTES = 2 * 1024 * 1024


def save_operator_avatar(content: bytes, content_type: str | None, filename: str | None) -> str:
    from image_validation import validate_image_bytes

    ct = validate_image_bytes(content, content_type)
    if ct not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Допустимы только JPG, PNG, WEBP или GIF",
        )
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="Файл слишком большой (макс. 2 МБ)")

    file_id = uuid.uuid4().hex
    path = OPERATOR_AVATAR_DIR / f"{file_id}{ALLOWED_TYPES[ct]}"
    OPERATOR_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return file_id


def delete_operator_avatar_file(file_id: str | None) -> None:
    path = resolve_operator_avatar_path(file_id)
    if path and path.is_file():
        path.unlink(missing_ok=True)


def resolve_operator_avatar_path(file_id: str | None) -> Path | None:
    if not file_id or len(file_id) != 32 or not all(c in "0123456789abcdef" for c in file_id):
        return None
    for ext in ALLOWED_TYPES.values():
        p = OPERATOR_AVATAR_DIR / f"{file_id}{ext}"
        if p.is_file():
            return p
    return None


def operator_avatar_public_url(file_id: str | None) -> str | None:
    if not file_id:
        return None
    tok = make_attachment_access_token(file_id, ttl_seconds=86400 * 30)
    return f"/api/public/operator-avatars/{file_id}?access={tok}"


def verify_operator_avatar_access(file_id: str, access: str | None) -> bool:
    return bool(access and verify_attachment_access_token(file_id, access))
