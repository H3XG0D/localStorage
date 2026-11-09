"""Длинные нарды: список и просмотр без входа, сесть и ходить — со своим токеном."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from auth import get_current_user, resolve_client_user_id
from casino_nardy_table import act, create_table, join_table, leave_table, list_open_tables, snapshot
from db import get_pool

public_router = APIRouter()
user_router = APIRouter()


class CreateBody(BaseModel):
    stake_rub: Decimal = Field(..., gt=0)


class MoveBody(BaseModel):
    move_index: int = Field(..., ge=0)
    expected_version: int = Field(..., ge=0)


@public_router.get("/casino/nardy/tables")
async def public_nardy_tables() -> dict[str, object]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await list_open_tables(conn)


@public_router.get("/casino/nardy/tables/{table_id}")
async def public_nardy_table(table_id: str) -> dict[str, object]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await snapshot(conn, table_id=table_id.strip(), viewer_id=None)


@user_router.post("/casino/nardy/tables")
async def post_nardy_table(body: CreateBody, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await create_table(conn, creator_id=viewer, stake_rub=body.stake_rub)


@user_router.get("/casino/nardy/tables/{table_id}")
async def get_nardy_table(table_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await snapshot(conn, table_id=table_id.strip(), viewer_id=viewer)


@user_router.post("/casino/nardy/tables/{table_id}/join")
async def post_nardy_join(table_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await join_table(conn, table_id=table_id.strip(), user_id=viewer)


@user_router.post("/casino/nardy/tables/{table_id}/leave")
async def post_nardy_leave(table_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await leave_table(conn, table_id=table_id.strip(), user_id=viewer)


@user_router.post("/casino/nardy/tables/{table_id}/act")
async def post_nardy_act(
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
                move_index=body.move_index,
                expected_version=body.expected_version,
            )
