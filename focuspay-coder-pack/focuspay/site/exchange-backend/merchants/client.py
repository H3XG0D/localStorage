"""Unified merchant payin client with strict priority failover (1→2→3)."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import aiohttp

from .registry import Merchant, enabled_merchants, load_merchants

logger = logging.getLogger("merchants.client")


def _callback_url(m: Merchant) -> str:
    try:
        from config import settings
        secret = settings.webhook_secret or ""
    except Exception:
        secret = ""
    return (m.callback_url or "").replace("{WEBHOOK_SECRET}", secret)


def _sign(body_str: str, secret: str) -> tuple[str, str]:
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), (ts + body_str).encode(), hashlib.sha256).hexdigest()
    return ts, sig


async def _post_to_merchant(
    session: aiohttp.ClientSession,
    m: Merchant,
    path: str,
    payload: dict,
) -> tuple[int, dict]:
    body_str = json.dumps(payload, separators=(",", ":"))
    ts, sig = _sign(body_str, m.secret or "")
    headers = {
        "X-API-Key": m.api_key or "",
        "X-Timestamp": ts,
        "X-Signature": sig,
        "Content-Type": "application/json",
    }
    try:
        async with session.post(
            f"{m.base_url}{path}",
            data=body_str,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=m.timeout_sec),
        ) as resp:
            try:
                body = await resp.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                body = {"_raw": body}
            return resp.status, body
    except (asyncio.TimeoutError, aiohttp.ClientError) as e:
        return 0, {"status_pending": "error", "error": f"{type(e).__name__}: {e}"}


def _has_bill(body: dict) -> bool:
    try:
        from payin_resolver import get_bill_from_response
        return get_bill_from_response(body) is not None
    except Exception:
        data_order = (body or {}).get("data_order") or {}
        bill = (body or {}).get("bill") or data_order.get("bill")
        if not isinstance(bill, dict):
            return False
        return bool(str(bill.get("reciver") or bill.get("receiver") or "").strip())


async def create_payin_routed(
    *,
    order_id: str,
    user_id: int,
    fiat_amount: int,
    sub_token: str | None = None,
    merchants: list[Merchant] | None = None,
) -> dict[str, Any]:
    """Try merchants by priority until one returns a bill. Never raises on HTTP."""
    chain = enabled_merchants(merchants if merchants is not None else load_merchants())
    attempts: list[dict[str, Any]] = []
    last_resp: dict[str, Any] = {"status_pending": "error", "error": "no merchants configured"}
    async with aiohttp.ClientSession() as session:
        for n, m in enumerate(chain, 1):
            sub = (sub_token or m.default_sub_token or "SBPRUB").upper()
            if m.sub_tokens and sub not in m.sub_tokens:
                attempts.append({"merchant_id": m.id, "skipped": f"sub_token {sub} not supported"})
                continue
            t0 = time.monotonic()
            payload = {
                "token": "P2P",
                "sub_token": sub,
                "fingerprint": str(user_id),
                "client_transaction_id": str(order_id),
                "amount": int(fiat_amount),
                "callback_url": _callback_url(m),
            }
            status, body = await _post_to_merchant(session, m, "/create_order_payin", payload)
            latency_ms = int((time.monotonic() - t0) * 1000)
            ok = status == 200 and body.get("status_pending") != "error" and _has_bill(body)
            attempts.append({
                "merchant_id": m.id, "http_status": status,
                "latency_ms": latency_ms, "ok": ok,
                "error": None if ok else str(body.get("error") or ("no bill" if status == 200 else f"HTTP {status}")),
            })
            logger.info("payin attempt %s/%s merchant=%s sub=%s status=%s ok=%s latency_ms=%s",
                        n, len(chain), m.id, sub, status, ok, latency_ms)
            if ok:
                out = dict(body)
                out["_merchant_id"] = m.id
                out["_merchant_attempts"] = attempts
                return out
            last_resp = dict(body)
            last_resp.setdefault("status_pending", "error")
    last_resp["_merchant_attempts"] = attempts
    if chain:
        last_resp["_merchant_id"] = None
    logger.warning("payin all merchants failed attempts=%s",
                   json.dumps(attempts, ensure_ascii=False)[:1000])
    return last_resp


async def create_payin_order(
    *,
    order_id: str,
    user_id: int,
    fiat_amount: int,
    sub_token: str | None = None,
) -> dict[str, Any]:
    """Drop-in replacement for merchant_client.create_payin_order."""
    return await create_payin_routed(
        order_id=order_id, user_id=user_id, fiat_amount=fiat_amount, sub_token=sub_token,
    )


def merchant_id_from_response(resp: dict | None) -> str | None:
    mid = (resp or {}).get("_merchant_id")
    return str(mid) if mid else None


def attempts_from_response(resp: dict | None) -> list[dict]:
    att = (resp or {}).get("_merchant_attempts")
    return list(att) if isinstance(att, list) else []


async def _route_by_merchant(
    path: str, payload: dict, *, merchant_id: str | None = None,
) -> dict[str, Any]:
    chain = enabled_merchants()
    if merchant_id:
        chain = [m for m in chain if m.id == merchant_id] + [m for m in chain if m.id != merchant_id]
    async with aiohttp.ClientSession() as session:
        last: dict[str, Any] = {"status": 0, "body": {"error": "no merchants"}}
        for m in chain:
            status, body = await _post_to_merchant(session, m, path, payload)
            last = {"status": status, "body": body, "_merchant_id": m.id}
            if status == 200:
                return last
        return last


async def cancel_payin_routed(uuid_value: str, *, merchant_id: str | None = None) -> dict:
    return await _route_by_merchant("/cancel_order_payin", {"uuid": uuid_value}, merchant_id=merchant_id)


async def payin_set_check_routed(uuid_value: str, file_url: str, *, merchant_id: str | None = None) -> dict:
    return await _route_by_merchant("/payin_set_check", {"uuid": uuid_value, "file": file_url}, merchant_id=merchant_id)
