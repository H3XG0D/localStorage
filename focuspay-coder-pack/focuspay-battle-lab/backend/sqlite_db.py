"""aiosqlite helpers (fetchone/fetchall on cursor)."""
from __future__ import annotations

import aiosqlite


async def fetchone(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> tuple | None:
    cur = await db.execute(sql, params)
    return await cur.fetchone()


async def fetchall(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    cur = await db.execute(sql, params)
    return await cur.fetchall()
