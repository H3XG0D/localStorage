"""Cabinet review: text only, bonus on this account after moderation."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user, resolve_client_user_id
from db import get_pool
from site_reviews_submit import (
    ReviewRejected,
    author_label,
    create_text_review,
    load_offer,
    notify_moderators,
)

router = APIRouter()


class ReviewBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.get("/review")
async def review_offer(current_user: dict = Depends(get_current_user)):
    client_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await load_offer(conn, client_id)


@router.post("/review")
async def submit_review(body: ReviewBody, current_user: dict = Depends(get_current_user)):
    client_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            created = await create_text_review(
                conn,
                user_id=client_id,
                text=body.text,
                author=author_label(current_user),
            )
    except ReviewRejected as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    await notify_moderators(int(created["id"]))
    return created
