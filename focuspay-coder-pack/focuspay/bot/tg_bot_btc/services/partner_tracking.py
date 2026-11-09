"""События для партнёрского бота (см. INTEGRATION.md партнёрки).

Fire-and-forget: партнёрка никогда не должна ломать обменник —
все ошибки гасятся, при пустых PARTNER_URL/TRACK_SECRET — no-op.
"""
import asyncio
import logging
import os

logger = logging.getLogger("partner_tracking")

_TIMEOUT_S = 10


def _config() -> tuple[str, str]:
    base = (os.getenv("PARTNER_URL") or "").strip().rstrip("/")
    secret = (os.getenv("TRACK_SECRET") or "").strip()
    return base, secret


def is_configured() -> bool:
    base, secret = _config()
    return bool(base and secret)


async def _post_track(event: str, client_id: int, extra: dict) -> None:
    base, secret = _config()
    if not base or not secret:
        return
    try:
        import aiohttp

        payload = {"event": event, "client_id": int(client_id), **extra}
        timeout = aiohttp.ClientTimeout(total=_TIMEOUT_S)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(
                f"{base}/api/track",
                json=payload,
                headers={"X-Track-Secret": secret},
            ) as r:
                if r.status != 200:
                    logger.warning("partner track rejected event=%s status=%s", event, r.status)
    except Exception as e:
        logger.warning("partner track failed event=%s: %r", event, e)


def schedule_partner_event(event: str, client_id: int, **data) -> None:
    """Поставить событие в фон. Безопасно звать откуда угодно (sync)."""
    if not is_configured():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("partner event skipped — no loop event=%s", event)
        return
    loop.create_task(_post_track(event, client_id, dict(data)))


def schedule_partner_exchange(order: dict) -> None:
    """Успешно завершённый обмен: user_id + сумма в рублях из заявки."""
    try:
        user_id = int(order.get("user_id") or 0)
    except (TypeError, ValueError):
        return
    if not user_id:
        return
    try:
        amount = float(order.get("fiat_amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    extra = {"amount_rub": amount}
    order_id = str(order.get("order_id") or "").strip()
    if order_id:
        extra["order_id"] = order_id
    schedule_partner_event("exchange", user_id, **extra)
