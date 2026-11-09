"""Вебхук Telegram для бота внештатников. Всегда 200, чтобы Telegram не ретраил."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from exchanger_bot_config import fetch_config_row
from exchanger_bot_handlers import handle_telegram_update

router = APIRouter()
logger = logging.getLogger("exchanger_bot_webhook")


@router.post("/exchanger/{path_secret}")
async def exchanger_bot_webhook(
    path_secret: str,
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    try:
        cfg = await fetch_config_row()
        expected = (cfg or {}).get("webhook_secret") or ""
        if not expected or path_secret != expected:
            return JSONResponse({"ok": True})
        if (x_telegram_bot_api_secret_token or "") != expected:
            return JSONResponse({"ok": True})
        payload = await request.json()
        if isinstance(payload, dict):
            await handle_telegram_update(payload)
    except Exception:
        logger.exception("exchanger bot webhook failed")
    return JSONResponse({"ok": True})
