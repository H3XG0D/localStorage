"""HTTP-клиент к focuspay-signer (HMAC как exchanger v1)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

from config import settings
from exchanger_hmac import sign_body

logger = logging.getLogger("signer_client")


def _base_url() -> str:
    return (settings.signer_base_url or "").strip().rstrip("/")


def _secret() -> str:
    return (settings.signer_secret_key or "").strip()


def _api_key() -> str:
    return (settings.signer_api_key or "focuspay-main").strip()


def signer_configured() -> bool:
    return bool(_base_url() and _secret())


async def signer_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 30.0,
) -> tuple[int, dict[str, Any]]:
    if not signer_configured():
        return 503, {"error": "signer_not_configured"}
    payload = json.dumps(body or {}, separators=(",", ":"), ensure_ascii=False)
    ts = str(int(time.time()))
    sig = sign_body(_secret(), ts, payload)
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": _api_key(),
        "X-Timestamp": ts,
        "X-Signature": sig,
    }
    url = f"{_base_url()}{path}"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.request(
                method, url, data=payload.encode("utf-8"), headers=headers
            ) as resp:
                raw = await resp.text()
                try:
                    data = json.loads(raw) if raw else {}
                except ValueError:
                    data = {"raw": raw[:500]}
                if not isinstance(data, dict):
                    data = {"raw": data}
                return resp.status, data
    except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
        logger.warning("signer request failed %s %s: %s", method, path, exc)
        return 503, {"error": "signer_unreachable", "detail": str(exc)[:200]}


async def fetch_signer_health() -> dict[str, Any]:
    code, data = await signer_request("GET", "/v1/health", None, timeout=10.0)
    return {"http_status": code, **data}


async def fetch_signer_balances() -> dict[str, Any]:
    code, data = await signer_request("GET", "/v1/balance", None, timeout=15.0)
    if code != 200:
        return {"ok": False, "http_status": code, "coins": {}}
    return {"ok": True, "http_status": code, **data}


async def fetch_signer_deposit_addresses() -> dict[str, Any]:
    code, data = await signer_request("GET", "/v1/deposit-address", None, timeout=15.0)
    if code != 200:
        return {"ok": False, "http_status": code, "addresses": {}}
    return {"ok": True, "http_status": code, **data}


async def mint_signer_receive_address(coin: str) -> dict[str, Any]:
    """Адрес казино. Не ротирует текущий адрес дома."""
    code, data = await signer_request(
        "POST",
        "/v1/receive-address",
        {"coin": coin.lower()},
        timeout=20.0,
    )
    if code != 200 or not data.get("address"):
        return {
            "ok": False,
            "reason": data.get("detail") or "signer_unavailable",
            "http_status": code,
        }
    return {"ok": True, "http_status": code, **data}


async def fetch_signer_receive_incoming(coin: str, addresses: list[str]) -> dict[str, Any]:
    """Подтверждённые входы на адреса казино, сгруппированные подписантом."""
    if not addresses:
        return {"ok": True, "coin": coin.lower(), "items": []}
    code, data = await signer_request(
        "POST",
        "/v1/receive-incoming",
        {"coin": coin.lower(), "addresses": addresses},
        timeout=40.0,
    )
    if code != 200:
        return {
            "ok": False,
            "reason": data.get("detail") or "signer_unavailable",
            "http_status": code,
            "items": [],
        }
    items = data.get("items") if isinstance(data.get("items"), list) else []
    return {"ok": True, "http_status": code, "coin": coin.lower(), "items": items}


async def rotate_signer_deposit_address(coin: str) -> dict[str, Any]:
    code, data = await signer_request(
        "POST",
        "/v1/deposit-address",
        {"coin": coin.lower()},
        timeout=20.0,
    )
    if code in (404, 405):
        return {"ok": False, "reason": "signer_outdated", "http_status": code}
    if code != 200 or not data.get("address"):
        return {
            "ok": False,
            "reason": data.get("detail") or "signer_unavailable",
            "http_status": code,
        }
    return {"ok": True, "http_status": code, **data}


async def fetch_signer_fee_estimate(coin: str) -> dict[str, Any]:
    code, data = await signer_request(
        "GET", f"/v1/fee-estimate?coin={coin.lower()}", None, timeout=15.0
    )
    if code != 200:
        return {"ok": False, "http_status": code}
    return {"ok": True, "http_status": code, **data}


async def fetch_signer_topups(coin: str = "btc") -> dict[str, Any]:
    code, data = await signer_request(
        "GET", f"/v1/topups?coin={coin.lower()}", None, timeout=40.0
    )
    if code != 200:
        return {"ok": False, "http_status": code, "items": []}
    return {"ok": True, "http_status": code, **data}


async def trust_signer_topup(coin: str, txid: str, note: str = "") -> dict[str, Any]:
    code, data = await signer_request(
        "POST",
        "/v1/topups/trust",
        {"coin": coin.lower(), "txid": txid, "note": note[:200]},
        timeout=40.0,
    )
    if code != 200:
        return {"ok": False, "reason": data.get("detail") or "signer_unavailable", "http_status": code}
    return data


async def fetch_signer_payout(request_id: str) -> tuple[int, dict[str, Any]]:
    return await signer_request("GET", f"/v1/payouts/{request_id}", None, timeout=15.0)


async def fetch_signer_tx(coin: str, txid: str) -> dict[str, Any]:
    code, data = await signer_request(
        "POST",
        "/v1/tx/status",
        {"coin": coin.lower(), "txid": txid},
        timeout=20.0,
    )
    if code != 200:
        return {"ok": False, "found": False, "http_status": code}
    return {"ok": True, "http_status": code, **data}


async def quote_signer_bumps(txid: str, targets_sat_vb: list[float]) -> dict[str, Any]:
    code, data = await signer_request(
        "POST",
        "/v1/tx/bump-quotes",
        {"coin": "btc", "txid": txid, "targets_sat_vb": targets_sat_vb[:3]},
        timeout=40.0,
    )
    if code != 200:
        return {"ok": False, "reason": "signer_unavailable", "definite": True, "quotes": [], "http_status": code}
    if "quotes" not in data:
        data = {**data, "quotes": []}
    return data


async def quote_signer_bump(txid: str) -> dict[str, Any]:
    code, data = await signer_request(
        "POST",
        "/v1/tx/bump-quote",
        {"coin": "btc", "txid": txid},
        timeout=25.0,
    )
    if code != 200:
        return {"ok": False, "reason": "signer_unavailable", "definite": True, "http_status": code}
    return data


async def submit_signer_bump(txid: str, fee_rate_btc_kvb: float) -> dict[str, Any]:
    code, data = await signer_request(
        "POST",
        "/v1/tx/bump",
        {"coin": "btc", "txid": txid, "fee_rate_btc_kvb": fee_rate_btc_kvb},
        timeout=70.0,
    )
    if code != 200:
        definite = code < 500
        return {
            "ok": False,
            "reason": "signer_unavailable" if not definite else "rpc_error",
            "definite": definite,
            "http_status": code,
        }
    return data


async def push_signer_policy(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Записать потолки админки на подписант. Без кошелька — тихий пропуск."""
    if not signer_configured():
        return {"ok": False, "reason": "signer_not_configured"}
    from auto_settings import signer_policy_payload

    body = payload or signer_policy_payload()
    cleaned = {k: float(v) for k, v in body.items() if float(v or 0) > 0}
    if not cleaned:
        return {"ok": False, "reason": "empty_policy"}
    code, data = await signer_request("POST", "/v1/policy", cleaned, timeout=15.0)
    if code != 200:
        logger.warning("signer policy push failed http=%s data=%s", code, data)
        return {"ok": False, "http_status": code, **(data if isinstance(data, dict) else {})}
    return {"ok": True, "http_status": code, **data}


async def submit_signer_payout(body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Returns (status, response) with status in accepted|duplicate|rejected|unknown."""
    coin = str(body.get("coin") or "").lower()
    if coin in ("btc", "ltc"):
        from auto_settings import signer_coin_caps

        caps = signer_coin_caps(coin)
        if caps:
            body = {**body, **caps}
    code, data = await signer_request("POST", "/v1/payouts", body)
    st = str(data.get("status") or "").lower()
    if st in ("accepted", "duplicate", "rejected"):
        return st, data
    if code == 400:
        return "rejected", data
    # 5xx / timeout / unparsable: the send may or may not have happened. Never
    # retry blindly — the caller must reconcile by request_id.
    return "unknown", data
