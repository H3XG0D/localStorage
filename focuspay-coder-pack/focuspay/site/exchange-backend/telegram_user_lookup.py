"""Поиск клиента по Telegram @username или user_id."""
from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp

from config import settings

logger = logging.getLogger("telegram_user_lookup")

_TG_USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{3,31}$")


def normalize_search_term(raw: str) -> str:
    return (raw or "").strip().lstrip("@")


def looks_like_telegram_username(term: str) -> bool:
    return bool(_TG_USERNAME_RE.match(term))


def user_hit(
    user_id: int,
    username: str | None,
    first_name: str | None,
    *,
    is_banned: bool = False,
    ban_type: str | None = None,
) -> dict[str, Any]:
    from bot_user_avatars import bot_user_avatar_public_url

    un = (username or "").strip()
    display = f"@{un}" if un else (first_name or str(user_id))
    uid = int(user_id)
    banned = bool(is_banned)
    bt = (ban_type or "hard") if banned else None
    return {
        "user_id": uid,
        "username": un or None,
        "first_name": first_name,
        "display": display,
        "avatar_url": bot_user_avatar_public_url(uid),
        "is_banned": banned,
        "ban_type": bt,
    }


async def _ban_fields_for_user(conn, user_id: int) -> tuple[bool, str | None]:
    row = await conn.fetchrow(
        "SELECT is_banned, ban_type FROM bot_users WHERE user_id = $1",
        int(user_id),
    )
    if not row:
        return False, None
    banned = bool(row["is_banned"])
    return banned, ((row["ban_type"] or "hard") if banned else None)


async def enrich_hit_ban(conn, hit: dict[str, Any]) -> dict[str, Any]:
    """Подтянуть is_banned/ban_type из БД (для API-first hits без бан-полей)."""
    banned, ban_type = await _ban_fields_for_user(conn, int(hit["user_id"]))
    out = dict(hit)
    out["is_banned"] = banned
    out["ban_type"] = ban_type
    return out


async def search_bot_users_in_db(conn, term: str, *, limit: int = 20) -> list[dict]:
    """Поиск в bot_users: ID, точный @username, префикс username, имя."""
    if term.isdigit():
        rows = await conn.fetch(
            """
            SELECT user_id, username, first_name, is_banned, ban_type
            FROM bot_users
            WHERE user_id::text = $1 OR user_id::text LIKE $2
            ORDER BY last_seen_at DESC NULLS LAST
            LIMIT $3
            """,
            term,
            f"{term}%",
            limit,
        )
        return [
            user_hit(
                r["user_id"],
                r["username"],
                r["first_name"],
                is_banned=bool(r["is_banned"]),
                ban_type=r["ban_type"],
            )
            for r in rows
        ]

    name_pattern = f"%{term}%"
    username_prefix = f"{term}%"
    rows = await conn.fetch(
        """
        SELECT user_id, username, first_name, is_banned, ban_type
        FROM bot_users
        WHERE lower(username) = lower($1)
           OR username ILIKE $2
           OR first_name ILIKE $3
        ORDER BY
            CASE
                WHEN lower(username) = lower($1) THEN 0
                WHEN username ILIKE $2 THEN 1
                ELSE 2
            END,
            last_seen_at DESC NULLS LAST
        LIMIT $4
        """,
        term,
        username_prefix,
        name_pattern,
        limit,
    )
    return [
        user_hit(
            r["user_id"],
            r["username"],
            r["first_name"],
            is_banned=bool(r["is_banned"]),
            ban_type=r["ban_type"],
        )
        for r in rows
    ]


async def resolve_telegram_username_via_api(username: str) -> dict[str, Any] | None:
    """
    Telegram getChat по @username (работает, если пользователь уже писал боту).
    """
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return None
    uname = normalize_search_term(username)
    if not looks_like_telegram_username(uname):
        return None
    url = f"https://api.telegram.org/bot{token}/getChat"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params={"chat_id": f"@{uname}"},
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                data = await resp.json()
    except Exception as e:
        logger.warning("getChat @%s failed: %s", uname, e)
        return None
    if not data.get("ok"):
        logger.debug("getChat @%s: %s", uname, data.get("description"))
        return None
    chat = data.get("result") or {}
    if chat.get("type") != "private":
        return None
    uid = chat.get("id")
    if uid is None:
        return None
    return user_hit(
        int(uid),
        chat.get("username") or uname,
        chat.get("first_name"),
    )


async def _persist_bot_user_hit(hit: dict[str, Any]) -> None:
    from auth import ensure_bot_user

    await ensure_bot_user(
        hit["user_id"],
        hit.get("username"),
        hit.get("first_name"),
    )


async def _resolve_username_via_api_first(term: str) -> dict[str, Any] | None:
    """Актуальный @username через Telegram API (важно после смены handle)."""
    if not looks_like_telegram_username(term):
        return None
    tg = await resolve_telegram_username_via_api(term)
    if not tg:
        return None
    await _persist_bot_user_hit(tg)
    return tg


async def resolve_single_recipient(conn, raw: str) -> dict[str, Any] | None:
    """Точное определение одного получателя по Telegram ID или @username.

    Возвращает user_hit (user_id/username/first_name) или None, если не найден.
    """
    term = normalize_search_term(raw)
    if not term:
        return None

    if term.isdigit():
        uid = int(term)
        row = await conn.fetchrow(
            "SELECT user_id, username, first_name, is_banned, ban_type FROM bot_users WHERE user_id = $1",
            uid,
        )
        if row:
            return user_hit(
                row["user_id"],
                row["username"],
                row["first_name"],
                is_banned=bool(row["is_banned"]),
                ban_type=row["ban_type"],
            )
        return user_hit(uid, None, None)

    tg = await _resolve_username_via_api_first(term)
    if tg:
        return await enrich_hit_ban(conn, tg)

    row = await conn.fetchrow(
        """
        SELECT user_id, username, first_name, is_banned, ban_type
        FROM bot_users
        WHERE lower(username) = lower($1)
        ORDER BY last_seen_at DESC NULLS LAST
        LIMIT 1
        """,
        term,
    )
    if row:
        return user_hit(
            row["user_id"],
            row["username"],
            row["first_name"],
            is_banned=bool(row["is_banned"]),
            ban_type=row["ban_type"],
        )
    return None


async def search_client_by_telegram(
    conn,
    raw_query: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Поиск покупателя: для @username — сначала Telegram API (актуальный handle),
    затем дополнение из БД; для ID — только БД.
    """
    term = normalize_search_term(raw_query)
    if not term:
        return []

    hits: list[dict[str, Any]] = []
    seen: set[int] = set()

    if looks_like_telegram_username(term):
        tg = await _resolve_username_via_api_first(term)
        if tg:
            hits.append(await enrich_hit_ban(conn, tg))
            seen.add(tg["user_id"])

    db_hits = await search_bot_users_in_db(conn, term, limit=limit)
    for h in db_hits:
        if h["user_id"] not in seen:
            hits.append(h)
            seen.add(h["user_id"])
        elif hits and hits[0]["user_id"] == h["user_id"]:
            # API hit без бана — подтянуть поля из БД-хита
            hits[0] = h

    from bot_user_avatars import fetch_and_cache_bot_user_avatar

    for h in hits[:5]:
        try:
            await fetch_and_cache_bot_user_avatar(h["user_id"])
        except Exception as e:
            logger.debug("avatar prefetch uid=%s: %s", h["user_id"], e)

    return hits[:limit]
