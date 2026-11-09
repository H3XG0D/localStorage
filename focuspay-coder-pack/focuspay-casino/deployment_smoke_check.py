"""Read-only preflight for FocusPay Casino Internal API.

The probe deliberately sends invalid payloads to POST-only lifecycle endpoints.
A 422 response proves the authenticated route is mounted without creating a hold,
claiming recovery work, or moving money.
"""
from __future__ import annotations

import asyncio

import httpx

from config import FOCUSPAY_API_URL, FOCUSPAY_INTERNAL_TOKEN


async def require_status(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    expected_status: int,
) -> None:
    response = await client.request(method, path, json={})
    if response.status_code != expected_status:
        raise RuntimeError(
            f"{method} {path} returned {response.status_code}; expected {expected_status}"
        )


async def main() -> None:
    if not FOCUSPAY_INTERNAL_TOKEN:
        raise RuntimeError("FOCUSPAY_INTERNAL_TOKEN must be configured")

    base_url = FOCUSPAY_API_URL.rstrip("/")
    headers = {"X-Internal-Token": FOCUSPAY_INTERNAL_TOKEN}
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=15.0) as client:
        settings = await client.get("/api/internal/casino/settings")
        settings.raise_for_status()
        if not isinstance(settings.json(), dict):
            raise RuntimeError("Casino settings response must be an object")

        snapshot = await client.get("/api/internal/casino/recovery/snapshot")
        snapshot.raise_for_status()
        if not isinstance(snapshot.json(), dict):
            raise RuntimeError("Recovery snapshot response must be an object")

        for path in (
            "/api/internal/casino/games/create-or-resume",
            "/api/internal/casino/recovery/claim",
            "/api/internal/casino/outbox/claim",
        ):
            await require_status(client, "POST", path, expected_status=422)

    print("Casino Internal API preflight passed")


if __name__ == "__main__":
    asyncio.run(main())
