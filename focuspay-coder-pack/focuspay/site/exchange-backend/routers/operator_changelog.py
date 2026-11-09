"""Operator changelog + deploy confirmation."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_operator
from deployment_events import (
    confirm_deploy_event,
    get_event,
    list_changelog,
)

router = APIRouter()


class ConfirmBody(BaseModel):
    note: str | None = Field(None, max_length=500)


@router.get("/changelog")
async def operator_changelog(
    day: str | None = Query(None, description="UTC date YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _op: dict = Depends(get_current_operator),
):
    del _op
    day_obj: date | None = None
    if day:
        try:
            day_obj = date.fromisoformat(day)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="Invalid day") from e
    return await list_changelog(day=day_obj, limit=limit, offset=offset)


@router.get("/deploy/{event_id}")
async def operator_deploy_get(event_id: int, _op: dict = Depends(get_current_operator)):
    del _op
    row = await get_event(event_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return row


@router.post("/deploy/{event_id}/confirm")
async def operator_deploy_confirm(
    event_id: int,
    body: ConfirmBody,
    op: dict = Depends(get_current_operator),
):
    try:
        return await confirm_deploy_event(event_id, op, note=body.note)
    except LookupError:
        raise HTTPException(status_code=404, detail="Not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
