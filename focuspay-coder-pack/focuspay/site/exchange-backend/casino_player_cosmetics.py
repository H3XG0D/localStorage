"""Casino nickname and uploaded avatar. Prefer these over Telegram cache."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping, Sequence

from fastapi import HTTPException

from bot_user_avatars import BOT_USER_AVATAR_DIR
from chat_attachments import make_attachment_access_token, verify_attachment_access_token

NICK_MIN = 2
NICK_MAX = 32
AVATAR_MAX_BYTES = 512 * 1024
_AVATAR_KEY_PREFIX = "ca:"
_NICK_OK = re.compile(r"^[\w .'-]+$", re.UNICODE)
_LINK_RE = re.compile(r"(https?://|t\.me/|tg://)", re.IGNORECASE)
_ALLOWED_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def cosmetics_avatar_stem(user_id: int) -> str:
    uid = int(user_id)
    if uid == 0:
        raise ValueError("user_id must be non-zero")
    if uid < 0:
        return f"casino_n{abs(uid)}"
    return f"casino_{uid}"


def cosmetics_avatar_path_key(user_id: int) -> str:
    """Starlette's int path converter is [0-9]+, so web ids like -1 must not go in the URL as -1."""
    uid = int(user_id)
    if uid == 0:
        raise ValueError("user_id must be non-zero")
    if uid < 0:
        return f"n{abs(uid)}"
    return str(uid)


def parse_signed_user_id(raw: object, *, detail: str = "Игрок не найден") -> int:
    if isinstance(raw, bool) or raw is None:
        raise HTTPException(status_code=404, detail=detail)
    if isinstance(raw, int):
        uid = raw
    else:
        text = str(raw).strip()
        if text.startswith("n") and text[1:].isdigit() and int(text[1:]) > 0:
            uid = -int(text[1:])
        else:
            try:
                uid = int(text)
            except (TypeError, ValueError):
                raise HTTPException(status_code=404, detail=detail)
    if uid == 0:
        raise HTTPException(status_code=404, detail=detail)
    return uid


def cosmetics_avatar_public_url(user_id: int | None, *, has_avatar: bool = True) -> str | None:
    if not has_avatar or user_id is None:
        return None
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    if uid == 0:
        return None
    tok = make_attachment_access_token(f"{_AVATAR_KEY_PREFIX}{uid}", ttl_seconds=86400 * 7)
    return f"/api/public/casino-avatars/{cosmetics_avatar_path_key(uid)}?access={tok}"


def verify_cosmetics_avatar_access(user_id: int, access: str | None) -> bool:
    return bool(access and verify_attachment_access_token(f"{_AVATAR_KEY_PREFIX}{int(user_id)}", access))


def resolve_cosmetics_avatar_path(user_id: int) -> Path | None:
    stem = cosmetics_avatar_stem(int(user_id))
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        path = BOT_USER_AVATAR_DIR / f"{stem}{ext}"
        if path.is_file():
            return path
    return None


def detect_avatar_ext(data: bytes) -> str:
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    raise HTTPException(status_code=400, detail="Нужен JPG, PNG или WebP")


def sanitize_nickname(raw: str) -> str:
    name = (raw or "").replace("\x00", "").strip()
    name = re.sub(r"\s+", " ", name)
    if len(name) < NICK_MIN or len(name) > NICK_MAX:
        raise HTTPException(status_code=400, detail=f"Имя {NICK_MIN}–{NICK_MAX} символов")
    if _LINK_RE.search(name):
        raise HTTPException(status_code=400, detail="В имени нельзя ссылку")
    if not _NICK_OK.match(name):
        raise HTTPException(status_code=400, detail="В имени только буквы, цифры, пробел и .-'")
    return name


async def load_cosmetics_map(conn, user_ids: Sequence[int]) -> dict[int, dict[str, object]]:
    ids: list[int] = []
    seen: set[int] = set()
    for raw in user_ids:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            continue
        if uid == 0 or uid in seen:
            continue
        seen.add(uid)
        ids.append(uid)
    if not ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT user_id, nickname, avatar_ext
        FROM casino_player_cosmetics
        WHERE user_id = ANY($1::bigint[])
        """,
        ids,
    )
    out: dict[int, dict[str, object]] = {}
    for row in rows:
        out[int(row["user_id"])] = {
            "nickname": str(row["nickname"] or "").strip(),
            "avatar_ext": str(row["avatar_ext"] or "").strip() or None,
        }
    return out


def apply_cosmetics(
    user_id: int,
    name: str,
    *,
    avatar_url: str | None,
    cosmetics: Mapping[str, object] | None,
) -> tuple[str, str | None]:
    from casino_default_avatar import default_avatar_url_for_user

    nick = str((cosmetics or {}).get("nickname") or "").strip()
    display = nick or name
    has_file = bool((cosmetics or {}).get("avatar_ext"))
    custom = cosmetics_avatar_public_url(user_id, has_avatar=has_file)
    if custom:
        return display, custom
    if avatar_url:
        return display, avatar_url
    return display, default_avatar_url_for_user(user_id)


async def set_notify_open_tables(conn, user_id: int, enabled: bool) -> None:
    uid = int(user_id)
    if uid == 0:
        raise HTTPException(status_code=400, detail="Нет профиля")
    await conn.execute(
        """
        INSERT INTO casino_player_cosmetics (user_id, notify_open_tables, updated_at)
        VALUES ($1, $2, now())
        ON CONFLICT (user_id) DO UPDATE
        SET notify_open_tables = EXCLUDED.notify_open_tables, updated_at = now()
        """,
        uid,
        bool(enabled),
    )


async def load_notify_open_tables(conn, user_id: int) -> bool:
    row = await conn.fetchrow(
        "SELECT notify_open_tables FROM casino_player_cosmetics WHERE user_id = $1",
        int(user_id),
    )
    return bool(row and row.get("notify_open_tables"))


async def upsert_nickname(conn, user_id: int, nickname: str) -> dict[str, object]:
    uid = int(user_id)
    if uid == 0:
        raise HTTPException(status_code=400, detail="Нет профиля")
    name = sanitize_nickname(nickname)
    row = await conn.fetchrow(
        """
        INSERT INTO casino_player_cosmetics (user_id, nickname, updated_at)
        VALUES ($1, $2, now())
        ON CONFLICT (user_id) DO UPDATE
        SET nickname = EXCLUDED.nickname, updated_at = now()
        RETURNING user_id, nickname, avatar_ext
        """,
        uid,
        name,
    )
    return dict(row)


async def save_avatar_bytes(conn, user_id: int, data: bytes) -> dict[str, object]:
    uid = int(user_id)
    if uid == 0:
        raise HTTPException(status_code=400, detail="Нет профиля")
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(data) > AVATAR_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Файл больше 512 КБ")
    ext = detect_avatar_ext(data)
    BOT_USER_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    stem = cosmetics_avatar_stem(uid)
    dest = BOT_USER_AVATAR_DIR / f"{stem}{ext}"
    tmp = BOT_USER_AVATAR_DIR / f".{stem}.tmp"
    tmp.write_bytes(data)
    tmp.replace(dest)
    for old in BOT_USER_AVATAR_DIR.glob(f"{stem}.*"):
        if old != dest and old.suffix.lower() in _ALLOWED_EXT:
            old.unlink(missing_ok=True)
    row = await conn.fetchrow(
        """
        INSERT INTO casino_player_cosmetics (user_id, avatar_ext, updated_at)
        VALUES ($1, $2, now())
        ON CONFLICT (user_id) DO UPDATE
        SET avatar_ext = EXCLUDED.avatar_ext, updated_at = now()
        RETURNING user_id, nickname, avatar_ext
        """,
        uid,
        ext.lstrip("."),
    )
    return dict(row)
