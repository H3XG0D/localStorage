"""HTTP clients for FocusPay + FocusVPN internal APIs.

Money flows only through FocusPay (/api/internal/vpn/purchase|trial): FocusPay
holds the balance, grants days on FocusVPN and confirms the spend. The bot never
extends a subscription directly.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from bot import config


class APIError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body

    @property
    def detail(self) -> dict[str, Any]:
        """FastAPI error detail as a dict ({} if not structured)."""
        try:
            d = json.loads(self.body).get("detail")
        except (ValueError, AttributeError):
            return {}
        return d if isinstance(d, dict) else {"message": str(d)}


def _headers(token: str) -> dict[str, str]:
    return {"X-Internal-Token": token, "Content-Type": "application/json"}


async def _fp(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.request(
            method,
            f"{config.FOCUSPAY_API_BASE}/api/internal/vpn{path}",
            headers=_headers(config.FOCUSPAY_INTERNAL_TOKEN),
            json=body,
        )
    if r.status_code >= 400:
        raise APIError(r.status_code, r.text)
    return r.json()


async def _mv(method: str, path: str, body: dict[str, Any] | None = None, params: dict | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.request(
            method,
            f"{config.FOCUSVPN_API_BASE}{path}",
            headers=_headers(config.FOCUSVPN_INTERNAL_TOKEN),
            json=body,
            params=params,
        )
    if r.status_code >= 400:
        raise APIError(r.status_code, r.text)
    return r.json() if r.content else {}


async def fp_plans() -> dict[str, Any]:
    return await _fp("GET", "/plans")


async def fp_status(telegram_id: int) -> dict[str, Any]:
    """Balance, deposit gates, trial availability, plans and the CP subscription."""
    return await _fp("GET", f"/status/{int(telegram_id)}")


async def fp_purchase(telegram_id: int, plan_code: str, idem_key: str) -> dict[str, Any]:
    return await _fp("POST", "/purchase", {"telegram_id": telegram_id, "plan_code": plan_code, "idem_key": idem_key})


async def fp_device(telegram_id: int, plan_code: str, idem_key: str) -> dict[str, Any]:
    """Buy one extra device seat. Does not extend the subscription."""
    return await _fp("POST", "/device", {"telegram_id": telegram_id, "plan_code": plan_code, "idem_key": idem_key})


async def fp_trial(telegram_id: int, idem_key: str) -> dict[str, Any]:
    return await _fp("POST", "/trial", {"telegram_id": telegram_id, "idem_key": idem_key})


async def fp_expiring() -> list[dict[str, Any]]:
    """Reminders not yet sent: kind soon (ends within 6 h) or ended (within a day)."""
    return (await _fp("GET", "/expiring")).get("reminders") or []


async def fp_notified(telegram_id: int, kind: str, ends_at: str) -> bool:
    """Record a reminder; False if another sender already recorded it."""
    res = await _fp("POST", "/notified", {"telegram_id": telegram_id, "kind": kind, "ends_at": ends_at})
    return bool(res.get("recorded"))


async def fp_review_reminders() -> list[dict[str, Any]]:
    """Users who can leave a VPN review and have not been reminded in this 7-day window."""
    return (await _fp("GET", "/review-reminders")).get("reminders") or []


async def fp_review_notified(telegram_id: int, window_at: str) -> bool:
    res = await _fp("POST", "/review-notified", {"telegram_id": telegram_id, "window_at": window_at})
    return bool(res.get("recorded"))


async def fp_submit_review(
    telegram_id: int,
    text: str,
    author: str,
    photo: tuple[str, bytes, str] | None = None,
) -> dict[str, Any]:
    """Multipart: the FocusPay bot cannot see this chat, so the screenshot goes as bytes."""
    data = {"telegram_id": str(int(telegram_id)), "text": text, "author": author}
    files = {"photo": photo} if photo else None
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{config.FOCUSPAY_API_BASE}/api/internal/vpn/reviews",
            headers={"X-Internal-Token": config.FOCUSPAY_INTERNAL_TOKEN},
            data=data,
            files=files,
        )
    if r.status_code >= 400:
        raise APIError(r.status_code, r.text)
    return r.json()


async def mv_upsert(telegram_id: int) -> dict[str, Any]:
    return await _mv("POST", "/v1/internal/telegram/upsert", {"telegram_id": telegram_id})


async def mv_attach_login(start_token: str, telegram_id: int) -> dict[str, Any]:
    return await _mv(
        "POST", "/v1/internal/telegram/attach-login", {"start_token": start_token, "telegram_id": telegram_id}
    )


async def mv_login_code(telegram_id: int) -> dict[str, Any]:
    return await _mv("POST", "/v1/internal/telegram/login-code", {"telegram_id": telegram_id})


async def mv_sub_link(telegram_id: int, rotate: bool = False) -> dict[str, Any]:
    """Stable Happ subscription URL. rotate replaces it and kills the previous one."""
    return await _mv("POST", "/v1/internal/telegram/sub-link", {"telegram_id": int(telegram_id), "rotate": rotate})


async def mv_status(telegram_id: int) -> dict[str, Any]:
    return await _mv("GET", "/v1/internal/billing/status", params={"telegram_id": telegram_id})


async def mv_devices(telegram_id: int) -> list[dict[str, Any]]:
    res = await _mv("GET", "/v1/internal/telegram/devices", params={"telegram_id": telegram_id})
    return res.get("devices") or []


async def mv_revoke_device(telegram_id: int, device_id: str) -> None:
    """Unbind a device: its VPN stops and the slot is free for another phone."""
    await _mv("POST", "/v1/internal/telegram/devices/revoke", {"telegram_id": telegram_id, "device_id": device_id})
