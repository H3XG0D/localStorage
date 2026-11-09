"""Рассылка — панель оператора."""
from fastapi import APIRouter, Depends, File, Query, UploadFile

from auth import get_current_operator
from routers import broadcast_handlers as bh

router = APIRouter()


def _operator_label(operator: dict) -> str:
    return operator.get("display_name") or operator.get("username") or f"op#{operator.get('id')}"


@router.get("/broadcast/segments")
async def segments(_operator=Depends(get_current_operator)):
    return await bh.segments_list()


@router.post("/broadcast/preview")
async def preview(body: bh.PreviewBody, _operator=Depends(get_current_operator)):
    return await bh.preview_segment(body, apply_stickers=False)


@router.get("/broadcast/stickers")
async def stickers(_operator=Depends(get_current_operator)):
    return await bh.list_project_stickers()


@router.get("/broadcast/stickers/{sticker_id}/preview")
async def sticker_preview(sticker_id: str, _operator=Depends(get_current_operator)):
    return await bh.sticker_preview(sticker_id)


@router.post("/broadcast/ai-draft")
async def ai_draft(body: bh.AiDraftBody, _operator=Depends(get_current_operator)):
    return await bh.ai_draft(body)


@router.post("/broadcast/upload-photo")
async def upload_photo(
    file: UploadFile = File(...),
    _operator=Depends(get_current_operator),
):
    return await bh.upload_photo(file)


@router.post("/broadcast/jobs")
async def create_job(body: bh.CreateJobBody, operator=Depends(get_current_operator)):
    return await bh.create_job(
        body,
        sender_role="operator",
        sender_id=int(operator["id"]),
        sender_label=_operator_label(operator),
        apply_stickers=False,
    )


@router.get("/broadcast/jobs")
async def list_jobs(
    limit: int = Query(50, ge=1, le=100),
    _operator=Depends(get_current_operator),
):
    return await bh.list_jobs(limit=limit)


@router.get("/broadcast/jobs/{job_id}")
async def get_job(job_id: int, _operator=Depends(get_current_operator)):
    return await bh.get_job(job_id)


@router.get("/broadcast/jobs/{job_id}/photo")
async def get_job_photo(job_id: int, _operator=Depends(get_current_operator)):
    return await bh.get_job_photo(job_id)


@router.post("/broadcast/jobs/{job_id}/cancel")
async def cancel_job(job_id: int, _operator=Depends(get_current_operator)):
    return await bh.cancel_job(job_id)


@router.post("/broadcast/jobs/{job_id}/launch")
async def launch_job(job_id: int, _operator=Depends(get_current_operator)):
    return await bh.launch_job(job_id)


@router.patch("/broadcast/jobs/{job_id}")
async def patch_job(job_id: int, body: bh.PatchJobBody, _operator=Depends(get_current_operator)):
    return await bh.patch_job(job_id, body, sender_role="operator", apply_stickers=False)


@router.get("/broadcast/schedules")
async def list_schedules(
    limit: int = Query(50, ge=1, le=100),
    _operator=Depends(get_current_operator),
):
    return await bh.list_schedules(limit=limit)


@router.post("/broadcast/schedules")
async def create_schedule(body: bh.CreateScheduleBody, operator=Depends(get_current_operator)):
    return await bh.create_schedule(
        body,
        sender_role="operator",
        sender_id=int(operator["id"]),
        sender_label=_operator_label(operator),
        apply_stickers=False,
    )


@router.patch("/broadcast/schedules/{schedule_id}")
async def patch_schedule(
    schedule_id: int,
    body: bh.PatchScheduleBody,
    operator=Depends(get_current_operator),
):
    return await bh.patch_schedule(
        schedule_id,
        body,
        sender_role="operator",
        apply_stickers=False,
    )


@router.delete("/broadcast/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int, _operator=Depends(get_current_operator)):
    return await bh.delete_schedule(schedule_id)
