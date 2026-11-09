"""Casino login via /start cauth_<token> and /casino — same table as exchange-backend."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from services.db import get_pool

logger = logging.getLogger(__name__)

CAUTH_PREFIX = "cauth_"
CAUTH_PAYLOAD_KEY = "_cauth_start_payload"
TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")
TTL_SECONDS = 600
DEFAULT_RETURN_PATH = "/casino"


def hash_login_token(raw: str) -> str:
    return hashlib.sha256((raw or "").encode()).hexdigest()


def new_login_token() -> str:
    return secrets.token_hex(16)


def extract_cauth_token(payload: str | None) -> str | None:
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
    if not text.lower().startswith(CAUTH_PREFIX):
        return None
    code = text[len(CAUTH_PREFIX) :].strip().lower()
    if not TOKEN_RE.fullmatch(code):
        return None
    return code


def sanitize_casino_return_path(raw: str | None) -> str:
    if not raw or not isinstance(raw, str):
        return DEFAULT_RETURN_PATH
    trimmed = raw.strip()
    if not trimmed.startswith("/") or trimmed.startswith("//") or "\\" in trimmed:
        return DEFAULT_RETURN_PATH
    path_only = trimmed.split("?")[0].split("#")[0]
    if path_only != "/casino" and not path_only.startswith("/casino/"):
        return DEFAULT_RETURN_PATH
    return trimmed


def public_site_url() -> str:
    from services.config_rates import PUBLIC_SITE_URL

    site = (PUBLIC_SITE_URL or os.getenv("PUBLIC_SITE_URL") or "https://focuspay.org").rstrip("/")
    if "gateway" in site or site.startswith("http://backend"):
        site = "https://focuspay.org"
    return site


def casino_complete_url(ticket: str, return_path: str) -> str:
    path = sanitize_casino_return_path(return_path)
    query = urlencode({"ticket": ticket, "next": path})
    return f"{public_site_url()}/login/telegram?{query}"


async def attach_telegram_to_start(
    start_token: str,
    telegram_user_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
) -> dict | None:
    code = extract_cauth_token(start_token) or (
        start_token.strip().lower() if TOKEN_RE.fullmatch((start_token or "").strip().lower()) else None
    )
    if not code:
        return None
    ticket = new_login_token()
    pool = await get_pool()
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
) -> dict:
    ticket = new_login_token()
    path = sanitize_casino_return_path(return_path)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS)
    pool = await get_pool()
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
