"""Подписанные запросы к Payfast Merchant API."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import aiohttp

from config import settings


def _merchant_config() -> tuple[str, str, str]:
    base = (settings.merchant_base_url or "").rstrip("/")
    api_key = (settings.merchant_api_key or "").strip()
    secret = (settings.merchant_secret_key or "").strip()
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


async def merchant_post(path: str, payload: dict, *, timeout: float = 25) -> dict:
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
            if response.status >= 400:
                body["status_pending"] = "error"
                body.setdefault("error", body.get("error") or f"HTTP {response.status}")
            return body


async def get_merchant_order(uuid_system: str) -> dict:
    return await merchant_post("/get_order", {"uuid": str(uuid_system).strip()})
