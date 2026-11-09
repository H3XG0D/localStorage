"""Ключи HMAC API магазина (одна активная пара на внештатника)."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime
from typing import Any

logger = logging.getLogger("exchanger_api_keys")

# Кабинет внештатника может смотреть публичный api_key, но не выпускать и не отзывать.
ADMIN_ONLY_API_KEY_DETAIL = "Ключ API выдаёт и отзывает только администратор площадки"

_SCHEMA_SQL = (
    """
    ALTER TABLE external_deals
        ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ
    """,
    """
    ALTER TABLE external_deals
        ADD COLUMN IF NOT EXISTS client_transaction_id TEXT
    """,
    """
    ALTER TABLE external_deals
        ADD COLUMN IF NOT EXISTS callback_url TEXT
    """,
    """
    ALTER TABLE external_deals
        ADD COLUMN IF NOT EXISTS customer_fingerprint TEXT
    """,
    """
    ALTER TABLE external_deals
        ADD COLUMN IF NOT EXISTS client_stat JSONB
    """,
    """
    ALTER TABLE external_deals
        ADD COLUMN IF NOT EXISTS client_stat_at TIMESTAMPTZ
    """,
    """
    CREATE TABLE IF NOT EXISTS external_client_stats (
        exchanger_id INTEGER NOT NULL REFERENCES external_exchangers(id) ON DELETE CASCADE,
        fingerprint  TEXT NOT NULL,
        payload      JSONB NOT NULL,
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (exchanger_id, fingerprint)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS external_deals_exchanger_client_tx_uidx
        ON external_deals (exchanger_id, client_transaction_id)
        WHERE client_transaction_id IS NOT NULL AND client_transaction_id <> ''
    """,
    """
    CREATE TABLE IF NOT EXISTS external_exchanger_api_keys (
        id           SERIAL PRIMARY KEY,
        exchanger_id INTEGER NOT NULL REFERENCES external_exchangers(id),
        api_key      VARCHAR(64) NOT NULL UNIQUE,
        secret       TEXT NOT NULL,
        secret_hash  VARCHAR(128) NOT NULL,
        secret_hint  VARCHAR(16) NOT NULL,
        is_active    BOOLEAN NOT NULL DEFAULT TRUE,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        revoked_at   TIMESTAMPTZ
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS external_exchanger_api_keys_one_active
        ON external_exchanger_api_keys (exchanger_id)
        WHERE is_active = TRUE
    """,
)

_schema_ready = False


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def secret_hint(secret: str) -> str:
    raw = (secret or "").strip()
    if len(raw) < 4:
        return "…"
    return raw[:4] + "…"


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def key_public_dict(row) -> dict[str, Any]:
    d = dict(row)
    return {
        "id": int(d["id"]),
        "api_key": d["api_key"],
        "secret_hint": d.get("secret_hint") or "",
        "is_active": bool(d.get("is_active")),
        "created_at": _iso(d.get("created_at")),
        "revoked_at": _iso(d.get("revoked_at")),
    }


async def ensure_exchanger_hmac_schema(conn) -> None:
    global _schema_ready
    if _schema_ready:
        return
    for sql in _SCHEMA_SQL:
        await conn.execute(sql)
    _schema_ready = True


async def get_active_key_row(conn, exchanger_id: int):
    return await conn.fetchrow(
        """
        SELECT * FROM external_exchanger_api_keys
        WHERE exchanger_id = $1 AND is_active = TRUE
        ORDER BY id DESC
        LIMIT 1
        """,
        exchanger_id,
    )


async def get_key_by_api_key(conn, api_key: str):
    key = (api_key or "").strip()
    if not key:
        return None
    return await conn.fetchrow(
        """
        SELECT k.*, e.is_active AS exchanger_is_active
        FROM external_exchanger_api_keys k
        JOIN external_exchangers e ON e.id = k.exchanger_id
        WHERE k.api_key = $1
        """,
        key,
    )


async def list_key_for_exchanger(conn, exchanger_id: int) -> dict[str, Any] | None:
    await ensure_exchanger_hmac_schema(conn)
    row = await get_active_key_row(conn, exchanger_id)
    return key_public_dict(row) if row else None


async def issue_key_for_exchanger(conn, exchanger_id: int) -> dict[str, Any]:
    """Выпуск / ротация: старый ключ отзывается, секрет показывается один раз."""
    await ensure_exchanger_hmac_schema(conn)
    api_key = secrets.token_hex(16)
    secret = secrets.token_hex(24)
    async with conn.transaction():
        await conn.execute(
            """
            UPDATE external_exchanger_api_keys
            SET is_active = FALSE, revoked_at = now()
            WHERE exchanger_id = $1 AND is_active = TRUE
            """,
            exchanger_id,
        )
        row = await conn.fetchrow(
            """
            INSERT INTO external_exchanger_api_keys (
                exchanger_id, api_key, secret, secret_hash, secret_hint, is_active
            ) VALUES ($1, $2, $3, $4, $5, TRUE)
            RETURNING *
            """,
            exchanger_id,
            api_key,
            secret,
            hash_secret(secret),
            secret_hint(secret),
        )
    out = key_public_dict(row)
    out["secret"] = secret
    return out


async def revoke_key_for_exchanger(conn, exchanger_id: int) -> dict[str, Any]:
    await ensure_exchanger_hmac_schema(conn)
    result = await conn.execute(
        """
        UPDATE external_exchanger_api_keys
        SET is_active = FALSE, revoked_at = now()
        WHERE exchanger_id = $1 AND is_active = TRUE
        """,
        exchanger_id,
    )
    revoked = str(result).endswith("1") or "UPDATE 1" in str(result)
    return {"ok": True, "revoked": revoked}
