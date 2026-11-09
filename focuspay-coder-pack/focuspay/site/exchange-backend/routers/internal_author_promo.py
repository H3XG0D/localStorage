"""Выдача купона автора из FocusPayPartnersBot. Секрет общий с трекингом."""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from author_promo import AuthorPromoError, issue_author_promo
from config import settings
from db import get_pool

router = APIRouter()


def _accepted_secrets() -> list[str]:
    values = [
        os.getenv("TRACK_SECRET", "").strip(),
        (settings.internal_api_secret or "").strip(),
    ]
    return [v for v in values if v]


def _verify(token: str | None) -> None:
    expected = _accepted_secrets()
    if not expected:
        raise HTTPException(status_code=503, detail="Author promo API not configured")
    supplied = (token or "").strip()
    if not supplied or not any(hmac.compare_digest(supplied, item) for item in expected):
        raise HTTPException(status_code=403, detail="Forbidden")


class AuthorPromoIn(BaseModel):
    code: str = Field(min_length=3, max_length=32)
    author_telegram_id: int = Field(gt=0)
    video_id: int | None = Field(default=None, ge=1)
    issued_for: str = "first_video"
    author_name: str | None = Field(default=None, max_length=80)


@router.post("/partner-author-promos")
async def create_author_promo(
    body: AuthorPromoIn,
    x_track_secret: str | None = Header(None, alias="X-Track-Secret"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify(x_track_secret or x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            return await issue_author_promo(
                conn,
                code=body.code,
                author_telegram_id=body.author_telegram_id,
                video_id=body.video_id,
                issued_for=body.issued_for,
                author_name=body.author_name,
            )
        except AuthorPromoError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.message) from exc
