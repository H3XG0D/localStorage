"""Клиент API мерчанта (payin) — адаптер над merchants/ (failover 1→2→3).

Legacy-прямые функции сохранены для совместимости (бот, старые вызовы).
Новые точки вызова должны использовать merchants.client.create_payin_routed.
"""
import hashlib
import hmac
import json
import time

import aiohttp

from config import settings
from merchants.client import (  # noqa: F401 — публичный API адаптера
    attempts_from_response,
    cancel_payin_routed,
    create_payin_routed,
    merchant_id_from_response,
    payin_set_check_routed,
)


def _merchant_config():
    base = (settings.merchant_base_url or "").rstrip("/")
    api_key = settings.merchant_api_key or ""
    secret = settings.merchant_secret_key or ""
    if not base or not api_key or not secret:
        raise ValueError("Merchant API not configured")
    return base, api_key, secret


def _sign_body(body_str: str, secret: str) -> tuple[str, str]:
    timestamp = str(int(time.time()))
    message = timestamp + body_str
    signature = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return timestamp, signature


def _headers(timestamp: str, signature: str, api_key: str) -> dict:
    return {
        "X-API-Key": api_key,
        "X-Timestamp": timestamp,
        "X-Signature": signature,
        "Content-Type": "application/json",
    }


async def create_payin_order(
    *,
    order_id: str,
    user_id: int,
    fiat_amount: int,
    sub_token: str | None = None,
) -> dict:
    """Совместимость: идёт через роутер merchants (failover по приоритету)."""
    return await create_payin_routed(
        order_id=order_id, user_id=user_id, fiat_amount=fiat_amount, sub_token=sub_token,
    )


async def cancel_payin(uuid_value: str, *, merchant_id: str | None = None) -> dict:
    uuid_value = (uuid_value or "").strip()
    if not uuid_value:
        return {"status": 0, "body": {"error": "empty uuid"}}
    return await cancel_payin_routed(uuid_value, merchant_id=merchant_id)


async def payin_set_check(uuid_merchant: str, file_url: str, *, merchant_id: str | None = None) -> dict:
    return await payin_set_check_routed(uuid_merchant, file_url, merchant_id=merchant_id)
