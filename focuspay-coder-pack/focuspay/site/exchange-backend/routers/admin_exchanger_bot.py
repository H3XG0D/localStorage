"""Админка общего TG-бота внештатников: токен, whitelist, рассылка."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from auth import get_current_finance_owner
from db import get_pool
from exchanger_bot_broadcast import (
    cancel_broadcast,
    create_broadcast,
    list_broadcasts,
    list_recipient_ids,
)
from exchanger_bot_config import (
    clear_token,
    configure_token,
    fetch_config_row,
    public_config,
    reconfigure,
)

router = APIRouter()


class TokenBody(BaseModel):
    token: str

    @field_validator("token")
    @classmethod
    def _token(cls, v: str) -> str:
        t = (v or "").strip()
        if len(t) < 20 or ":" not in t:
            raise ValueError("Не похоже на токен Telegram-бота")
        return t


class MemberBody(BaseModel):
    telegram_user_id: int
    exchanger_id: int
    role: str = "owner"
    label: Optional[str] = None

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        r = (v or "owner").strip().lower()
        if r not in ("owner", "clerk"):
            raise ValueError("role must be owner or clerk")
        return r


class MemberPatch(BaseModel):
    role: Optional[str] = None
    label: Optional[str] = None
    is_active: Optional[bool] = None
    exchanger_id: Optional[int] = None


class BroadcastBody(BaseModel):
    audience: str = "all"
    text: str


async def _members_count() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval("SELECT COUNT(*) FROM exchanger_bot_members WHERE is_active = TRUE") or 0)


@router.get("/exchanger-bot")
async def get_exchanger_bot(_owner=Depends(get_current_finance_owner)):
    row = await fetch_config_row()
    return public_config(row, members_count=await _members_count())


@router.put("/exchanger-bot/token")
async def put_exchanger_bot_token(body: TokenBody, owner=Depends(get_current_finance_owner)):
    result = await configure_token(body.token, updated_by=owner.get("id"))
    result["members_count"] = await _members_count()
    return result


@router.post("/exchanger-bot/reconfigure")
async def post_exchanger_bot_reconfigure(_owner=Depends(get_current_finance_owner)):
    result = await reconfigure()
    result["members_count"] = await _members_count()
    return result


@router.delete("/exchanger-bot/token")
async def delete_exchanger_bot_token(_owner=Depends(get_current_finance_owner)):
    result = await clear_token()
    result["members_count"] = await _members_count()
    return result


@router.get("/exchanger-bot/members")
async def list_members(_owner=Depends(get_current_finance_owner)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT m.*, e.name AS exchanger_name
            FROM exchanger_bot_members m
            JOIN external_exchangers e ON e.id = m.exchanger_id
            ORDER BY m.id DESC
            """
        )
    items = []
    for row in rows:
        data = dict(row)
        for key in ("created_at", "last_seen_at"):
            if data.get(key) is not None:
                data[key] = data[key].isoformat()
        items.append(data)
    return {"items": items}


@router.post("/exchanger-bot/members", status_code=201)
async def create_member(body: MemberBody, _owner=Depends(get_current_finance_owner)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        ex = await conn.fetchrow(
            "SELECT id FROM external_exchangers WHERE id = $1",
            body.exchanger_id,
        )
        if not ex:
            raise HTTPException(status_code=404, detail="Магазин не найден")
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO exchanger_bot_members (
                    telegram_user_id, exchanger_id, role, label
                ) VALUES ($1, $2, $3, $4)
                RETURNING *
                """,
                body.telegram_user_id,
                body.exchanger_id,
                body.role,
                (body.label or "").strip() or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Этот telegram id уже выдан") from exc
    return {"member": dict(row)}


@router.patch("/exchanger-bot/members/{member_id}")
async def patch_member(
    member_id: int,
    body: MemberPatch,
    _owner=Depends(get_current_finance_owner),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM exchanger_bot_members WHERE id = $1", member_id)
        if not row:
            raise HTTPException(status_code=404, detail="Участник не найден")
        if body.role is not None:
            role = body.role.strip().lower()
            if role not in ("owner", "clerk"):
                raise HTTPException(status_code=400, detail="role must be owner or clerk")
            await conn.execute("UPDATE exchanger_bot_members SET role = $1 WHERE id = $2", role, member_id)
        if body.label is not None:
            await conn.execute(
                "UPDATE exchanger_bot_members SET label = $1 WHERE id = $2",
                body.label.strip() or None,
                member_id,
            )
        if body.is_active is not None:
            await conn.execute(
                "UPDATE exchanger_bot_members SET is_active = $1 WHERE id = $2",
                bool(body.is_active),
                member_id,
            )
        if body.exchanger_id is not None:
            await conn.execute(
                "UPDATE exchanger_bot_members SET exchanger_id = $1 WHERE id = $2",
                int(body.exchanger_id),
                member_id,
            )
        row = await conn.fetchrow("SELECT * FROM exchanger_bot_members WHERE id = $1", member_id)
    return {"member": dict(row)}


@router.delete("/exchanger-bot/members/{member_id}")
async def delete_member(member_id: int, _owner=Depends(get_current_finance_owner)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM exchanger_bot_members WHERE id = $1", member_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Участник не найден")
    return {"ok": True}


@router.get("/exchanger-bot/broadcast/preview")
async def preview_broadcast(audience: str = "all", _owner=Depends(get_current_finance_owner)):
    ids = await list_recipient_ids(audience)
    return {"audience": audience, "count": len(ids)}


@router.post("/exchanger-bot/broadcast")
async def post_broadcast(body: BroadcastBody, owner=Depends(get_current_finance_owner)):
    return await create_broadcast(
        audience=body.audience,
        text=body.text,
        created_by=owner.get("id"),
    )


@router.get("/exchanger-bot/broadcast")
async def get_broadcasts(_owner=Depends(get_current_finance_owner)):
    return {"items": await list_broadcasts()}


@router.post("/exchanger-bot/broadcast/{job_id}/cancel")
async def post_cancel_broadcast(job_id: int, _owner=Depends(get_current_finance_owner)):
    return await cancel_broadcast(job_id)
