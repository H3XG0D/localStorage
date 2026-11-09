"""Привязка Telegram оператора (opsbind_ / /ops_bind) — тот же контракт, что backend ops_ai_memory."""

from __future__ import annotations

import logging
import re

from services.db import get_pool
from services.order_ops_notify import operator_url

logger = logging.getLogger(__name__)

OPS_BIND_PREFIX = "opsbind_"
OPS_BIND_PAYLOAD_KEY = "_opsbind_start_payload"
_TOKEN_RE = re.compile(r"^[A-Z0-9]{8,32}$")


def extract_ops_bind_token(payload: str | None, *, allow_bare: bool = False) -> str | None:
    """Достаёт код из opsbind_XXX, /ops_bind XXX, /start opsbind_XXX.

    Голый токен (без префикса) — только из /ops_bind или allow_bare=True,
    чтобы /start ref_… не считался привязкой оператора.
    """
    raw = (payload or "").strip()
    if not raw:
        return None
    text = raw
    lower = text.lower()
    if lower.startswith("/start"):
        parts = text.split(None, 1)
        text = parts[1] if len(parts) > 1 else ""
        lower = text.lower()
        allow_bare = False
    explicit_cmd = False
    if lower.startswith("/ops_bind"):
        parts = text.split(None, 1)
        text = parts[1] if len(parts) > 1 else ""
        lower = text.lower()
        explicit_cmd = True
    text = text.strip().strip("/")
    if text.lower().startswith(("ref_", "uref_", "promo_")):
        return None
    has_prefix = text.lower().startswith(OPS_BIND_PREFIX)
    if not has_prefix and not explicit_cmd and not allow_bare:
        return None
    if has_prefix:
        text = text[len(OPS_BIND_PREFIX) :]
    code = text.strip().upper().replace("-", "").replace("_", "")
    if not _TOKEN_RE.fullmatch(code):
        return None
    return code


def ops_profile_url() -> str:
    return operator_url("/ops/profile")


async def bind_operator_telegram_by_token(token: str, telegram_user_id: int) -> dict | None:
    code = extract_ops_bind_token(token, allow_bare=True)
    if not code:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, username, display_name, telegram_user_id, telegram_bind_expires_at
            FROM operator_accounts
            WHERE telegram_bind_token = $1
              AND is_active = TRUE
              AND (telegram_bind_expires_at IS NULL OR telegram_bind_expires_at > NOW())
            """,
            code,
        )
        if not row:
            return None
        if row["telegram_user_id"] and int(row["telegram_user_id"]) != int(telegram_user_id):
            return None
        await conn.execute(
            """
            UPDATE operator_accounts
            SET telegram_user_id = NULL
            WHERE telegram_user_id = $1 AND id <> $2
            """,
            telegram_user_id,
            row["id"],
        )
        updated = await conn.fetchrow(
            """
            UPDATE operator_accounts SET
                telegram_user_id = $1,
                telegram_bind_token = NULL,
                telegram_bind_expires_at = NULL
            WHERE id = $2
            RETURNING id, username, display_name, telegram_user_id,
                      ops_ai_digest_enabled, ops_ai_digest_hour
            """,
            telegram_user_id,
            row["id"],
        )
    if not updated:
        return None
    return {
        "id": updated["id"],
        "username": updated["username"],
        "display_name": updated["display_name"],
        "telegram_user_id": updated["telegram_user_id"],
        "digest_enabled": bool(updated["ops_ai_digest_enabled"]),
        "digest_hour": int(updated["ops_ai_digest_hour"] or 10),
    }
