"""Общие обработчики рассылки для admin и operator роутеров."""
from __future__ import annotations

from typing import Optional

from fastapi import File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

import broadcast_service as bs
from telegram_notify import download_telegram_file, upload_photo_get_file_id

MAX_PHOTO_BYTES = 10 * 1024 * 1024


class PreviewBody(BaseModel):
    segment: str


class CreateJobBody(BaseModel):
    segment: str
    text: str = Field("", max_length=4096)
    photo_file_id: Optional[str] = Field(None, max_length=256)


async def segments_list():
    return {"segments": await bs.list_segments()}


async def preview_segment(body: PreviewBody):
    count = await bs.count_segment(body.segment)
    seg = body.segment.strip().lower()
    return {
        "segment": seg,
        "label": bs.BROADCAST_SEGMENTS.get(seg, seg),
        "count": count,
    }


async def upload_photo(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Нужен файл изображения")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Максимум 10 МБ")
    file_id = await upload_photo_get_file_id(data, file.filename or "broadcast.jpg")
    if not file_id:
        raise HTTPException(status_code=502, detail="Не удалось загрузить фото в Telegram")
    return {"photo_file_id": file_id}


async def create_job(
    body: CreateJobBody,
    *,
    sender_role: str,
    sender_id: int,
    sender_label: str | None,
):
    return await bs.create_job(
        sender_role=sender_role,
        sender_id=sender_id,
        sender_label=sender_label,
        segment=body.segment,
        message_text=body.text,
        photo_file_id=body.photo_file_id,
    )


async def list_jobs(limit: int = 50):
    return {"jobs": await bs.list_jobs(limit=limit)}


async def get_job(job_id: int):
    job = await bs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Рассылка не найдена")
    return job


async def cancel_job(job_id: int):
    return await bs.cancel_job(job_id)


async def get_job_photo(job_id: int):
    job = await bs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Рассылка не найдена")
    file_id = (job.get("photo_file_id") or "").strip()
    if not file_id:
        raise HTTPException(status_code=404, detail="Фото недоступно")
    result = await download_telegram_file(file_id)
    if not result:
        raise HTTPException(status_code=404, detail="Не удалось загрузить фото")
    content, mime = result
    return Response(
        content=content,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=3600"},
    )
