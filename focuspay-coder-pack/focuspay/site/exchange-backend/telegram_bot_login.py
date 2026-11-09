"""Casino login via casino-bot /start cauth_<token> (no oauth.telegram.org phone prompt)."""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import unquote, urlencode

CAUTH_PREFIX = "cauth_"
TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")
TTL_SECONDS = 600
DEFAULT_RETURN_PATH = "/casino"


def hash_login_token(raw: str) -> str:
    return hashlib.sha256((raw or "").encode()).hexdigest()


def new_login_token() -> str:
    return secrets.token_hex(16)


def extract_cauth_token(payload: str | None) -> str | None:
    """cauth_<hex>, /start cauth_<hex>. Not ref_/uref_/opsbind_."""
    raw = (payload or "").strip()
    if not raw:
        return None
    text = raw
    lower = text.lower()
    if lower.startswith("/start"):
        parts = text.split(None, 1)
        text = parts[1] if len(parts) > 1 else ""
        lower = text.lower()
    text = text.strip().strip("/")
    if not lower.startswith(CAUTH_PREFIX) and not text.lower().startswith(CAUTH_PREFIX):
        return None
    if text.lower().startswith(CAUTH_PREFIX):
        text = text[len(CAUTH_PREFIX) :]
    code = text.strip().lower()
    if not TOKEN_RE.fullmatch(code):
        return None
    return code


def sanitize_casino_return_path(raw: str | None) -> str:
    if not raw or not isinstance(raw, str):
        return DEFAULT_RETURN_PATH
    trimmed = raw.strip()
    if not trimmed.startswith("/") or trimmed.startswith("//") or "\\" in trimmed:
        return DEFAULT_RETURN_PATH
    if any(ch in trimmed for ch in " <>"):
        return DEFAULT_RETURN_PATH
    path_only = trimmed.split("?")[0].split("#")[0]
    try:
        decoded = unquote(path_only)
    except Exception:
        return DEFAULT_RETURN_PATH
    if (
        not decoded.startswith("/")
        or decoded.startswith("//")
        or "\\" in decoded
        or "://" in decoded
    ):
        return DEFAULT_RETURN_PATH
    blocked = ("/login", "/register", "/forgot")
    if any(decoded == p or decoded.startswith(p + "/") for p in blocked):
        return DEFAULT_RETURN_PATH
    if decoded != "/casino" and not decoded.startswith("/casino/"):
        return DEFAULT_RETURN_PATH
    return trimmed


async def _pool():
    from db import get_pool

    return await get_pool()


def bot_username() -> str:
    """Deep link goes to the casino bot (@focusludka_bot in prod), not the exchange bot."""
    from config import settings

    name = (settings.casino_bot_username or "").strip().lstrip("@")
    if name:
        return name
    return "focusludka_bot"


def public_site_url() -> str:
    from config import settings

    return (settings.public_site_url or "https://focuspay.org").rstrip("/")


def cauth_deep_link(start_token: str) -> str:
    return f"https://t.me/{bot_username()}?start={CAUTH_PREFIX}{start_token}"


def casino_complete_url(ticket: str, return_path: str) -> str:
    path = sanitize_casino_return_path(return_path)
    query = urlencode({"ticket": ticket, "next": path})
    return f"{public_site_url()}/login/telegram?{query}"


async def create_bot_login(return_path: str | None) -> dict[str, Any]:
    start_token = new_login_token()
    path = sanitize_casino_return_path(return_path)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS)
    pool = await _pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO web_telegram_bot_logins (
                start_token_hash, return_path, expires_at
            ) VALUES ($1, $2, $3)
            """,
            hash_login_token(start_token),
            path,
            expires_at,
        )
    return {
        "deep_link": cauth_deep_link(start_token),
        "wait_token": start_token,
        "expires_at": expires_at.isoformat(),
        "return_path": path,
    }


async def attach_telegram_to_start(
    start_token: str,
    telegram_user_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
) -> dict[str, Any] | None:
    code = extract_cauth_token(start_token) or (
        start_token.strip().lower() if TOKEN_RE.fullmatch(start_token.strip().lower()) else None
    )
    if not code:
        return None
    ticket = new_login_token()
    pool = await _pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE web_telegram_bot_logins
            SET telegram_user_id = $2,
                tg_username = $3,
                tg_first_name = $4,
                ticket_hash = $5,
                ticket_consumed_at = NULL
            WHERE start_token_hash = $1
              AND expires_at > now()
            RETURNING return_path, expires_at
            """,
            hash_login_token(code),
            int(telegram_user_id),
            username,
            first_name,
            hash_login_token(ticket),
        )
    if not row:
        return None
    path = sanitize_casino_return_path(row["return_path"])
    return {
        "ticket": ticket,
        "return_path": path,
        "url": casino_complete_url(ticket, path),
        "expires_at": row["expires_at"],
    }


async def create_direct_ticket(
    telegram_user_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
    return_path: str | None = None,
) -> dict[str, Any]:
    ticket = new_login_token()
    path = sanitize_casino_return_path(return_path)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS)
    pool = await _pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO web_telegram_bot_logins (
                ticket_hash, return_path, telegram_user_id,
                tg_username, tg_first_name, expires_at
            ) VALUES ($1, $2, $3, $4, $5, $6)
            """,
            hash_login_token(ticket),
            path,
            int(telegram_user_id),
            username,
            first_name,
            expires_at,
        )
    return {
        "ticket": ticket,
        "return_path": path,
        "url": casino_complete_url(ticket, path),
        "expires_at": expires_at,
    }


async def consume_wait(wait_token: str) -> tuple[str, dict[str, Any] | None]:
    """Returns (status, row). status: pending | expired | consumed | ready."""
    raw = (wait_token or "").strip().lower()
    if not TOKEN_RE.fullmatch(raw):
        return "expired", None
    token_hash = hash_login_token(raw)
    pool = await _pool()
    async with pool.acquire() as conn:
        ready = await conn.fetchrow(
            """
            UPDATE web_telegram_bot_logins
            SET wait_consumed_at = now()
            WHERE start_token_hash = $1
              AND telegram_user_id IS NOT NULL
              AND wait_consumed_at IS NULL
              AND expires_at > now()
            RETURNING *
            """,
            token_hash,
        )
        if ready:
            return "ready", dict(ready)
        row = await conn.fetchrow(
            "SELECT * FROM web_telegram_bot_logins WHERE start_token_hash = $1",
            token_hash,
        )
    if not row:
        return "expired", None
    now = datetime.now(timezone.utc)
    expires = row["expires_at"]
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires is None or expires <= now:
        return "expired", None
    if row["wait_consumed_at"]:
        return "consumed", dict(row)
    return "pending", dict(row)


async def consume_ticket(ticket: str) -> dict[str, Any] | None:
    raw = (ticket or "").strip().lower()
    if not TOKEN_RE.fullmatch(raw):
        return None
    pool = await _pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE web_telegram_bot_logins
            SET ticket_consumed_at = now()
            WHERE ticket_hash = $1
              AND telegram_user_id IS NOT NULL
              AND ticket_consumed_at IS NULL
              AND expires_at > now()
            RETURNING *
            """,
            hash_login_token(raw),
        )
    return dict(row) if row else None
