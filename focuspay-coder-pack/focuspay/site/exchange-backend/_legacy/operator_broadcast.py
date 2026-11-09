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
    return await bh.preview_segment(body)


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
