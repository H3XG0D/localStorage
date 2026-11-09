#!/usr/bin/env python3
"""Sandbox-only FocusPay VPN billing ASGI app.

Mounts the real exchange-backend `routers.internal_vpn` (purchase/trial saga) from
FOCUSPAY_ROOT against DATABASE_DSN (must be focuspay_sandbox), plus the reconcile loop.
Does NOT start production webhook callbacks / Payfast / Telegram notify.
"""

from __future__ import annotations

import os
import sys

dsn = os.environ.get("DATABASE_DSN", "")
if "focuspay_sandbox" not in dsn and ":15433/" not in dsn:
    print("REFUSE: DATABASE_DSN must be focuspay_sandbox / :15433", file=sys.stderr)
    sys.exit(2)
if "exchange_bot" in dsn and "focuspay_sandbox" not in dsn:
    print("REFUSE: refusing production exchange_bot DSN", file=sys.stderr)
    sys.exit(2)

fp_root = os.environ.get("FOCUSPAY_ROOT", "/home/qwe/Desktop/focuspay/site/exchange-backend")
sys.path.insert(0, fp_root)
os.environ.setdefault("INTERNAL_API_SECRET", os.environ.get("VPN_INTERNAL_TOKEN", ""))
os.environ.setdefault("FOCUSVPN_INTERNAL_TOKEN", os.environ.get("VPN_INTERNAL_TOKEN", ""))

import asyncio  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from db import init_db  # noqa: E402
from routers.internal_vpn import router as vpn_router  # noqa: E402
from vpn_billing import reconcile_loop  # noqa: E402

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(vpn_router, prefix="/api/internal/vpn")


@app.on_event("startup")
async def _startup():
    await init_db(dsn)
    asyncio.get_running_loop().create_task(reconcile_loop())
    print("SANDBOX FocusPay VPN billing DB connected")


@app.get("/health")
async def health():
    return {"ok": True, "service": "focuspay-vpn-wallet-sandbox"}


if __name__ == "__main__":
    import uvicorn

    host, _, port = os.environ.get("FOCUSPAY_WALLET_ADDR", "127.0.0.1:18081").partition(":")
    uvicorn.run(app, host=host or "127.0.0.1", port=int(port or "18081"))
