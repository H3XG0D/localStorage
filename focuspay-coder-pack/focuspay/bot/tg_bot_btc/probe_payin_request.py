#!/usr/bin/env python3
"""Пробный POST /create_order_payin — для диагностики с Payfast (показать запрос/ответ)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import hashlib
import hmac

import aiohttp


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def _callback_url(raw: str) -> str:
    cb = (raw or "").strip()
    if "{WEBHOOK_SECRET}" in cb:
        cb = cb.replace("{WEBHOOK_SECRET}", os.environ.get("WEBHOOK_SECRET", ""))
    if "?token=" in cb:
        cb = cb.split("?")[0].rstrip("/")
    return cb


async def probe(*, amount: int, sub_token: str, fingerprint: int, redact: bool = True) -> None:
    base = os.environ["MERCHANT_BASE_URL"].rstrip("/")
    api_key = os.environ["MERCHANT_API_KEY"]
    secret = os.environ["MERCHANT_SECRET_KEY"]
    order_id = str(uuid.uuid4().int)[:8]
    payload = {
        "token": "P2P",
        "sub_token": sub_token.upper(),
        "fingerprint": str(fingerprint),
        "client_transaction_id": order_id,
        "amount": int(amount),
        "callback_url": _callback_url(os.environ.get("MERCHANT_CALLBACK_URL", "")),
    }
    body_str = json.dumps(payload, separators=(",", ":"))
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), (ts + body_str).encode(), hashlib.sha256).hexdigest()

    print("POST", f"{base}/create_order_payin")
    print("Headers:")
    print("  X-API-Key:", api_key if not redact else api_key[:6] + "***")
    print("  X-Timestamp:", ts)
    print("  X-Signature:", sig if not redact else sig[:12] + "***")
    print("  Content-Type: application/json")
    print("Body:", json.dumps(payload, ensure_ascii=False, indent=2))

    headers = {
        "X-API-Key": api_key,
        "X-Timestamp": ts,
        "X-Signature": sig,
        "Content-Type": "application/json",
    }
    t0 = time.time()
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{base}/create_order_payin",
            data=body_str,
            headers=headers,
            timeout=25,
        ) as resp:
            text = await resp.text()
            print(f"\nHTTP {resp.status} ({time.time() - t0:.2f}s)")
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                print(text[:4000])
                return
            print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> None:
    _load_env()
    p = argparse.ArgumentParser(description="Probe Payfast create_order_payin")
    p.add_argument("--amount", type=int, default=5555)
    p.add_argument("--sub", default="CARDRUB", choices=["CARDRUB", "SBPRUB"])
    p.add_argument("--fingerprint", type=int, default=999999999)
    p.add_argument(
        "--full",
        action="store_true",
        help="Print full X-API-Key and X-Signature (for Payfast support)",
    )
    args = p.parse_args()
    asyncio.run(
        probe(
            amount=args.amount,
            sub_token=args.sub,
            fingerprint=args.fingerprint,
            redact=not args.full,
        )
    )


if __name__ == "__main__":
    main()
