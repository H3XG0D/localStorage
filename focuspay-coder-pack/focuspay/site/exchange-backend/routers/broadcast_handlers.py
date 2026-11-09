"""Общие обработчики рассылки для admin и operator роутеров."""
from __future__ import annotations

import io
from datetime import datetime
from typing import Literal, Optional

from fastapi import File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

import broadcast_service as bs
from telegram_notify import download_telegram_file, upload_photo_get_file_id

MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTO_PIXELS = 20_000_000
MAX_PHOTO_EDGE = 10_000
ALLOWED_IMAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF"})
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_GIF_MAGIC = b"GIF8"
_WEBP_RIFF = b"RIFF"
_WEBP_WEBP = b"WEBP"

StickerMode = Literal["none", "selected", "auto"]


def _normalize_segment_field(value: str) -> str:
    try:
        return bs.normalize_segment(value)
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc


def _normalize_destination_field(value: str) -> str:
    try:
        return bs.normalize_destination(value)
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc


class PreviewBody(BaseModel):
    segment: str
    destination: str = "bot"
    text: str = Field("", max_length=4096)
    selected_sticker_ids: list[str] = Field(default_factory=list, max_length=3)
    sticker_mode: StickerMode = "none"

    @field_validator("segment")
    @classmethod
    def _segment(cls, value: str) -> str:
        return _normalize_segment_field(value)

    @field_validator("destination")
    @classmethod
    def _destination(cls, value: str) -> str:
        return _normalize_destination_field(value)


class CreateJobBody(BaseModel):
    segment: str
    destination: str = "bot"
    text: str = Field("", max_length=4096)
    photo_file_id: Optional[str] = Field(None, max_length=256)
    selected_sticker_ids: list[str] = Field(default_factory=list, max_length=3)
    sticker_mode: StickerMode = "none"
    ai_enabled: bool = False
    ai_provider_profile: str = Field("default", max_length=32)
    scheduled_at: Optional[datetime] = None

    @field_validator("segment")
    @classmethod
    def _segment(cls, value: str) -> str:
        return _normalize_segment_field(value)

    @field_validator("destination")
    @classmethod
    def _destination(cls, value: str) -> str:
        return _normalize_destination_field(value)


class PatchJobBody(BaseModel):
    text: Optional[str] = Field(None, max_length=4096)
    scheduled_at: Optional[datetime] = None
    segment: Optional[str] = None
    destination: Optional[str] = None
    selected_sticker_ids: Optional[list[str]] = Field(None, max_length=3)
    sticker_mode: Optional[StickerMode] = None

    @field_validator("segment")
    @classmethod
    def _segment(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _normalize_segment_field(value)

    @field_validator("destination")
    @classmethod
    def _destination(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _normalize_destination_field(value)


class CreateScheduleBody(BaseModel):
    segment: str
    destination: str = "bot"
    text: str = Field("", max_length=4096)
    photo_file_id: Optional[str] = Field(None, max_length=256)
    selected_sticker_ids: list[str] = Field(default_factory=list, max_length=3)
    sticker_mode: StickerMode = "none"
    time_local: str = Field(..., min_length=4, max_length=8)
    days_of_week: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7], max_length=7)
    enabled: bool = True

    @field_validator("segment")
    @classmethod
    def _segment(cls, value: str) -> str:
        return _normalize_segment_field(value)

    @field_validator("destination")
    @classmethod
    def _destination(cls, value: str) -> str:
        return _normalize_destination_field(value)


class PatchScheduleBody(BaseModel):
    segment: Optional[str] = None
    destination: Optional[str] = None
    text: Optional[str] = Field(None, max_length=4096)
    photo_file_id: Optional[str] = Field(None, max_length=256)
    selected_sticker_ids: Optional[list[str]] = Field(None, max_length=3)
    sticker_mode: Optional[StickerMode] = None
    time_local: Optional[str] = Field(None, min_length=4, max_length=8)
    days_of_week: Optional[list[int]] = Field(None, max_length=7)
    enabled: Optional[bool] = None

    @field_validator("segment")
    @classmethod
    def _segment(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _normalize_segment_field(value)

    @field_validator("destination")
    @classmethod
    def _destination(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _normalize_destination_field(value)


class AiDraftBody(BaseModel):
    text: str = Field("", max_length=4096)
    ai_enabled: bool = False
    ai_provider_profile: str = Field("default", max_length=32)


def _detect_image_ext(data: bytes) -> str | None:
    if len(data) < 12:
        return None
    if data.startswith(_JPEG_MAGIC):
        return "jpg"
    if data.startswith(_PNG_MAGIC):
        return "png"
    if data.startswith(_GIF_MAGIC):
        return "gif"
    if data[:4] == _WEBP_RIFF and data[8:12] == _WEBP_WEBP:
        return "webp"
    return None


def _safe_broadcast_filename(ext: str) -> str:
    allowed = {"jpg": "jpg", "jpeg": "jpg", "png": "png", "webp": "webp", "gif": "gif"}
    return f"broadcast.{allowed.get(ext.lower(), 'jpg')}"


def validate_broadcast_image(data: bytes, *, content_type: str | None) -> tuple[bytes, str]:
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Максимум 10 МБ")
    if content_type and not content_type.lower().startswith("image/"):
        raise HTTPException(status_code=400, detail="Нужен файл изображения")
    ext = _detect_image_ext(data)
    if not ext:
        raise HTTPException(status_code=400, detail="Недопустимый формат изображения")
    try:
        from PIL import Image

        prev_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = MAX_PHOTO_PIXELS
        try:
            bio = io.BytesIO(data)
            with Image.open(bio) as probe:
                probe.verify()
            bio.seek(0)
            with Image.open(bio) as image:
                image.load()
                fmt = (image.format or "").upper()
                width, height = image.size
        finally:
            Image.MAX_IMAGE_PIXELS = prev_limit
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Повреждённое изображение")
    if fmt not in ALLOWED_IMAGE_FORMATS:
        raise HTTPException(status_code=400, detail="Недопустимый формат изображения")
    if width < 1 or height < 1 or width > MAX_PHOTO_EDGE or height > MAX_PHOTO_EDGE:
        raise HTTPException(status_code=400, detail="Недопустимый размер изображения")
    fmt_to_ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}
    return data, _safe_broadcast_filename(fmt_to_ext.get(fmt, ext))


async def segments_list():
    return {"segments": await bs.list_segments()}


async def preview_segment(body: PreviewBody, *, apply_stickers: bool = False):
    if body.destination == "news":
        count = 1
        label = bs.NEWS_DESTINATION_LABEL
    else:
        count = await bs.count_segment(body.segment)
        label = bs.BROADCAST_SEGMENTS.get(body.segment, body.segment)
    sticker_preview = await bs.preview_stickers(
        sticker_mode=body.sticker_mode,
        selected_sticker_ids=body.selected_sticker_ids,
        text=body.text,
        apply_stickers=apply_stickers,
    )
    return {
        "segment": body.segment,
        "destination": body.destination,
        "label": label,
        "count": count,
        **sticker_preview,
    }


async def upload_photo(file: UploadFile = File(...)):
    data = await file.read()
    _payload, filename = validate_broadcast_image(data, content_type=file.content_type)
    file_id = await upload_photo_get_file_id(_payload, filename)
    if not file_id:
        raise HTTPException(
            status_code=502,
            detail="Не удалось загрузить фото. Повторите попытку позже.",
        )
    return {"photo_file_id": file_id}


async def create_job(
    body: CreateJobBody,
    *,
    sender_role: str,
    sender_id: int,
    sender_label: str | None,
    apply_stickers: bool = False,
):
    # ai_enabled / ai_provider_profile are ignored: confirmed `text` is what gets sent.
    return await bs.create_job(
        sender_role=sender_role,
        sender_id=sender_id,
        sender_label=sender_label,
        segment=body.segment,
        message_text=body.text,
        photo_file_id=body.photo_file_id,
        sticker_mode=body.sticker_mode if apply_stickers else "none",
        selected_sticker_ids=body.selected_sticker_ids if apply_stickers else [],
        apply_stickers=apply_stickers,
        scheduled_at=body.scheduled_at,
        require_future_slot=body.scheduled_at is not None,
        destination=body.destination,
    )


async def patch_job(
    job_id: int,
    body: PatchJobBody,
    *,
    sender_role: str = "operator",
    apply_stickers: bool = False,
):
    kwargs: dict = {}
    if "text" in body.model_fields_set:
        kwargs["text"] = body.text
    if "scheduled_at" in body.model_fields_set:
        kwargs["scheduled_at"] = body.scheduled_at
    if "segment" in body.model_fields_set:
        kwargs["segment"] = body.segment
    if "destination" in body.model_fields_set:
        kwargs["destination"] = body.destination
    if "sticker_mode" in body.model_fields_set:
        kwargs["sticker_mode"] = body.sticker_mode
    if "selected_sticker_ids" in body.model_fields_set:
        kwargs["selected_sticker_ids"] = body.selected_sticker_ids
    return await bs.patch_job(
        job_id,
        sender_role=sender_role,
        apply_stickers=apply_stickers,
        **kwargs,
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


async def launch_job(job_id: int):
    return await bs.launch_draft(job_id)


async def list_schedules(limit: int = 50):
    return {"schedules": await bs.list_schedules(limit=limit)}


async def create_schedule(
    body: CreateScheduleBody,
    *,
    sender_role: str,
    sender_id: int,
    sender_label: str | None,
    apply_stickers: bool = False,
):
    return await bs.create_schedule(
        sender_role=sender_role,
        sender_id=sender_id,
        sender_label=sender_label,
        segment=body.segment,
        message_text=body.text,
        photo_file_id=body.photo_file_id,
        sticker_mode=body.sticker_mode if apply_stickers else "none",
        selected_sticker_ids=body.selected_sticker_ids if apply_stickers else [],
        apply_stickers=apply_stickers,
        time_local=body.time_local,
        days_of_week=body.days_of_week,
        enabled=body.enabled,
        destination=body.destination,
    )


async def patch_schedule(
    schedule_id: int,
    body: PatchScheduleBody,
    *,
    sender_role: str,
    apply_stickers: bool = False,
):
    kwargs: dict = {}
    if "text" in body.model_fields_set:
        kwargs["text"] = body.text
    if "segment" in body.model_fields_set:
        kwargs["segment"] = body.segment
    if "destination" in body.model_fields_set:
        kwargs["destination"] = body.destination
    if "time_local" in body.model_fields_set:
        kwargs["time_local"] = body.time_local
    if "days_of_week" in body.model_fields_set:
        kwargs["days_of_week"] = body.days_of_week
    if "enabled" in body.model_fields_set:
        kwargs["enabled"] = body.enabled
    if "sticker_mode" in body.model_fields_set:
        kwargs["sticker_mode"] = body.sticker_mode
    if "selected_sticker_ids" in body.model_fields_set:
        kwargs["selected_sticker_ids"] = body.selected_sticker_ids
    if "photo_file_id" in body.model_fields_set:
        kwargs["photo_file_id"] = body.photo_file_id
    return await bs.patch_schedule(
        schedule_id,
        sender_role=sender_role,
        apply_stickers=apply_stickers,
        **kwargs,
    )


async def delete_schedule(schedule_id: int):
    return await bs.delete_schedule(schedule_id)


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


async def list_project_stickers():
    if not bs.BROADCAST_STICKERS_ENABLED:
        return {
            "stickers": [],
            "available_count": 0,
            "catalog_empty": True,
            "set_names": [],
        }
    from broadcast_stickers import catalog_with_availability

    return await catalog_with_availability()


async def sticker_preview(sticker_id: str):
    from broadcast_stickers import download_sticker_preview

    result = await download_sticker_preview(sticker_id)
    if not result:
        raise HTTPException(status_code=404, detail="Стикер недоступен")
    content, mime = result
    return Response(
        content=content,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=86400"},
    )


async def ai_draft(body: AiDraftBody):
    from broadcast_ai import improve_draft

    return await improve_draft(
        text=body.text,
        ai_enabled=body.ai_enabled,
        ai_provider_profile=body.ai_provider_profile,
    )
