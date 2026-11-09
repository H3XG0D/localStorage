"""События купона автора в FocusPayPartnersBot. Ошибки не ломают обмен."""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger("partner_author_track")


def _config() -> tuple[str, str]:
    base = (os.getenv("PARTNER_URL") or "").strip().rstrip("/")
    secret = (os.getenv("TRACK_SECRET") or "").strip()
    return base, secret


def is_configured() -> bool:
    base, secret = _config()
    return bool(base and secret)


async def _post(event: str, client_id: int, extra: dict) -> None:
    base, secret = _config()
    if not base or not secret:
        return
    try:
        import aiohttp

        payload = {"event": event, "client_id": int(client_id), **extra}
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{base}/api/track",
                json=payload,
                headers={"X-Track-Secret": secret},
            ) as response:
                if response.status != 200:
                    logger.warning("partner track rejected event=%s status=%s", event, response.status)
    except Exception as exc:
        logger.warning("partner track failed event=%s: %r", event, exc)


def schedule_author_promo_event(event: str, client_id: int, **data) -> None:
    if not is_configured():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("partner event skipped — no loop event=%s", event)
        return
    loop.create_task(_post(event, client_id, dict(data)))
