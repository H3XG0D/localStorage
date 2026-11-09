"""Sticker sets for operator chat (Telegram Bot API getStickerSet)."""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import aiohttp
from fastapi import HTTPException

from config import settings

logger = logging.getLogger("chat_stickers")

_CACHE_TTL_SEC = 300
_MAX_SETS_PER_OPERATOR = 10
_SET_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,256}$")

_cache: dict[int | str, dict[str, Any]] = {}


def _normalize_set_name(name: str) -> str:
    raw = (name or "").strip().lstrip("@")
    if not raw or not _SET_NAME_RE.match(raw):
        raise HTTPException(
            status_code=400,
            detail="Имя набора: латиница, цифры и _, без @ (как в Telegram)",
        )
    return raw


def invalidate_sticker_cache(operator_id: int | None = None) -> None:
    if operator_id is None:
        _cache.clear()
        return
    _cache.pop(int(operator_id), None)
    _cache.pop("global", None)


async def _get_sticker_set(name: str) -> dict | None:
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return None
    url = f"https://api.telegram.org/bot{token}/getStickerSet"
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params={"name": name}) as r:
                data = await r.json()
                if not data.get("ok"):
                    logger.warning("getStickerSet %s failed: %s", name, data)
                    return None
                result = data.get("result") or {}
                stickers = []
                for st in result.get("stickers") or []:
                    stickers.append(
                        {
                            "file_id": st.get("file_id"),
                            "emoji": st.get("emoji") or "",
                            "file_unique_id": st.get("file_unique_id"),
                            "is_video": bool(st.get("is_video")),
                            "is_animated": bool(st.get("is_animated")),
                        }
                    )
                return {
                    "name": result.get("name") or name,
                    "title": result.get("title") or name,
                    "stickers": stickers,
                }
    except Exception as e:
        logger.warning("getStickerSet %s error: %s", name, e)
        return None


async def _operator_set_names(operator_id: int | None) -> list[str]:
    names = list(settings.operator_sticker_set_names)
    if operator_id is None:
        return names
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT set_name FROM operator_sticker_sets
            WHERE operator_id = $1
            ORDER BY id
            """,
            int(operator_id),
        )
    seen = set(names)
    for row in rows:
        n = (row["set_name"] or "").strip()
        if n and n not in seen:
            names.append(n)
            seen.add(n)
    return names


async def fetch_operator_sticker_sets(
    operator_id: int | None = None,
    *,
    force: bool = False,
) -> list[dict]:
    cache_key: int | str = int(operator_id) if operator_id is not None else "global"
    now = time.time()
    cached = _cache.get(cache_key)
    if not force and cached and now - float(cached.get("at", 0)) < _CACHE_TTL_SEC:
        return list(cached.get("sets") or [])

    names = await _operator_set_names(operator_id)
    if not names:
        _cache[cache_key] = {"at": now, "sets": []}
        return []

    sets: list[dict] = []
    for name in names:
        item = await _get_sticker_set(name)
        if item and item.get("stickers"):
            sets.append(item)

    _cache[cache_key] = {"at": now, "sets": sets}
    return list(sets)


async def sticker_file_id_allowed(
    file_id: str,
    operator_id: int | None = None,
) -> bool:
    fid = (file_id or "").strip()
    if not fid:
        return False
    for st_set in await fetch_operator_sticker_sets(operator_id):
        for st in st_set.get("stickers") or []:
            if st.get("file_id") == fid:
                return True
    return False


def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "operator_id": row["operator_id"],
        "set_name": row["set_name"],
        "title": row.get("title"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


async def list_my_sticker_sets(operator_id: int) -> list[dict]:
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, operator_id, set_name, title, created_at
            FROM operator_sticker_sets
            WHERE operator_id = $1
            ORDER BY id
            """,
            int(operator_id),
        )
    return [_row_to_dict(r) for r in rows]


async def add_operator_sticker_set(operator_id: int, set_name: str) -> dict:
    name = _normalize_set_name(set_name)
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM operator_sticker_sets WHERE operator_id = $1",
            int(operator_id),
        )
        if int(count or 0) >= _MAX_SETS_PER_OPERATOR:
            raise HTTPException(
                status_code=400,
                detail=f"Не более {_MAX_SETS_PER_OPERATOR} наборов на оператора",
            )

    item = await _get_sticker_set(name)
    if not item or not item.get("stickers"):
        raise HTTPException(
            status_code=400,
            detail="Набор не найден или бот не имеет к нему доступа",
        )

    title = item.get("title") or name
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO operator_sticker_sets (operator_id, set_name, title)
                VALUES ($1, $2, $3)
                ON CONFLICT (operator_id, set_name) DO UPDATE SET title = EXCLUDED.title
                RETURNING id, operator_id, set_name, title, created_at
                """,
                int(operator_id),
                name,
                title,
            )
        except Exception as e:
            logger.exception("add_operator_sticker_set failed op=%s name=%s", operator_id, name)
            raise HTTPException(status_code=400, detail="Не удалось сохранить набор") from e

    invalidate_sticker_cache(int(operator_id))
    return _row_to_dict(row)


async def remove_operator_sticker_set(operator_id: int, row_id: int) -> None:
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM operator_sticker_sets
            WHERE id = $1 AND operator_id = $2
            """,
            int(row_id),
            int(operator_id),
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Набор не найден")
    invalidate_sticker_cache(int(operator_id))
