"""Cloudflare Turnstile: серверная проверка токена."""
from __future__ import annotations

import logging

import aiohttp

from config import settings

logger = logging.getLogger("turnstile")

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile(token: str | None, remote_ip: str | None = None) -> bool:
    """Проверить токен Cloudflare Turnstile.

    Возвращает True если:
    - turnstile_enabled=False (проверка отключена — dev/staging режим)
    - токен валиден по ответу Cloudflare

    При ошибке сети / некорректном ответе — fail-closed: возвращает False
    (только если turnstile_enabled=True).
    """
    if not settings.turnstile_enabled:
        return True

    if not token:
        logger.warning("turnstile: token is empty")
        return False

    secret = settings.turnstile_secret_key
    if not secret:
        logger.warning("turnstile: TURNSTILE_SECRET_KEY not configured — skipping check")
        return True

    payload: dict = {"secret": secret, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.post(TURNSTILE_VERIFY_URL, data=payload) as resp:
                data = await resp.json(content_type=None)
    except Exception as e:
        logger.warning("turnstile verify request failed: %s", e)
        return False

    success = bool(data.get("success"))
    if not success:
        logger.info("turnstile verify failed: %s", data.get("error-codes"))
    return success
