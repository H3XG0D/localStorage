"""Live Telegram sticker packs for broadcast. Unique ids only — no client file_id."""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from fastapi import HTTPException

from config import settings

logger = logging.getLogger("broadcast_stickers")

MAX_STICKERS_PER_JOB = 1
# Telegram file_unique_id. Reject Bot API file_id (CAAC…) and old slugs (07_promo).
STICKER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_OLD_SLUG_RE = re.compile(r"^[0-9]{2}_[a-z0-9_]+$")

STICKER_STATUS_NONE = "none"
STICKER_STATUS_SELECTED = "selected"
STICKER_STATUS_AUTO = "auto"
STICKER_STATUS_SKIPPED_EMPTY = "skipped_empty_catalog"

_FALLBACK_EMOJI: tuple[tuple[tuple[str, ...], str], ...] = (
    (("промо", "скидк", "бонус", "подарок", "розыгрыш", "кэшбэк", "кешбэк", "выгод", "promo", "gift"), "✨"),
    (("курс", "pulse", "rate", "котир"), "🪐"),
    (("оплат", "paid", "карт", "сбп"), "🔑"),
    (("готов", "done", "успеш"), "✔️"),
    (("спасиб", "thank"), "💌"),
    (("помог", "help", "support"), "🩹"),
    (("привет", "hello", "hi "), "🪽"),
    (("новост", "news", "обновл"), "📝"),
)
_DEFAULT_EMOJIS = ("⭐", "✨", "✔️", "🪐")

_preview_cache: dict[str, tuple[float, bytes, str]] = {}
_PREVIEW_TTL_SEC = 6 * 3600


def allowed_set_names() -> list[str]:
    return []


def _normalize_id(value: str) -> str:
    return (value or "").strip()


def _is_unique_id(value: str) -> bool:
    sid = _normalize_id(value)
    if not sid or sid.upper().startswith("CAAC"):
        return False
    if _OLD_SLUG_RE.match(sid):
        return False
    return bool(STICKER_ID_RE.match(sid))


def validate_sticker_ids(
    ids: list[str] | None,
    *,
    max_count: int = MAX_STICKERS_PER_JOB,
    catalog_ids: set[str] | None = None,
) -> list[str]:
    raw = list(ids or [])
    if len(raw) > max_count:
        raise HTTPException(status_code=400, detail=f"Не больше {max_count} стикеров")
    out: list[str] = []
    seen: set[str] = set()
    allowed = catalog_ids
    for item in raw:
        sid = _normalize_id(str(item))
        if not sid:
            continue
        if not _is_unique_id(sid):
            raise HTTPException(status_code=400, detail="Неизвестный sticker_id")
        if allowed is not None and sid not in allowed:
            raise HTTPException(status_code=400, detail="Неизвестный sticker_id")
        if sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    return out


def filter_known_ids(ids: list[str] | None, catalog_ids: set[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in ids or []:
        sid = _normalize_id(str(item))
        if not sid or sid in seen or not _is_unique_id(sid) or sid not in catalog_ids:
            continue
        seen.add(sid)
        out.append(sid)
        if len(out) >= MAX_STICKERS_PER_JOB:
            break
    return out


def pick_fallback_sticker_id(text: str, catalog: list[dict[str, Any]]) -> str | None:
    if not catalog:
        return None
    by_emoji: dict[str, str] = {}
    for item in catalog:
        emoji = str(item.get("emoji") or "").strip()
        sid = str(item.get("id") or "").strip()
        if emoji and sid and emoji not in by_emoji:
            by_emoji[emoji] = sid
    blob = (text or "").strip().lower()
    want = ""
    for needles, emoji in _FALLBACK_EMOJI:
        if any(n in blob for n in needles) and emoji in by_emoji:
            want = emoji
            break
    if want:
        return by_emoji[want]
    for emoji in _DEFAULT_EMOJIS:
        if emoji in by_emoji:
            return by_emoji[emoji]
    return str(catalog[0].get("id") or "").strip() or None


def plan_sticker_ids(
    *,
    sticker_mode: str,
    selected_sticker_ids: list[str] | None,
    text: str,
    catalog: list[dict[str, Any]] | None = None,
) -> tuple[list[str], str]:
    items = list(catalog or [])
    known = {str(item.get("id") or "") for item in items if item.get("id")}
    mode = (sticker_mode or STICKER_STATUS_NONE).strip().lower()
    if mode not in (STICKER_STATUS_NONE, STICKER_STATUS_SELECTED, STICKER_STATUS_AUTO):
        raise HTTPException(status_code=400, detail="Неизвестный sticker_mode")
    if mode == STICKER_STATUS_NONE:
        return [], STICKER_STATUS_NONE
    selected = filter_known_ids(selected_sticker_ids, known)
    if mode == STICKER_STATUS_SELECTED:
        if not selected:
            return [], STICKER_STATUS_NONE
        return selected, STICKER_STATUS_SELECTED
    if selected:
        return selected, STICKER_STATUS_SELECTED
    if not items:
        return [], STICKER_STATUS_SKIPPED_EMPTY
    picked = pick_fallback_sticker_id(text, items)
    if not picked:
        return [], STICKER_STATUS_SKIPPED_EMPTY
    return [picked], STICKER_STATUS_AUTO


async def _fetch_allowlisted_sets() -> list[dict[str, Any]]:
    names = allowed_set_names()
    if not names:
        return []
    from chat_stickers import _get_sticker_set, _normalize_set_name

    sets: list[dict[str, Any]] = []
    for raw_name in names:
        try:
            name = _normalize_set_name(raw_name)
        except HTTPException:
            logger.warning("broadcast sticker set skipped: invalid name")
            continue
        item = await _get_sticker_set(name)
        if item and item.get("stickers"):
            sets.append(item)
    return sets


async def list_live_catalog() -> list[dict[str, Any]]:
    sets = await _fetch_allowlisted_sets()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for st_set in sets:
        set_name = str(st_set.get("name") or "")
        for st in st_set.get("stickers") or []:
            if st.get("is_video") or st.get("is_animated"):
                continue
            uid = _normalize_id(str(st.get("file_unique_id") or ""))
            fid = _normalize_id(str(st.get("file_id") or ""))
            if not uid or not fid or uid in seen or not _is_unique_id(uid):
                continue
            seen.add(uid)
            emoji = str(st.get("emoji") or "")
            out.append(
                {
                    "id": uid,
                    "emoji": emoji,
                    "label": emoji or uid,
                    "file_id": fid,
                    "set_name": set_name,
                    "preview_url": f"/broadcast/stickers/{uid}/preview",
                    "available": True,
                }
            )
    return out


async def catalog_with_availability() -> dict[str, Any]:
    stickers = await list_live_catalog()
    public = [
        {
            "id": item["id"],
            "emoji": item.get("emoji") or "",
            "label": item.get("label") or item["id"],
            "preview_url": item.get("preview_url") or "",
            "available": True,
        }
        for item in stickers
    ]
    return {
        "stickers": public,
        "available_count": len(public),
        "catalog_empty": not bool(public),
        "set_names": allowed_set_names(),
    }


def catalog_ids_from(catalog: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("id") or "") for item in catalog if item.get("id")}


async def resolve_sticker_file_ids(sticker_ids: list[str]) -> tuple[list[str], str | None]:
    catalog = await list_live_catalog()
    known = catalog_ids_from(catalog)
    valid = filter_known_ids(sticker_ids, known)
    if not valid:
        return [], STICKER_STATUS_SKIPPED_EMPTY if sticker_ids else None
    by_id = {item["id"]: item for item in catalog}
    file_ids: list[str] = []
    for sid in valid:
        fid = str((by_id.get(sid) or {}).get("file_id") or "").strip()
        if fid:
            file_ids.append(fid)
    if not file_ids:
        return [], STICKER_STATUS_SKIPPED_EMPTY
    return file_ids, None


async def download_sticker_preview(sticker_id: str) -> tuple[bytes, str] | None:
    sid = _normalize_id(sticker_id)
    if not _is_unique_id(sid):
        return None
    now = time.time()
    cached = _preview_cache.get(sid)
    if cached and now - cached[0] < _PREVIEW_TTL_SEC:
        return cached[1], cached[2]
    catalog = await list_live_catalog()
    item = next((row for row in catalog if row.get("id") == sid), None)
    fid = str((item or {}).get("file_id") or "").strip()
    if not fid:
        return None
    from telegram_notify import download_telegram_file

    result = await download_telegram_file(fid)
    if not result:
        return None
    content, mime = result
    _preview_cache[sid] = (now, content, mime)
    if len(_preview_cache) > 200:
        oldest = sorted(_preview_cache.items(), key=lambda kv: kv[1][0])[:40]
        for key, _ in oldest:
            _preview_cache.pop(key, None)
    return content, mime


def public_sticker_rows(sticker_ids: list[str], *, status: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for sid in sticker_ids:
        uid = _normalize_id(sid)
        if not uid:
            continue
        rows.append(
            {
                "id": uid,
                "label": uid,
                "emoji": "",
                "preview_url": f"/broadcast/stickers/{uid}/preview",
            }
        )
    return rows
