"""Best-effort callback магазину при зачислении / отмене внештатной сделки."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import aiohttp

logger = logging.getLogger("exchanger_deal_callback")

# Attempt delays before each try (seconds). Same event_id across retries.
_CALLBACK_RETRY_DELAYS = (0.0, 0.5, 2.0)
_DELIVERY_LOG_KEY = "exchanger:callback:deliveries"
_DELIVERY_LOG_MAX = 200


def _iso(value) -> str | None:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


def callback_event_id(deal_id: int, event: str) -> str:
    """Stable id for shop-side dedupe across delivery retries of the same event."""
    safe_event = "".join(ch for ch in str(event or "") if ch.isalnum() or ch in "-_")[:32]
    return f"ext-{int(deal_id)}-{safe_event or 'event'}"


def callback_payload(deal: dict[str, Any], event: str) -> dict[str, Any]:
    deal_id = int(deal.get("id") or 0)
    return {
        "event": event,
        "event_id": callback_event_id(deal_id, event),
        "deal_id": deal_id,
        "id": deal_id,
        "client_transaction_id": deal.get("client_transaction_id") or None,
        "status": str(deal.get("status") or ""),
        "amount_rub": float(deal.get("amount_rub") or 0),
        "client_pays_rub": float(deal.get("client_pays_rub") or 0),
        "principal_usdt": float(deal.get("principal_usdt") or 0),
        "expires_at": _iso(deal.get("expires_at")),
    }


def serialize_callback_payload(payload: dict[str, Any]) -> bytes:
    """Сериализовать ровно те байты, которые будут отправлены и подписаны."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sign_callback_body(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()


def verify_callback_signature(
    secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
) -> bool:
    """Сравнить подпись constant-time; helper также фиксирует sender-контракт."""
    if not secret or not timestamp or not signature:
        return False
    expected = sign_callback_body(secret, timestamp, body)
    return hmac.compare_digest(expected, signature)


async def _resolve_callback_secret(deal: dict[str, Any]) -> str:
    """Взять активный HMAC-секрет магазина, не добавляя его в callback payload."""
    explicit = str(deal.get("callback_secret") or "").strip()
    if explicit:
        return explicit

    try:
        exchanger_id = int(deal.get("exchanger_id") or 0)
    except (TypeError, ValueError):
        return ""
    if exchanger_id <= 0:
        return ""

    try:
        from db import get_pool
        from exchanger_api_keys import get_active_key_row

        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await get_active_key_row(conn, exchanger_id)
    except Exception:
        logger.warning(
            "exchanger callback signing key lookup failed deal=%s event=%s",
            deal.get("id"),
            deal.get("status"),
            exc_info=True,
        )
        return ""

    return str(row.get("secret") or "").strip() if row else ""


def _record_delivery(entry: dict[str, Any]) -> None:
    """Best-effort ring buffer in Redis for ops debugging (no secrets)."""
    try:
        from rate_limit_store import _get_redis

        r = _get_redis()
        if r is None:
            return
        r.lpush(_DELIVERY_LOG_KEY, json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
        r.ltrim(_DELIVERY_LOG_KEY, 0, _DELIVERY_LOG_MAX - 1)
    except Exception:
        logger.debug("callback delivery log skipped", exc_info=True)


async def fire_exchanger_deal_callback(deal: dict[str, Any], event: str) -> None:
    url = str(deal.get("callback_url") or "").strip()
    if not url or not url.lower().startswith(("http://", "https://")):
        return

    payload = callback_payload(deal, event)
    body = serialize_callback_payload(payload)
    secret = await _resolve_callback_secret(deal)
    deal_id = payload.get("deal_id")
    event_id = payload.get("event_id")

    last_status: int | None = None
    last_error: str | None = None
    for attempt, delay in enumerate(_CALLBACK_RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        headers = {"Content-Type": "application/json"}
        if secret:
            timestamp = str(int(time.time()))
            headers.update(
                {
                    "X-Timestamp": timestamp,
                    "X-Signature": sign_callback_body(secret, timestamp, body),
                    "X-Event-Id": str(event_id),
                }
            )
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, data=body, headers=headers) as response:
                    last_status = int(response.status)
                    if response.status < 400:
                        _record_delivery(
                            {
                                "ok": True,
                                "deal_id": deal_id,
                                "event": event,
                                "event_id": event_id,
                                "attempt": attempt + 1,
                                "http": last_status,
                                "ts": int(time.time()),
                            }
                        )
                        return
                    logger.warning(
                        "exchanger callback http=%s deal=%s event=%s attempt=%s",
                        response.status,
                        deal_id,
                        event,
                        attempt + 1,
                    )
        except Exception as exc:
            last_error = type(exc).__name__
            logger.warning(
                "exchanger callback failed deal=%s event=%s attempt=%s",
                deal_id,
                event,
                attempt + 1,
                exc_info=True,
            )

    _record_delivery(
        {
            "ok": False,
            "deal_id": deal_id,
            "event": event,
            "event_id": event_id,
            "attempt": len(_CALLBACK_RETRY_DELAYS),
            "http": last_status,
            "error": last_error,
            "ts": int(time.time()),
        }
    )


def schedule_exchanger_deal_callback(deal: dict[str, Any], event: str) -> None:
    url = str(deal.get("callback_url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(fire_exchanger_deal_callback(deal, event))
