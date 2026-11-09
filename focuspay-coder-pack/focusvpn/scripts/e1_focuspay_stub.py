#!/usr/bin/env python3
"""In-memory FocusPay VPN billing stub for the E1 full smoke (no Postgres).

Mirrors the contract of FocusPay `routers/internal_vpn.py` + `vpn_billing.py`:
hold balance -> CP grant (idempotent by purchase id) -> spend; release on a 4xx.
"""

from __future__ import annotations

import math
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

TOKEN = os.environ.get("VPN_INTERNAL_TOKEN", "e1-smoke-fp")
CP = os.environ.get("FOCUSVPN_API_BASE", "http://127.0.0.1:18093").rstrip("/")
CP_TOKEN = os.environ.get("FOCUSVPN_INTERNAL_TOKEN", TOKEN)
MIN_EXCHANGES = int(os.environ.get("VPN_MIN_EXCHANGES", "10"))

SETTINGS = {
    "plans": [
        {"code": "week", "title": "Неделя", "days": 7, "price_rub": "300.00"},
        {"code": "month", "title": "Месяц", "days": 30, "price_rub": "990.00"},
        {"code": "q3", "title": "3 месяца", "days": 90, "price_rub": "2490.00"},
    ],
    "device_addons": [
        {"code": "week", "title": "Неделя", "days": 7, "price_rub": "300.00"},
        {"code": "month", "title": "Месяц", "days": 30, "price_rub": "990.00"},
        {"code": "q3", "title": "3 месяца", "days": 90, "price_rub": "2490.00"},
    ],
    "trial": {"enabled": True, "days": 1, "min_exchanges": 0},
    "purchase_min_exchanges": MIN_EXCHANGES,
    "app_url": "",
}

BALANCES: dict[int, float] = {}
EXCHANGES: dict[int, int] = {}
NOTIFIED: set[tuple[int, str, str]] = set()
PURCHASES: dict[str, dict] = {}  # idem_key -> purchase
LOCK = threading.Lock()

app = FastAPI()


def _auth(tok: str | None) -> None:
    if tok != TOKEN:
        raise HTTPException(403, "Forbidden")


def _cards(items: list[dict]) -> list[dict]:
    if not items:
        return []
    rates = [float(p["price_rub"]) / p["days"] for p in items]
    top = max(rates)
    return [
        {**p, "price_rub": float(p["price_rub"]), "per_day_rub": round(rate, 2), "discount_pct": round((top - rate) / top * 100)}
        for p, rate in zip(items, rates)
    ]


def _plans() -> list[dict]:
    return _cards(SETTINGS["plans"])


def _cp(method: str, path: str, **kw) -> httpx.Response:
    return httpx.request(method, f"{CP}{path}", headers={"X-Internal-Token": CP_TOKEN}, timeout=10, **kw)


def _cp_status(tg: int) -> dict:
    r = _cp("GET", "/v1/internal/billing/status", params={"telegram_id": tg})
    return r.json() if r.status_code == 200 else {}


def _subscription(tg: int) -> dict:
    cp = _cp_status(tg)
    if not cp.get("has_live") or not cp.get("ends_at"):
        return {"active": False, "plan": None, "status": None, "ends_at": None, "days_left": 0}
    ends = datetime.fromisoformat(cp["ends_at"].replace("Z", "+00:00"))
    secs = (ends - datetime.now(timezone.utc)).total_seconds()
    return {"active": secs > 0, "plan": cp.get("plan_code"), "status": cp.get("status"),
            "ends_at": ends.isoformat(), "days_left": max(0, math.ceil(secs / 86400))}


def _trial_used(tg: int) -> bool:
    return any(p["telegram_id"] == tg and p["kind"] == "trial" and p["status"] in ("held", "paid") for p in PURCHASES.values())


class PurchaseIn(BaseModel):
    telegram_id: int
    plan_code: str
    idem_key: str


class TrialIn(BaseModel):
    telegram_id: int
    idem_key: str


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/internal/vpn/plans")
def plans(x_internal_token: str | None = Header(default=None)):
    _auth(x_internal_token)
    return {"plans": _plans(), "trial": SETTINGS["trial"],
            "purchase_min_exchanges": SETTINGS["purchase_min_exchanges"], "app_url": SETTINGS["app_url"]}


@app.get("/api/internal/vpn/status/{telegram_id}")
def status(telegram_id: int, x_internal_token: str | None = Header(default=None)):
    _auth(x_internal_token)
    have = EXCHANGES.get(telegram_id, MIN_EXCHANGES)
    trial = SETTINGS["trial"]
    used = _trial_used(telegram_id)
    need = SETTINGS["purchase_min_exchanges"]
    return {
        "telegram_id": telegram_id,
        "available_rub": BALANCES.get(telegram_id, 0.0),
        "exchanges": {"have": have, "need": need},
        "purchase_open": have >= need,
        "trial": {**trial, "used": used},
        "trial_available": trial["enabled"] and not used and have >= trial["min_exchanges"],
        "plans": _plans(),
        "device_addons": _cards(SETTINGS["device_addons"]),
        "app_url": SETTINGS["app_url"],
        "subscription": _subscription(telegram_id),
        "devices_limit": {
            "max_devices": int(cp.get("max_devices") or 0),
            "base_devices": int(cp.get("base_devices") or 0),
            "extra_slots": cp.get("extra_slots") or [],
        } if (cp := _cp_status(telegram_id)) else {"max_devices": 0, "base_devices": 0, "extra_slots": []},
    }


@app.get("/api/internal/vpn/expiring")
def expiring(x_internal_token: str | None = Header(default=None)):
    _auth(x_internal_token)
    now = datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    r = _cp("GET", "/v1/internal/billing/ending",
            params={"from": (now - timedelta(hours=24)).strftime(fmt), "to": (now + timedelta(hours=6)).strftime(fmt)})
    out = []
    for row in r.json().get("subscriptions") or []:
        ends = datetime.fromisoformat(row["ends_at"].replace("Z", "+00:00"))
        kind = "ended" if ends <= now else "soon"
        if (row["telegram_id"], kind, ends.isoformat()) not in NOTIFIED:
            out.append({**row, "kind": kind, "ends_at": ends.isoformat()})
    return {"reminders": out}


class NotifiedIn(BaseModel):
    telegram_id: int
    kind: str
    ends_at: str


@app.post("/api/internal/vpn/notified")
def notified(body: NotifiedIn, x_internal_token: str | None = Header(default=None)):
    _auth(x_internal_token)
    key = (body.telegram_id, body.kind, datetime.fromisoformat(body.ends_at).isoformat())
    with LOCK:
        recorded = key not in NOTIFIED
        NOTIFIED.add(key)
    return {"recorded": recorded}


def _drive(p: dict) -> dict:
    r = httpx.post(
        f"{CP}/v1/internal/billing/grant",
        headers={"X-Internal-Token": CP_TOKEN},
        json={"external_id": p["id"], "telegram_id": p["telegram_id"], "kind": p["kind"],
              "plan_code": p["plan_code"], "days": p["days"], "amount_rub": f"{p['price_rub']:.2f}"},
        timeout=10,
    )
    if r.status_code == 200:
        p["status"], p["ends_at"] = "paid", r.json().get("ends_at")
    elif 400 <= r.status_code < 500:
        if p["kind"] in ("paid", "device"):
            BALANCES[p["telegram_id"]] = round(BALANCES.get(p["telegram_id"], 0.0) + p["price_rub"], 2)
        p["status"], p["error"] = ("released" if p["kind"] in ("paid", "device") else "failed"), r.text[:200]
    return p


def _out(p: dict, replay: bool) -> dict:
    return {"purchase_id": p["id"], "status": "pending" if p["status"] == "held" else p["status"],
            "kind": p["kind"], "plan_code": p["plan_code"], "days": p["days"], "price_rub": p["price_rub"],
            "ends_at": p.get("ends_at"), "error": p.get("error"), "replay": replay}


@app.post("/api/internal/vpn/purchase")
def purchase(body: PurchaseIn, x_internal_token: str | None = Header(default=None)):
    _auth(x_internal_token)
    with LOCK:
        if body.idem_key in PURCHASES:
            return _out(PURCHASES[body.idem_key], True)
        plan = next((p for p in SETTINGS["plans"] if p["code"] == body.plan_code), None)
        if not plan:
            raise HTTPException(400, {"code": "unknown_plan", "message": "unknown plan"})
        have = EXCHANGES.get(body.telegram_id, MIN_EXCHANGES)
        need = SETTINGS["purchase_min_exchanges"]
        if have < need:
            raise HTTPException(403, {"code": "exchange_gate", "need": need, "have": have})
        price = float(plan["price_rub"])
        if BALANCES.get(body.telegram_id, 0.0) + 1e-9 < price:
            raise HTTPException(402, {"code": "insufficient_funds", "message": "insufficient balance"})
        BALANCES[body.telegram_id] = round(BALANCES[body.telegram_id] - price, 2)
        p = {"id": str(uuid.uuid4()), "telegram_id": body.telegram_id, "kind": "paid", "plan_code": plan["code"],
             "days": int(plan["days"]), "price_rub": price, "status": "held"}
        PURCHASES[body.idem_key] = p
        return _out(_drive(p), False)


@app.post("/api/internal/vpn/device")
def device(body: PurchaseIn, x_internal_token: str | None = Header(default=None)):
    _auth(x_internal_token)
    with LOCK:
        if body.idem_key in PURCHASES:
            return _out(PURCHASES[body.idem_key], True)
        if not _cp_status(body.telegram_id).get("has_live"):
            raise HTTPException(400, {"code": "subscription_required", "message": "live subscription required"})
        addon = next((p for p in SETTINGS["device_addons"] if p["code"] == body.plan_code), None)
        if not addon:
            raise HTTPException(400, {"code": "unknown_plan", "message": "unknown device addon"})
        have = EXCHANGES.get(body.telegram_id, MIN_EXCHANGES)
        need = SETTINGS["purchase_min_exchanges"]
        if have < need:
            raise HTTPException(403, {"code": "exchange_gate", "need": need, "have": have})
        price = float(addon["price_rub"])
        if BALANCES.get(body.telegram_id, 0.0) + 1e-9 < price:
            raise HTTPException(402, {"code": "insufficient_funds", "message": "insufficient balance"})
        BALANCES[body.telegram_id] = round(BALANCES[body.telegram_id] - price, 2)
        p = {"id": str(uuid.uuid4()), "telegram_id": body.telegram_id, "kind": "device", "plan_code": addon["code"],
             "days": int(addon["days"]), "price_rub": price, "status": "held"}
        PURCHASES[body.idem_key] = p
        return _out(_drive(p), False)


@app.post("/api/internal/vpn/trial")
def trial(body: TrialIn, x_internal_token: str | None = Header(default=None)):
    _auth(x_internal_token)
    with LOCK:
        if body.idem_key in PURCHASES:
            return _out(PURCHASES[body.idem_key], True)
        t = SETTINGS["trial"]
        if _trial_used(body.telegram_id):
            raise HTTPException(409, {"code": "trial_used", "message": "trial already used"})
        have = EXCHANGES.get(body.telegram_id, MIN_EXCHANGES)
        if have < t["min_exchanges"]:
            raise HTTPException(403, {"code": "exchange_gate", "need": t["min_exchanges"], "have": have})
        p = {"id": str(uuid.uuid4()), "telegram_id": body.telegram_id, "kind": "trial", "plan_code": "trial",
             "days": int(t["days"]), "price_rub": 0.0, "status": "held"}
        PURCHASES[body.idem_key] = p
        return _out(_drive(p), False)


@app.post("/__smoke/credit")
def smoke_credit(body: dict):
    """Test-only: credit balance / set completed exchanges for a telegram user."""
    tid = int(body["telegram_id"])
    BALANCES[tid] = round(BALANCES.get(tid, 0.0) + float(body.get("amount_rub", 0)), 2)
    if "exchanges" in body:
        EXCHANGES[tid] = int(body["exchanges"])
    return {"telegram_id": tid, "available_rub": BALANCES[tid]}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "18094")))
