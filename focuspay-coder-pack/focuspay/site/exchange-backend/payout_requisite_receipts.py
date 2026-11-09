"""Чеки по доливам оператора: сохранение и отдача файла.

Отдельный каталог, чтобы не смешиваться с клиентскими чеками бота.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

RECEIPTS_DIR = Path(
    os.getenv(
        "PAYOUT_RECEIPTS_DIR",
        str(Path(os.getenv("RECEIPTS_DIR", "/opt/tg_bot_btc/receipts")) / "payout_requisites"),
    )
)

MAX_RECEIPT_BYTES = 20 * 1024 * 1024

ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}

_ERR = "Допустимы JPG, PNG, WEBP, PDF (макс. 20 МБ)"


def receipt_disk_path(receipt_file: str | None) -> Path | None:
    if not receipt_file:
        return None
    path = RECEIPTS_DIR / Path(str(receipt_file)).name
    return path if path.is_file() else None


def save_doliv_receipt(content: bytes, content_type: str | None, filename: str | None) -> str:
    if not content:
        raise HTTPException(status_code=400, detail="Файл чека пустой")
    if len(content) > MAX_RECEIPT_BYTES:
        raise HTTPException(status_code=400, detail=_ERR)

    ct = (content_type or "").split(";")[0].strip().lower()
    ext = ALLOWED_TYPES.get(ct)
    if not ext:
        suffix = Path(filename or "").suffix.lower()
        if suffix in ALLOWED_TYPES.values():
            ext = suffix
    if not ext:
        raise HTTPException(status_code=400, detail=_ERR)

    if ext in (".jpg", ".png", ".webp"):
        from image_validation import validate_image_bytes

        validate_image_bytes(content, content_type)

    name = f"doliv-{uuid.uuid4().hex}{ext}"
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    (RECEIPTS_DIR / name).write_bytes(content)
    return name


def doliv_receipt_response(receipt_file: str | None) -> FileResponse:
    if not receipt_file:
        raise HTTPException(status_code=404, detail="Чек по доливу не приложен")
    safe_name = Path(str(receipt_file)).name
    path = RECEIPTS_DIR / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Файл чека отсутствует на сервере")
    media = {
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media, filename=safe_name)
