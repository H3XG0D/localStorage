"""Русские шашки: лобби без входа, стол только со своим токеном."""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from auth import bearer_scheme, decode_token, get_current_user, get_web_user_by_id, resolve_client_user_id
from casino_draughts import (
    act,
    answer_draw,
    create_table,
    join_table,
    leave_table,
    list_open_tables,
    offer_draw,
    snapshot,
    subscribe_table,
    unsubscribe_table,
)
from db import get_pool

public_router = APIRouter()
user_router = APIRouter()


class CreateBody(BaseModel):
    stake_rub: Decimal = Field(..., gt=0)


class MoveBody(BaseModel):
    notation: str = Field(..., min_length=3, max_length=80)
    expected_version: int = Field(..., ge=0)


class DrawAnswerBody(BaseModel):
    accept: bool


async def _table_user(
    request: Request,
    access_token: str | None = Query(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else access_token
    if token:
        payload = decode_token(token)
        if payload.get("scope", "user") != "user":
            raise HTTPException(status_code=403, detail="Use the correct login for this token")
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        user = await get_web_user_by_id(int(user_id))
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return dict(user)
    return await get_current_user(request, credentials)


@public_router.get("/casino/draughts/tables")
async def public_draughts_tables() -> dict[str, object]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await list_open_tables(conn)


@user_router.post("/casino/draughts/tables")
async def post_draughts_table(body: CreateBody, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await create_table(conn, creator_id=viewer, stake_rub=body.stake_rub)


@user_router.get("/casino/draughts/tables/{table_id}")
async def get_draughts_table(table_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await snapshot(conn, table_id=table_id.strip(), viewer_id=viewer)


@user_router.post("/casino/draughts/tables/{table_id}/join")
async def post_draughts_join(table_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await join_table(conn, table_id=table_id.strip(), user_id=viewer)


@user_router.post("/casino/draughts/tables/{table_id}/leave")
async def post_draughts_leave(table_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await leave_table(conn, table_id=table_id.strip(), user_id=viewer)


@user_router.post("/casino/draughts/tables/{table_id}/act")
async def post_draughts_act(
    table_id: str,
    body: MoveBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await act(
                conn,
                table_id=table_id.strip(),
                user_id=viewer,
                notation=body.notation,
                expected_version=body.expected_version,
            )


@user_router.post("/casino/draughts/tables/{table_id}/draw")
async def post_draughts_draw(table_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await offer_draw(conn, table_id=table_id.strip(), user_id=viewer)


@user_router.post("/casino/draughts/tables/{table_id}/draw-answer")
async def post_draughts_draw_answer(
    table_id: str,
    body: DrawAnswerBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await answer_draw(conn, table_id=table_id.strip(), user_id=viewer, accept=body.accept)


@user_router.get("/casino/draughts/tables/{table_id}/events")
async def draughts_table_events(table_id: str, current_user: dict = Depends(_table_user)):
    _ = resolve_client_user_id(current_user)
    key = table_id.strip()

    async def event_stream():
        queue = subscribe_table(key)
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe_table(key, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
