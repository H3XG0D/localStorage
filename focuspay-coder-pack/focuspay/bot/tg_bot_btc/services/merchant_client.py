"""Подписанные запросы к Payfast Merchant API."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

import aiohttp

from services import config_rates

logger = logging.getLogger("merchant_client")

MERCHANT_HTTP_TIMEOUT = 20.0
MERCHANT_POLL_TIMEOUT = 10.0


def _merchant_config() -> tuple[str, str, str]:
    merchant = config_rates.MERCHANT or {}
    base = (merchant.get("base_url") or "").rstrip("/")
    api_key = (merchant.get("api_key") or "").strip()
    secret = (merchant.get("secret_key") or "").strip()
    if not base or not api_key or not secret:
        raise ValueError("Merchant API not configured")
    return base, api_key, secret


def _sign_body(body_str: str, secret: str) -> tuple[str, str]:
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode("utf-8"),
        (timestamp + body_str).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return timestamp, signature


async def merchant_post(path: str, payload: dict, *, timeout: float = MERCHANT_HTTP_TIMEOUT) -> dict:
    base, api_key, secret = _merchant_config()
    body_str = json.dumps(payload, separators=(",", ":"))
    timestamp, signature = _sign_body(body_str, secret)
    headers = {
        "X-API-Key": api_key,
        "X-Timestamp": timestamp,
        "X-Signature": signature,
        "Content-Type": "application/json",
    }
    url = f"{base}{path}"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url, data=body_str, headers=headers, timeout=timeout
        ) as response:
            try:
                body = await response.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                body = {"raw": body}
            if response.status >= 400:
                body["status_pending"] = "error"
                body.setdefault("error", body.get("error") or f"HTTP {response.status}")
            body["_http_status"] = int(response.status)
            return body


async def get_merchant_order(uuid_system: str, *, timeout: float = MERCHANT_POLL_TIMEOUT) -> dict:
    return await merchant_post("/get_order", {"uuid": str(uuid_system).strip()}, timeout=timeout)


async def cancel_order_payin(uuid_value: str, *, timeout: float = MERCHANT_HTTP_TIMEOUT) -> dict:
    """
    POST /cancel_order_payin.
    Returns {"status": <http_int>, "body": <dict>, "ok": bool}.
    """
    uuid_value = (uuid_value or "").strip()
    if not uuid_value:
        return {"status": 0, "body": {"error": "uuid_value пустой"}, "ok": False}
    try:
        body = await merchant_post(
            "/cancel_order_payin",
            {"uuid": uuid_value},
            timeout=timeout,
        )
    except Exception as e:
        logger.warning("cancel_order_payin failed uuid=%s: %s", uuid_value, e)
        return {"status": 0, "body": {"error": str(e)}, "ok": False}
    http = int(body.pop("_http_status", 0) or 0)
    ok = http == 200 and body.get("status_pending") != "error"
    return {"status": http, "body": body, "ok": ok}
