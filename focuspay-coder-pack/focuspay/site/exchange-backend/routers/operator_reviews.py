"""Модерация отзывов — кабинет оператора."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import get_current_operator
import review_moderation_service as rms

router = APIRouter()


class PublishBody(BaseModel):
    bonus: Literal["text", "photo", "none"] = "text"


class RejectBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


@router.get("/reviews/pending-count")
async def reviews_pending_count(_op: dict = Depends(get_current_operator)):
    del _op
    return {"count": await rms.pending_count()}


@router.get("/reviews")
async def list_reviews(
    status: Literal["pending", "published", "rejected", "all"] = Query("pending"),
    q: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    _op: dict = Depends(get_current_operator),
):
    del _op
    return await rms.list_reviews(
        status=status, q=q, user_id=user_id, page=page, limit=limit
    )


@router.get("/reviews/{submission_id}")
async def get_review(
    submission_id: int,
    _op: dict = Depends(get_current_operator),
):
    del _op
    row = await rms.get_review(submission_id)
    if not row:
        raise HTTPException(status_code=404, detail="Отзыв не найден")
    return row


@router.get("/reviews/{submission_id}/photo")
async def get_review_photo(
    submission_id: int,
    _op: dict = Depends(get_current_operator),
):
    del _op
    result = await rms.get_review_photo_bytes(submission_id)
    if not result:
        raise HTTPException(status_code=404, detail="Скрин недоступен")
    content, mime = result
    return Response(content=content, media_type=mime)


@router.post("/reviews/{submission_id}/publish")
async def publish_review(
    submission_id: int,
    body: PublishBody,
    op: dict = Depends(get_current_operator),
):
    try:
        return await rms.publish_review(
            submission_id,
            bonus=body.bonus,
            operator_id=int(op["id"]),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/reviews/{submission_id}/reject")
async def reject_review(
    submission_id: int,
    body: RejectBody,
    op: dict = Depends(get_current_operator),
):
    try:
        return await rms.reject_review(
            submission_id,
            operator_id=int(op["id"]),
            reason=body.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
