"""Отдача файлов чеков/видео для админки и кабинета оператора."""
import os
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

RECEIPTS_DIR = Path(os.getenv("RECEIPTS_DIR", "/opt/tg_bot_btc/receipts"))
RECEIPT_MEDIA = {
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
}


def receipt_file_response(receipt_file: str | None) -> FileResponse:
    if not receipt_file:
        raise HTTPException(status_code=404, detail="Чек по заявке не найден")

    safe_name = Path(str(receipt_file)).name
    path = RECEIPTS_DIR / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Файл чека отсутствует на сервере")

    media = RECEIPT_MEDIA.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media, filename=safe_name)
