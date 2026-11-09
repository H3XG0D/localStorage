"""Аватарки клиентов Telegram: кеш с диска, загрузка через Bot API."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import aiohttp

from chat_attachments import make_attachment_access_token, verify_attachment_access_token
from config import settings

logger = logging.getLogger("bot_user_avatars")

BOT_USER_AVATAR_DIR = Path(
    os.getenv("BOT_USER_AVATAR_DIR", "/opt/tg_bot_btc/bot_user_avatars")
)
CACHE_TTL_SECONDS = 7 * 86400
_AVATAR_KEY_PREFIX = "bu:"
_PREFETCH_CONCURRENCY = 4
_prefetch_sema = asyncio.Semaphore(_PREFETCH_CONCURRENCY)


def _avatar_key(user_id: int) -> str:
    return f"{_AVATAR_KEY_PREFIX}{int(user_id)}"


def bot_user_avatar_public_url(user_id: int | None) -> str | None:
    if user_id is None:
        return None
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    if uid <= 0:
        return None
    tok = make_attachment_access_token(_avatar_key(uid), ttl_seconds=86400 * 7)
    return f"/api/public/bot-user-avatars/{uid}?access={tok}"


def verify_bot_user_avatar_access(user_id: int, access: str | None) -> bool:
    return bool(access and verify_attachment_access_token(_avatar_key(user_id), access))


def resolve_bot_user_avatar_path(user_id: int) -> Path | None:
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = BOT_USER_AVATAR_DIR / f"{int(user_id)}{ext}"
        if p.is_file():
            return p
    return None


async def _telegram_api_get(session: aiohttp.ClientSession, method: str, **params):
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        return None
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        return await resp.json()


async def fetch_and_cache_bot_user_avatar(user_id: int) -> Path | None:
    """getUserProfilePhotos + getFile → файл в BOT_USER_AVATAR_DIR."""
    uid = int(user_id)
    existing = resolve_bot_user_avatar_path(uid)
    if existing and (time.time() - existing.stat().st_mtime) < CACHE_TTL_SECONDS:
        return existing

    BOT_USER_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    try:
        async with aiohttp.ClientSession() as session:
            data = await _telegram_api_get(
                session,
                "getUserProfilePhotos",
                user_id=uid,
                limit=1,
            )
            if not data or not data.get("ok"):
                return existing
            photos = (data.get("result") or {}).get("photos") or []
            if not photos or not photos[0]:
                return existing
            sizes = photos[0]
            file_id = sizes[-1].get("file_id") if sizes else None
            if not file_id:
                return existing

            file_data = await _telegram_api_get(session, "getFile", file_id=file_id)
            if not file_data or not file_data.get("ok"):
                return existing
            file_path = (file_data.get("result") or {}).get("file_path")
            if not file_path:
                return existing

            token = (settings.telegram_bot_token or "").strip()
            dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            async with session.get(
                dl_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as dl_resp:
                if dl_resp.status != 200:
                    return existing
                content = await dl_resp.read()
                if len(content) < 64 or len(content) > 5 * 1024 * 1024:
                    return existing

            suffix = ".jpg"
            if file_path.lower().endswith(".png"):
                suffix = ".png"
            elif file_path.lower().endswith(".webp"):
                suffix = ".webp"
            out = BOT_USER_AVATAR_DIR / f"{uid}{suffix}"
            for old in BOT_USER_AVATAR_DIR.glob(f"{uid}.*"):
                if old != out:
                    old.unlink(missing_ok=True)
            out.write_bytes(content)
            return out
    except Exception as e:
        logger.warning("bot user avatar fetch uid=%s: %s", uid, e)
    return existing


def _positive_user_ids(user_ids: list[int] | tuple[int, ...] | None) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for raw in user_ids or []:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            continue
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out


async def _prefetch_one(user_id: int) -> None:
    async with _prefetch_sema:
        try:
            await fetch_and_cache_bot_user_avatar(user_id)
        except Exception:
            logger.debug("avatar prefetch failed uid=%s", user_id, exc_info=True)


async def prefetch_bot_user_avatars(user_ids: list[int] | tuple[int, ...] | None) -> None:
    ids = [
        uid
        for uid in _positive_user_ids(user_ids)
        if resolve_bot_user_avatar_path(uid) is None
    ]
    if not ids:
        return
    await asyncio.gather(*(_prefetch_one(uid) for uid in ids), return_exceptions=True)


def schedule_prefetch_bot_user_avatars(user_ids: list[int] | tuple[int, ...] | None) -> None:
    ids = _positive_user_ids(user_ids)
    if not ids:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(prefetch_bot_user_avatars(ids))
