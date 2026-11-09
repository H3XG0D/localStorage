"""Токен и вебхук общего бота внештатников (одна строка exchanger_bot_config)."""
from __future__ import annotations

import logging
import secrets
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException

from config import settings
from db import get_pool
from exchanger_bot_api import (
    TelegramApiError,
    delete_webhook,
    get_me,
    get_webhook_info,
    set_my_commands,
    set_webhook,
)
from exchanger_bot_commands import mask_bot_token

logger = logging.getLogger("exchanger_bot_config")

BOT_COMMANDS = [
    {"command": "start", "description": "Как пользоваться"},
    {"command": "reki", "description": "Свободные суммы"},
    {"command": "balance", "description": "Баланс магазина"},
    {"command": "who", "description": "Кто в магазине"},
    {"command": "add", "description": "Добавить telegram id (хозяин)"},
    {"command": "kick", "description": "Убрать telegram id (хозяин)"},
]


def expected_webhook_url(webhook_secret: str) -> str:
    base = (settings.public_site_url or "").rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="PUBLIC_SITE_URL не задан — вебхук поставить нельзя")
    return f"{base}/api/bot/exchanger/{webhook_secret}"


def public_config(row: dict | None, *, members_count: int = 0) -> dict[str, Any]:
    row = row or {}
    token = row.get("token")
    return {
        "configured": bool(token),
        "bot_id": row.get("bot_id"),
        "bot_username": row.get("bot_username"),
        "token_masked": mask_bot_token(token),
        "webhook_url": row.get("webhook_url"),
        "configured_at": row["configured_at"].isoformat() if row.get("configured_at") else None,
        "last_error": row.get("last_error"),
        "members_count": members_count,
    }


async def fetch_config_row(conn=None) -> dict | None:
    if conn is not None:
        row = await conn.fetchrow("SELECT * FROM exchanger_bot_config WHERE id = 1")
        return dict(row) if row else None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM exchanger_bot_config WHERE id = 1")
        return dict(row) if row else None


async def _write_error(message: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE exchanger_bot_config SET last_error = $1, updated_at = now() WHERE id = 1",
            message[:500],
        )


async def apply_webhook(token: str, webhook_secret: str) -> str:
    url = expected_webhook_url(webhook_secret)
    await set_webhook(token, url=url, secret=webhook_secret)
    await set_my_commands(token, BOT_COMMANDS)
    return url


async def configure_token(token: str, *, updated_by: int | None) -> dict[str, Any]:
    token = (token or "").strip()
    if not token or ":" not in token:
        raise HTTPException(status_code=400, detail="Не похоже на токен Telegram-бота")
    try:
        me = await get_me(token)
    except TelegramApiError as exc:
        await _write_error(str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pool = await get_pool()
    async with pool.acquire() as conn:
        current = await fetch_config_row(conn)
        webhook_secret = (current or {}).get("webhook_secret") or secrets.token_urlsafe(32)
        try:
            webhook_url = await apply_webhook(token, webhook_secret)
            last_error = None
        except TelegramApiError as exc:
            webhook_url = None
            last_error = str(exc)
            await conn.execute(
                """
                INSERT INTO exchanger_bot_config (id, token, bot_id, bot_username, webhook_secret,
                    webhook_url, last_error, updated_by, updated_at)
                VALUES (1, $1, $2, $3, $4, NULL, $5, $6, now())
                ON CONFLICT (id) DO UPDATE SET
                    token = EXCLUDED.token,
                    bot_id = EXCLUDED.bot_id,
                    bot_username = EXCLUDED.bot_username,
                    webhook_secret = EXCLUDED.webhook_secret,
                    last_error = EXCLUDED.last_error,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = now()
                """,
                token,
                me.get("id"),
                me.get("username"),
                webhook_secret,
                last_error[:500] if last_error else None,
                updated_by,
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        row = await conn.fetchrow(
            """
            INSERT INTO exchanger_bot_config (
                id, token, bot_id, bot_username, webhook_secret, webhook_url,
                configured_at, last_error, updated_by, updated_at
            ) VALUES (1, $1, $2, $3, $4, $5, now(), NULL, $6, now())
            ON CONFLICT (id) DO UPDATE SET
                token = EXCLUDED.token,
                bot_id = EXCLUDED.bot_id,
                bot_username = EXCLUDED.bot_username,
                webhook_secret = EXCLUDED.webhook_secret,
                webhook_url = EXCLUDED.webhook_url,
                configured_at = now(),
                last_error = NULL,
                updated_by = EXCLUDED.updated_by,
                updated_at = now()
            RETURNING *
            """,
            token,
            me.get("id"),
            me.get("username"),
            webhook_secret,
            webhook_url,
            updated_by,
        )
    return public_config(dict(row))


async def reconfigure() -> dict[str, Any]:
    row = await fetch_config_row()
    if not row or not row.get("token"):
        raise HTTPException(status_code=400, detail="Токен ещё не задан")
    secret = row.get("webhook_secret") or secrets.token_urlsafe(32)
    try:
        webhook_url = await apply_webhook(row["token"], secret)
    except TelegramApiError as exc:
        await _write_error(str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pool = await get_pool()
    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            """
            UPDATE exchanger_bot_config
            SET webhook_secret = $1, webhook_url = $2, configured_at = now(),
                last_error = NULL, updated_at = now()
            WHERE id = 1
            RETURNING *
            """,
            secret,
            webhook_url,
        )
    return public_config(dict(updated))


async def clear_token() -> dict[str, Any]:
    row = await fetch_config_row()
    if row and row.get("token"):
        try:
            await delete_webhook(row["token"])
        except TelegramApiError as exc:
            logger.warning("deleteWebhook failed: %s", exc)
    pool = await get_pool()
    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            """
            UPDATE exchanger_bot_config
            SET token = NULL, bot_id = NULL, bot_username = NULL, webhook_url = NULL,
                configured_at = NULL, last_error = NULL, updated_at = now()
            WHERE id = 1
            RETURNING *
            """
        )
    return public_config(dict(updated) if updated else None)


async def ensure_webhook_on_startup() -> None:
    try:
        row = await fetch_config_row()
    except Exception:
        logger.exception("exchanger bot config table missing")
        return
    token = (row or {}).get("token")
    secret = (row or {}).get("webhook_secret")
    if not token or not secret:
        return
    try:
        expected = expected_webhook_url(secret)
        info = await get_webhook_info(token)
        if (info.get("url") or "") == expected:
            return
        await apply_webhook(token, secret)
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE exchanger_bot_config
                SET webhook_url = $1, last_error = NULL, updated_at = now()
                WHERE id = 1
                """,
                expected,
            )
        logger.info("exchanger bot webhook restored: %s", expected)
    except Exception as exc:
        logger.warning("exchanger bot webhook self-heal failed: %s", exc)
        try:
            await _write_error(str(exc))
        except Exception:
            logger.debug("exchanger bot webhook error persist failed", exc_info=True)
