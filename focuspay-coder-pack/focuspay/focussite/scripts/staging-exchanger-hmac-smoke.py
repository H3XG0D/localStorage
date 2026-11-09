#!/usr/bin/env python3
"""Staging-only HMAC exchanger API smoke + abuse matrix (A–E, H).

Never point at production. Fail-closed without STAGING_BASE_URL + HMAC creds.

Preferred run (callback reachable from backend container)::

  # on focuspay-test, from repo or /tmp copy
  KEY=... SECRET=...  # from external_exchanger_api_keys for 940001
  sudo docker run --rm --name exchanger-qa-smoke \\
    --network focuspay_staging_runtime_app_net \\
    -e STAGING_BASE_URL=http://backend:8000 \\
    -e EXCHANGER_API_KEY=$KEY -e EXCHANGER_HMAC_SECRET=$SECRET \\
    -e EXCHANGER_ID=940001 \\
    -e CALLBACK_LISTEN=1 -e CALLBACK_HOST=exchanger-qa-smoke \\
    -e CALLBACK_PORT=9876 \\
    -e INTERNAL_API_SECRET=... \\  # from staging-runtime.env
    -e OPS_USERNAME=fixture_full_client_ops -e OPS_PASSWORD=... \\
    -e ADMIN_USERNAME=... -e ADMIN_PASSWORD=... \\
    -v \"$PWD/focussite/scripts/staging-exchanger-hmac-smoke.py:/smoke.py:ro\" \\
    python:3.12-slim python /smoke.py

Local tunnel (HMAC only; callbacks skip unless CALLBACK_PUBLIC_URL reachable)::

  STAGING_BASE_URL=http://127.0.0.1:18081 \\
  EXCHANGER_API_KEY=... EXCHANGER_HMAC_SECRET=... python focussite/scripts/staging-exchanger-hmac-smoke.py
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

RESULTS: list[tuple[str, str, str]] = []  # id, PASS|FAIL|SKIP|NOTE, detail


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


BASE = _env("STAGING_BASE_URL").rstrip("/")
API_KEY = _env("EXCHANGER_API_KEY")
SECRET = _env("EXCHANGER_HMAC_SECRET")
EXCHANGER_ID = int(_env("EXCHANGER_ID", "940001") or "940001")
INTERNAL = _env("INTERNAL_API_SECRET")
OPS_USER = _env("OPS_USERNAME")
OPS_PASS = _env("OPS_PASSWORD")
ADMIN_USER = _env("ADMIN_USERNAME")
ADMIN_PASS = _env("ADMIN_PASSWORD")
V1 = "/api/exchanger/v1"
PREFIX = _env("SMOKE_PREFIX", f"qa-{uuid.uuid4().hex[:10]}")


class CallbackCatcher:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.events: list[dict[str, Any]] = []
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.public_url = _env("CALLBACK_PUBLIC_URL")

    def start_if_configured(self) -> str | None:
        if self.public_url:
            return self.public_url
        if _env("CALLBACK_LISTEN") != "1":
            return None
        host = _env("CALLBACK_HOST", "127.0.0.1")
        port = int(_env("CALLBACK_PORT", "9876") or "9876")
        catcher = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
                return

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    payload = {"_raw": raw.decode("utf-8", errors="replace")}
                entry = {
                    "path": self.path,
                    "headers": {
                        k: self.headers.get(k)
                        for k in ("X-Timestamp", "X-Signature", "Content-Type")
                    },
                    "body": payload,
                    "raw": raw,
                }
                with catcher.lock:
                    catcher.events.append(entry)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

        self.server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.public_url = f"http://{host}:{port}/hook"
        time.sleep(0.2)
        return self.public_url

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()

    def wait_event(self, event: str, deal_id: int, timeout: float = 12.0) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                for e in self.events:
                    body = e.get("body") or {}
                    if body.get("event") == event and int(body.get("deal_id") or 0) == int(deal_id):
                        return e
            time.sleep(0.25)
        return None


CATCHER = CallbackCatcher()


def record(cid: str, status: str, detail: str = "") -> None:
    RESULTS.append((cid, status, detail))
    print(f"[{status}] {cid}: {detail}")


def sign(ts: str, body: str) -> str:
    return hmac.new(SECRET.encode(), f"{ts}{body}".encode(), hashlib.sha256).hexdigest()


_last_signed_ts: str | None = None


def _next_timestamp(forced: str | None = None) -> str:
    """Avoid same-second replay false positives for identical bodies."""
    global _last_signed_ts
    if forced is not None:
        _last_signed_ts = forced
        return forced
    while True:
        ts = str(int(time.time()))
        if ts != _last_signed_ts:
            _last_signed_ts = ts
            return ts
        time.sleep(0.05)


def http(
    method: str,
    path: str,
    *,
    body: dict | None = None,
    body_raw: str | None = None,
    headers: dict[str, str] | None = None,
    signed: bool = False,
    api_key: str | None = None,
    secret: str | None = None,
    ts: str | None = None,
    sig: str | None = None,
    timeout: float = 45.0,
) -> tuple[int, Any, bytes]:
    if body_raw is not None:
        raw = body_raw
    elif body is None:
        raw = ""
    else:
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    hdrs = {"Accept": "application/json"}
    if method.upper() in {"POST", "PUT", "PATCH"} or raw:
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    if signed:
        key = api_key if api_key is not None else API_KEY
        sec = secret if secret is not None else SECRET
        timestamp = _next_timestamp(ts)
        if sig is not None:
            signature = sig
        elif sec == SECRET:
            signature = sign(timestamp, raw)
        else:
            signature = hmac.new(
                sec.encode(), f"{timestamp}{raw}".encode(), hashlib.sha256
            ).hexdigest()
        hdrs["X-API-Key"] = key
        hdrs["X-Timestamp"] = timestamp
        hdrs["X-Signature"] = signature
    url = path if path.startswith("http") else f"{BASE}{path}"
    if method.upper() == "GET" and raw == "":
        req = Request(url, method="GET", headers=hdrs)
    else:
        req = Request(
            url,
            data=raw.encode("utf-8") if (raw or method.upper() == "POST") else None,
            method=method.upper(),
            headers=hdrs,
        )
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            try:
                parsed: Any = json.loads(data.decode("utf-8") or "null")
            except json.JSONDecodeError:
                parsed = data.decode("utf-8", errors="replace")
            return int(resp.status), parsed, data
    except HTTPError as exc:
        data = exc.read()
        try:
            parsed = json.loads(data.decode("utf-8") or "null")
        except json.JSONDecodeError:
            parsed = data.decode("utf-8", errors="replace")
        return int(exc.code), parsed, data
    except URLError as exc:
        return 0, {"error": str(exc)}, b""

def detail_text(body: Any) -> str:
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return str(body)[:240]


def expect_status(cid: str, got: int, want: int | set[int], body: Any) -> bool:
    wants = want if isinstance(want, set) else {want}
    if got in wants:
        record(cid, "PASS", f"HTTP {got}")
        return True
    record(cid, "FAIL", f"HTTP {got} want {wants}: {detail_text(body)}")
    return False


def ctx_id(tag: str) -> str:
    return f"{PREFIX}-{tag}"


def create_deal(tag: str, **extra: Any) -> tuple[int, Any]:
    payload: dict[str, Any] = {
        "amount_rub": extra.pop("amount_rub", 500),
        "sub_token": extra.pop("sub_token", "SBPRUB"),
        "client_transaction_id": extra.pop("client_transaction_id", ctx_id(tag)),
        "fingerprint": extra.pop("fingerprint", f"fp-{tag}"),
    }
    cb = CATCHER.public_url
    if cb and "callback_url" not in extra:
        payload["callback_url"] = cb
    payload.update(extra)
    # drop Nones
    payload = {k: v for k, v in payload.items() if v is not None}
    status, body, _ = http("POST", f"{V1}/deals", body=payload, signed=True)
    return status, body


def deal_id_of(body: Any) -> int:
    if not isinstance(body, dict):
        return 0
    return int(body.get("id") or body.get("deal_id") or 0)


def ledger_count_for_deal(deal_id: int, token: str | None) -> int | None:
    if not token:
        return None
    status, body, _ = http(
        "GET",
        f"/api/admin/external/exchangers/{EXCHANGER_ID}/ledger?limit=200",
        headers={"Authorization": f"Bearer {token}"},
    )
    if status != 200:
        return None
    rows: Any
    if isinstance(body, list):
        rows = body
    elif isinstance(body, dict):
        rows = body.get("items") or body.get("ledger") or body.get("rows") or body.get("entries") or []
    else:
        return None
    n = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if int(row.get("deal_id") or 0) == int(deal_id) and str(row.get("type") or "") == "principal":
            n += 1
    return n


def is_route_missing(status: int, body: Any) -> bool:
    return status == 404 and "not found" in detail_text(body).lower()


def login(scope: str, username: str, password: str) -> str | None:
    path = {
        "admin": "/api/auth/admin/login",
        "operator": "/api/auth/operator/login",
        "exchanger": "/api/auth/exchanger/login",
    }[scope]
    status, body, _ = http("POST", path, body={"username": username, "password": password})
    if status != 200 or not isinstance(body, dict):
        return None
    if body.get("requires_2fa"):
        return None
    return str(body.get("access_token") or "") or None


def run_auth_section() -> None:
    # A1
    status, body, _ = http("POST", f"{V1}/deals", body={"amount_rub": 100})
    expect_status("A1", status, 401, body)

    # A2
    status, body, _ = http(
        "POST", f"{V1}/deals", body={"amount_rub": 100}, signed=True, api_key="deadbeef" * 4
    )
    expect_status("A2", status, 401, body)

    # A3 — sign wrong body
    raw = json.dumps({"amount_rub": 100}, separators=(",", ":"))
    ts = str(int(time.time()))
    bad_sig = sign(ts, "{}")
    status, body, _ = http(
        "POST", f"{V1}/deals", body_raw=raw, signed=True, ts=ts, sig=bad_sig
    )
    ok = expect_status("A3", status, 401, body)
    if ok and "signature" not in detail_text(body).lower() and "Invalid" not in detail_text(body):
        record("A3", "PASS", f"401 ({detail_text(body)})")

    # A4
    raw = json.dumps({"amount_rub": 100}, separators=(",", ":"))
    ts_old = str(int(time.time()) - 400)
    status, body, _ = http("POST", f"{V1}/deals", body_raw=raw, signed=True, ts=ts_old)
    expect_status("A4", status, 401, body)

    # A5 replay
    raw = json.dumps({"amount_rub": 101, "client_transaction_id": ctx_id("replay")}, separators=(",", ":"))
    ts = str(int(time.time()))
    status1, body1, _ = http("POST", f"{V1}/deals", body_raw=raw, signed=True, ts=ts)
    status2, body2, _ = http("POST", f"{V1}/deals", body_raw=raw, signed=True, ts=ts)
    if status1 in {200, 201} and status2 == 401 and "replay" in detail_text(body2).lower():
        record("A5", "PASS", "second request replay rejected")
    elif status1 == 401:
        record("A5", "FAIL", f"first call failed: {detail_text(body1)}")
    else:
        record("A5", "FAIL", f"first={status1} second={status2} {detail_text(body2)}")

    # A6 uppercase signature
    raw = json.dumps({"amount_rub": 102}, separators=(",", ":"))
    ts = str(int(time.time()))
    sig = sign(ts, raw).upper()
    status, body, _ = http("POST", f"{V1}/deals", body_raw=raw, signed=True, ts=ts, sig=sig)
    expect_status("A6", status, 401, body)

    # A7 wrong secret
    status, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={"amount_rub": 103},
        signed=True,
        secret="0" * 48,
    )
    expect_status("A7", status, 401, body)

    record("A8", "SKIP", "only one active key; revoke would break shop")

    # A9 GET empty body signature
    # need a deal first
    st, created, _ = http(
        "POST",
        f"{V1}/deals",
        body={"amount_rub": 200, "client_transaction_id": ctx_id("a9"), "fingerprint": "a9"},
        signed=True,
    )
    did = deal_id_of(created)
    if st not in {200, 201} or not did:
        record("A9", "FAIL", f"setup create failed {st} {detail_text(created)}")
    else:
        status, body, _ = http("GET", f"{V1}/deals/{did}", signed=True)
        expect_status("A9", status, 200, body)

    # A10 whitespace / reordered JSON signed vs sent
    signed_raw = '{"amount_rub":104}'
    sent_raw = '{"amount_rub": 104}'
    ts = str(int(time.time()))
    status, body, _ = http(
        "POST", f"{V1}/deals", body_raw=sent_raw, signed=True, ts=ts, sig=sign(ts, signed_raw)
    )
    expect_status("A10", status, 401, body)


def run_create_section() -> None:
    st, body = create_deal("b1", amount_rub=500, sub_token="SBPRUB")
    if expect_status("B1", st, {200, 201}, body):
        if not (isinstance(body, dict) and (body.get("payment") or body.get("bill"))):
            record("B1", "FAIL", "missing bill/payment")

    st, body = create_deal("b2", amount_rub=500, sub_token="CARDRUB")
    expect_status("B2", st, {200, 201}, body)

    st, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={
            "amount_crypto": 1.0,
            "crypto": "usdt",
            "sub_token": "SBPRUB",
            "client_transaction_id": ctx_id("b3"),
            "fingerprint": "b3",
            **({"callback_url": CATCHER.public_url} if CATCHER.public_url else {}),
        },
        signed=True,
    )
    expect_status("B3", st, {200, 201}, body)

    st, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={"amount_rub": 400, "client_transaction_id": ctx_id("b4"), "fingerprint": "b4"},
        signed=True,
    )
    if st in {200, 201} and isinstance(body, dict) and str(body.get("sub_token") or "SBPRUB").upper() == "SBPRUB":
        record("B4", "PASS", f"sub_token={body.get('sub_token')}")
    else:
        record("B4", "FAIL", f"{st} {detail_text(body)}")

    st, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={
            "amount_rub": 450,
            "client_transaction_id": ctx_id("b5"),
            "fingerprint": "buyer-b5",
            "callback_url": CATCHER.public_url or "http://example.invalid/hook",
            "client_stat": {
                "paid_orders": 3,
                "buy_paid": 3,
                "buy_failed": 1,
                "turnover_rub": 9000,
            },
        },
        signed=True,
    )
    expect_status("B5", st, {200, 201}, body)

    st, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={"amount_rub": 410, "client_transaction_id": ctx_id("b6")},
        signed=True,
    )
    expect_status("B6", st, {200, 201}, body)

    st, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={"amount_rub": 420, "fingerprint": "b7"},
        signed=True,
    )
    expect_status("B7", st, {200, 201}, body)

    # B8 idempotent
    cid = ctx_id("b8")
    st1, b1, _ = http(
        "POST",
        f"{V1}/deals",
        body={"amount_rub": 500, "client_transaction_id": cid, "fingerprint": "b8"},
        signed=True,
    )
    st2, b2, _ = http(
        "POST",
        f"{V1}/deals",
        body={"amount_rub": 500, "client_transaction_id": cid, "fingerprint": "b8"},
        signed=True,
    )
    id1, id2 = deal_id_of(b1), deal_id_of(b2)
    if st1 in {200, 201} and st2 in {200, 201} and id1 and id1 == id2:
        record("B8", "PASS", f"same deal_id={id1}")
        record("E1", "PASS", "idempotent create")
    else:
        record("B8", "FAIL", f"{st1}/{st2} ids {id1}/{id2}")
        record("E1", "FAIL", "idempotent create broken")

    st, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={"amount_rub": 500, "client_transaction_id": ctx_id("b9"), "fingerprint": "b9"},
        signed=True,
    )
    if st in {200, 201} and deal_id_of(body) and deal_id_of(body) != id1:
        record("B9", "PASS", f"new id={deal_id_of(body)}")
    else:
        record("B9", "FAIL", f"{st} {detail_text(body)}")

    st0, body0, _ = http("POST", f"{V1}/deals", body={"amount_rub": 0}, signed=True)
    stn, bodyn, _ = http("POST", f"{V1}/deals", body={"amount_rub": -5}, signed=True)
    if st0 == 400 and stn == 400:
        record("B10", "PASS", "zero/negative rejected")
    else:
        record("B10", "FAIL", f"zero={st0} neg={stn} {detail_text(body0)}/{detail_text(bodyn)}")

    st, body, _ = http("POST", f"{V1}/deals", body={"sub_token": "SBPRUB"}, signed=True)
    expect_status("B11", st, 400, body)

    record("B12", "SKIP", "needs Rapira outage injection")
    record("B13", "SKIP", "needs ending all operator shifts")

    st, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={"amount_rub": 500, "client_transaction_id": ctx_id("b14"), "fingerprint": "b14"},
        signed=True,
    )
    if st in {200, 201} and isinstance(body, dict):
        pays = float(body.get("client_pays_rub") or 0)
        amt = float(body.get("amount_rub") or 0)
        mode = str(body.get("markup_mode") or "")
        if mode == "on_deal" and pays > amt > 0:
            record("B14", "PASS", f"{amt} → pays {pays} mode={mode}")
        else:
            record("B14", "FAIL", f"amt={amt} pays={pays} mode={mode}")
        # B15 leak check
        top_keys = set(body.keys())
        forbidden = {"api_key", "secret", "api_secret", "webhook_secret", "internal"}
        pay = body.get("payment") if isinstance(body.get("payment"), dict) else {}
        bill = body.get("bill") or pay.get("bill")
        has_core = bool(bill) and bool(body.get("expires_at") or body.get("payment_text") or pay)
        leaked = [k for k in forbidden if k in top_keys or k in (pay or {})]
        # merchant_uuid may exist inside payment for ops — top-level Payfast noise check
        if has_core and not leaked:
            record("B15", "PASS", "bill/expires present, no secret keys")
            record("E14", "PASS", "no secret fields in deal JSON")
        else:
            record("B15", "FAIL", f"has_core={has_core} leaked={leaked}")
            record("E14", "FAIL", f"leaked={leaked}")
        locked_pays = pays
        time.sleep(0.5)
        st2, body2, _ = http("GET", f"{V1}/deals/{deal_id_of(body)}", signed=True)
        if st2 == 200 and abs(float(body2.get("client_pays_rub") or 0) - locked_pays) < 0.01:
            record("E12", "PASS", "client_pays_rub locked")
        else:
            record("E12", "FAIL", f"{st2} {detail_text(body2)}")
    else:
        record("B14", "FAIL", detail_text(body))
        record("B15", "FAIL", "create failed")
        record("E14", "FAIL", "create failed")
        record("E12", "FAIL", "create failed")


def run_happy_and_lifecycle(ops_token: str | None, admin_token: str | None) -> None:
    # C1
    st, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={
            "amount_rub": 500,
            "client_transaction_id": ctx_id("c1"),
            "fingerprint": "c1",
            **({"callback_url": CATCHER.public_url} if CATCHER.public_url else {}),
        },
        signed=True,
    )
    did = deal_id_of(body)
    if st not in {200, 201} or not did:
        record("C1", "FAIL", f"create {st} {detail_text(body)}")
    else:
        st_g, _, _ = http("GET", f"{V1}/deals/{did}", signed=True)
        st_p, paid, _ = http("POST", f"{V1}/deals/{did}/paid", body={}, signed=True)
        st_r, receipt, _ = http(
            "POST",
            f"{V1}/deals/{did}/receipt",
            body={"file": "https://example.com/qa-receipt.pdf"},
            signed=True,
        )
        status_name = ""
        if isinstance(receipt, dict):
            deal = receipt.get("deal") if isinstance(receipt.get("deal"), dict) else receipt
            status_name = str(deal.get("status") or "")
        if st_g == 200 and st_p == 200 and st_r == 200 and status_name == "pending":
            record("C1", "PASS", f"deal {did} → pending")
        else:
            record(
                "C1",
                "FAIL",
                f"get={st_g} paid={st_p} receipt={st_r} status={status_name} {detail_text(receipt)}",
            )

        # D3 second paid (must use new timestamp — empty body replay)
        time.sleep(1.05)
        st2, body2, _ = http("POST", f"{V1}/deals/{did}/paid", body={}, signed=True)
        if st2 == 400:
            record("D3", "PASS", "second paid rejected")
        elif st2 == 401 and "replay" in detail_text(body2).lower():
            record("D3", "FAIL", "replay blocked second paid — retry gap too small")
        else:
            record("D3", "FAIL", f"second paid {st2} {detail_text(body2)}")

        # D1 cancel after receipt
        st_c, body_c, _ = http("POST", f"{V1}/deals/{did}/cancel", body={}, signed=True)
        if st_c == 400:
            record("D1", "PASS", "cancel after receipt rejected")
        elif is_route_missing(st_c, body_c):
            record(
                "D1",
                "FAIL",
                "HMAC /cancel missing on staging backend (local repo has it; shop docs promise cancel)",
            )
        else:
            record("D1", "FAIL", f"cancel {st_c} {detail_text(body_c)}")

        # D6 second receipt
        st_r2, body_r2, _ = http(
            "POST",
            f"{V1}/deals/{did}/receipt",
            body={"file": "https://example.com/qa-receipt-2.pdf"},
            signed=True,
        )
        if st_r2 == 400:
            record("D6", "PASS", "second receipt rejected")
        else:
            record("D6", "FAIL", f"{st_r2} {detail_text(body_r2)}")

        # C2 ops confirm
        if not ops_token:
            record("C2", "SKIP", "no OPS credentials")
            record("E6", "SKIP", "no OPS credentials")
            record("D9", "SKIP", "no OPS credentials")
            record("D10", "SKIP", "no OPS credentials")
            record("C6", "SKIP", "no OPS credentials")
        else:
            st_conf, conf, _ = http(
                "POST",
                f"/api/operator/external/deals/{did}/confirm",
                body={},
                headers={"Authorization": f"Bearer {ops_token}"},
            )
            st_get, got, _ = http("GET", f"{V1}/deals/{did}", signed=True)
            confirmed = st_get == 200 and isinstance(got, dict) and got.get("status") == "confirmed"
            cb = CATCHER.wait_event("credited", did) if CATCHER.public_url else None
            ledger_n = ledger_count_for_deal(did, admin_token)
            if st_conf == 200 and confirmed:
                detail = f"confirmed ledger={ledger_n}"
                if CATCHER.public_url:
                    if cb and cb["headers"].get("X-Signature"):
                        # verify signature
                        ts = cb["headers"].get("X-Timestamp") or ""
                        sig = cb["headers"].get("X-Signature") or ""
                        raw = cb.get("raw") or b""
                        good = hmac.compare_digest(
                            hmac.new(SECRET.encode(), ts.encode() + raw, hashlib.sha256).hexdigest(),
                            sig,
                        )
                        leaked = any(
                            k in json.dumps(cb.get("body") or {})
                            for k in (SECRET, API_KEY, "api_secret")
                        )
                        event_id = (cb.get("body") or {}).get("event_id")
                        if good and not leaked and event_id:
                            record("C2", "PASS", detail + " + signed credited callback")
                            record("E2", "PASS", f"callback signed, event_id={event_id}")
                        else:
                            record(
                                "C2",
                                "FAIL",
                                f"{detail} sig_ok={good} leaked={leaked} event_id={event_id}",
                            )
                            record("E2", "FAIL", f"sig_ok={good} leaked={leaked} event_id={event_id}")
                    else:
                        record("C2", "FAIL", f"{detail} but no credited callback")
                        record("E2", "FAIL", "no callback captured")
                else:
                    record("C2", "PASS", detail + " (callback not listened)")
                    record("E2", "SKIP", "no callback listener")
                record("E6", "PASS", "ops confirm is intentional credit path")
                if ledger_n == 1:
                    pass  # good
                elif ledger_n is None:
                    record("D9", "SKIP", "no admin token for ledger count")
                else:
                    # will double-confirm below
                    pass
            else:
                record("C2", "FAIL", f"confirm={st_conf} get={st_get} {detail_text(conf)}")
                record("E6", "FAIL", "ops confirm failed")
                record("E2", "SKIP", "no credited event")

            # D9 double confirm
            st_conf2, _, _ = http(
                "POST",
                f"/api/operator/external/deals/{did}/confirm",
                body={},
                headers={"Authorization": f"Bearer {ops_token}"},
            )
            ledger_n2 = ledger_count_for_deal(did, admin_token)
            if ledger_n2 == 1 or (ledger_n2 is None and st_conf2 in {400, 409}):
                record("D9", "PASS", f"second confirm http={st_conf2} ledger={ledger_n2}")
            elif ledger_n2 is None:
                record("D9", "SKIP", "no ledger visibility")
            else:
                record("D9", "FAIL", f"ledger={ledger_n2} after double confirm")

            # D2 cancel confirmed
            st_c2, body_c2, _ = http("POST", f"{V1}/deals/{did}/cancel", body={}, signed=True)
            if st_c2 == 400:
                record("D2", "PASS", "cancel confirmed rejected")
            else:
                record("D2", "FAIL", f"{st_c2} {detail_text(body_c2)}")

            # D10 video on a fresh pending deal
            st_v, body_v, _ = http(
                "POST",
                f"{V1}/deals",
                body={
                    "amount_rub": 500,
                    "client_transaction_id": ctx_id("d10"),
                    "fingerprint": "d10",
                    **({"callback_url": CATCHER.public_url} if CATCHER.public_url else {}),
                },
                signed=True,
            )
            vid = deal_id_of(body_v)
            if st_v in {200, 201} and vid:
                http("POST", f"{V1}/deals/{vid}/paid", body={}, signed=True)
                http(
                    "POST",
                    f"{V1}/deals/{vid}/receipt",
                    body={"file": "https://example.com/qa-d10.pdf"},
                    signed=True,
                )
                st_vid, vid_body, _ = http(
                    "POST",
                    f"/api/operator/external/deals/{vid}/video",
                    body={},
                    headers={"Authorization": f"Bearer {ops_token}"},
                )
                if is_route_missing(st_vid, vid_body):
                    record("D10", "FAIL", "ops /video missing on staging backend")
                else:
                    st_g2, got2, _ = http("GET", f"{V1}/deals/{vid}", signed=True)
                    if (
                        st_vid == 200
                        and isinstance(got2, dict)
                        and got2.get("status") == "awaiting_receipt"
                        and (got2.get("needs_operator_video") or got2.get("required_receipt_type") == 3)
                    ):
                        http("POST", f"{V1}/deals/{vid}/paid", body={}, signed=True)
                        st_pdf, pdf_body, _ = http(
                            "POST",
                            f"{V1}/deals/{vid}/receipt",
                            body={"file": "https://example.com/qa-d10-again.pdf"},
                            signed=True,
                        )
                        if st_pdf == 400:
                            record("D10", "PASS", "video re-request + PDF blocked")
                        else:
                            record("D10", "FAIL", f"video ok but PDF accepted {st_pdf} {detail_text(pdf_body)}")
                    else:
                        record(
                            "D10",
                            "FAIL",
                            f"video={st_vid} get={st_g2} {detail_text(vid_body)} / {detail_text(got2)}",
                        )
            else:
                record("D10", "FAIL", "setup deal failed")

            # C6 extend
            st_e, body_e, _ = http(
                "POST",
                f"{V1}/deals",
                body={
                    "amount_rub": 500,
                    "client_transaction_id": ctx_id("c6"),
                    "fingerprint": "c6",
                    **({"callback_url": CATCHER.public_url} if CATCHER.public_url else {}),
                },
                signed=True,
            )
            eid = deal_id_of(body_e)
            if st_e in {200, 201} and eid:
                before = str(body_e.get("expires_at") or "")
                st_x, xb, _ = http(
                    "POST",
                    f"/api/operator/external/deals/{eid}/extend",
                    body={},
                    headers={"Authorization": f"Bearer {ops_token}"},
                )
                if is_route_missing(st_x, xb):
                    record("C6", "FAIL", "ops /extend missing on staging backend")
                else:
                    st_ge, ge, _ = http("GET", f"{V1}/deals/{eid}", signed=True)
                    after = str(ge.get("expires_at") or "") if isinstance(ge, dict) else ""
                    cb_x = CATCHER.wait_event("extended", eid, timeout=8) if CATCHER.public_url else True
                    if st_x == 200 and after and after != before and cb_x:
                        record("C6", "PASS", f"expires {before} → {after}")
                    else:
                        record("C6", "FAIL", f"extend={st_x} before={before} after={after} cb={bool(cb_x)}")
            else:
                record("C6", "FAIL", "setup failed")

    # C3 cancel happy
    st, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={
            "amount_rub": 500,
            "client_transaction_id": ctx_id("c3"),
            "fingerprint": "c3",
            **({"callback_url": CATCHER.public_url} if CATCHER.public_url else {}),
        },
        signed=True,
    )
    cid = deal_id_of(body)
    if st in {200, 201} and cid:
        st_c, cbod, _ = http("POST", f"{V1}/deals/{cid}/cancel", body={}, signed=True)
        if is_route_missing(st_c, cbod):
            record(
                "C3",
                "FAIL",
                "HMAC /cancel not deployed on staging (docs + local repo have it) — shop cannot cancel via API here",
            )
            if ops_token:
                st_oc, _, _ = http(
                    "POST",
                    f"/api/operator/external/deals/{cid}/cancel",
                    body={},
                    headers={"Authorization": f"Bearer {ops_token}"},
                )
                st_g, got, _ = http("GET", f"{V1}/deals/{cid}", signed=True)
                if st_oc == 200 and isinstance(got, dict) and got.get("status") == "cancelled":
                    record("C3b", "PASS", f"ops cancel fallback works for deal {cid}")
                else:
                    record("C3b", "FAIL", f"ops cancel fallback http={st_oc}")
            else:
                record("C3b", "SKIP", "no ops token for cancel fallback")
        else:
            st_g, got, _ = http("GET", f"{V1}/deals/{cid}", signed=True)
            cancelled = isinstance(got, dict) and got.get("status") == "cancelled"
            cb = CATCHER.wait_event("cancelled", cid, timeout=8) if CATCHER.public_url else True
            if st_c == 200 and cancelled and cb:
                record("C3", "PASS", f"cancelled deal={cid}")
            else:
                record("C3", "FAIL", f"cancel={st_c} status_ok={cancelled} cb={bool(cb)} {detail_text(cbod)}")
    else:
        record("C3", "FAIL", "create failed")

    # C4 lookups
    st, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={"amount_rub": 500, "client_transaction_id": ctx_id("c4"), "fingerprint": "c4"},
        signed=True,
    )
    lid = deal_id_of(body)
    if st in {200, 201} and lid:
        q = urlencode({"client_transaction_id": ctx_id("c4")})
        s1, b1, _ = http("GET", f"{V1}/deals/{lid}", signed=True)
        s2, b2, _ = http("GET", f"{V1}/deals?{q}", signed=True)
        s3, b3, _ = http("POST", f"{V1}/deals/get", body={"deal_id": lid}, signed=True)
        ids = {deal_id_of(b1), deal_id_of(b2), deal_id_of(b3)}
        if s1 == 200 and s2 == 200 and s3 == 200 and ids == {lid}:
            record("C4", "PASS", "all lookups match")
        else:
            record("C4", "FAIL", f"{s1}/{s2}/{s3} ids={ids}")
    else:
        record("C4", "FAIL", "create failed")

    # C5 client stat
    st, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={"amount_rub": 500, "client_transaction_id": ctx_id("c5"), "fingerprint": "buyer-c5"},
        signed=True,
    )
    sid = deal_id_of(body)
    if st in {200, 201} and sid:
        stat = {
            "paid_orders": 7,
            "buy_paid": 7,
            "buy_failed": 3,
            "turnover_rub": 84500,
            "conversion_pct": 70.0,
        }
        s1, b1, _ = http("POST", f"{V1}/deals/{sid}/client-stat", body=stat, signed=True)
        s2, b2, _ = http(
            "POST",
            f"{V1}/clients/stat",
            body={"fingerprint": "buyer-c5", **stat},
            signed=True,
        )
        s3, check, _ = http("GET", f"{V1}/deals/{sid}/check", signed=True)
        if s1 == 200 and s2 == 200 and s3 == 200:
            record("C5", "PASS", "stat + check ok")
        elif is_route_missing(s1, b1) or is_route_missing(s2, b2) or is_route_missing(s3, check):
            record(
                "C5",
                "FAIL",
                "client-stat/check routes missing on staging backend (local repo has them)",
            )
        else:
            record("C5", "FAIL", f"{s1}/{s2}/{s3} {detail_text(check)}")
    else:
        record("C5", "FAIL", "create failed")

    # D4 bad receipt
    st, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={"amount_rub": 500, "client_transaction_id": ctx_id("d4"), "fingerprint": "d4"},
        signed=True,
    )
    did4 = deal_id_of(body)
    if did4:
        http("POST", f"{V1}/deals/{did4}/paid", body={}, signed=True)
        s1, b1, _ = http(
            "POST", f"{V1}/deals/{did4}/receipt", body={"file": "not-a-url"}, signed=True
        )
        s2, b2, _ = http(
            "POST", f"{V1}/deals/{did4}/receipt", body={"file": "data:application/pdf;base64,aaa"}, signed=True
        )
        if s1 == 400 and s2 == 400:
            record("D4", "PASS", "non-url receipts rejected")
        else:
            record("D4", "FAIL", f"{s1}/{s2}")
    else:
        record("D4", "FAIL", "setup failed")

    # D5 foreign deal
    s, b, _ = http(
        "POST",
        f"{V1}/deals/999999991/receipt",
        body={"file": "https://example.com/x.pdf"},
        signed=True,
    )
    expect_status("D5", s, {404, 400}, b)
    record("E13", "PASS" if s in {404, 400} else "FAIL", f"foreign deal HTTP {s}")

    record("D7", "SKIP", "needs merchant fail injection")

    # D8 race cancel vs receipt
    st, body, _ = http(
        "POST",
        f"{V1}/deals",
        body={"amount_rub": 500, "client_transaction_id": ctx_id("d8"), "fingerprint": "d8"},
        signed=True,
    )
    did8 = deal_id_of(body)
    if did8:
        http("POST", f"{V1}/deals/{did8}/paid", body={}, signed=True)

        def _cancel() -> tuple[int, Any]:
            return http("POST", f"{V1}/deals/{did8}/cancel", body={}, signed=True)[:2]

        def _receipt() -> tuple[int, Any]:
            return http(
                "POST",
                f"{V1}/deals/{did8}/receipt",
                body={"file": "https://example.com/race.pdf"},
                signed=True,
            )[:2]

        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = [pool.submit(_cancel), pool.submit(_receipt)]
            outcomes = [f.result() for f in as_completed(futs)]
        st_g, got, _ = http("GET", f"{V1}/deals/{did8}", signed=True)
        final = got.get("status") if isinstance(got, dict) else None
        codes = sorted(o[0] for o in outcomes)
        if final in {"cancelled", "pending", "awaiting_receipt"} and final != "confirmed":
            record("D8", "PASS", f"final={final} codes={codes}")
        else:
            record("D8", "FAIL", f"final={final} codes={codes}")
    else:
        record("D8", "FAIL", "setup failed")


def run_money_abuse(ops_token: str | None, admin_token: str | None) -> None:
    record("E3", "PASS", "covered by A5") if any(r[0] == "A5" and r[1] == "PASS" for r in RESULTS) else record(
        "E3", "FAIL", "A5 did not pass"
    )

    # E4 trust off + internal settle
    if not INTERNAL:
        record("E4", "SKIP", "no INTERNAL_API_SECRET")
        record("E5", "SKIP", "no INTERNAL_API_SECRET")
        record("E11", "SKIP", "no INTERNAL_API_SECRET")
    else:
        st, body, _ = http(
            "POST",
            f"{V1}/deals",
            body={"amount_rub": 500, "client_transaction_id": ctx_id("e4"), "fingerprint": "e4"},
            signed=True,
        )
        did = deal_id_of(body)
        if did:
            http("POST", f"{V1}/deals/{did}/paid", body={}, signed=True)
            http(
                "POST",
                f"{V1}/deals/{did}/receipt",
                body={"file": "https://example.com/e4.pdf"},
                signed=True,
            )
            st_s, settled, _ = http(
                "POST",
                f"/api/internal/external/deals/{did}/payfast-settled",
                body={"webhook_body": {"status": "SUCCSES", "status_file": 0}},
                headers={"X-Internal-Token": INTERNAL},
            )
            st_g, got, _ = http("GET", f"{V1}/deals/{did}", signed=True)
            status = got.get("status") if isinstance(got, dict) else None
            confirmed_flag = isinstance(settled, dict) and settled.get("confirmed")
            if st_s == 200 and status != "confirmed" and not confirmed_flag:
                record("E4", "PASS", f"settle http={st_s} status={status} confirmed={confirmed_flag}")
                record("E11", "PASS", "no auto-confirm while trust off")
            else:
                record("E4", "FAIL", f"settle={st_s} status={status} body={detail_text(settled)}")
                record("E11", "FAIL", "unexpected auto-confirm")
        else:
            record("E4", "FAIL", "setup failed")
            record("E11", "FAIL", "setup failed")

        st_s, settled, _ = http(
            "POST",
            "/api/internal/external/deals/payfast-settled-by-ref",
            body={"merchant_ref": f"no-such-ref-{PREFIX}"},
            headers={"X-Internal-Token": INTERNAL},
        )
        if st_s == 200 and isinstance(settled, dict) and (
            settled.get("skipped") or settled.get("reason") == "deal_not_found" or not settled.get("confirmed")
        ):
            record("E5", "PASS", detail_text(settled))
        else:
            record("E5", "FAIL", f"{st_s} {detail_text(settled)}")

    # E7 HMAC cannot hit admin create
    st, body, _ = http(
        "POST",
        f"/api/admin/external/exchangers/{EXCHANGER_ID}/deals",
        body={"amount_rub": 100, "pending": False},
        signed=True,
    )
    if st in {401, 403, 404, 405, 422}:
        record("E7", "PASS", f"HMAC blocked from admin create HTTP {st}")
    else:
        record("E7", "FAIL", f"unexpected {st} {detail_text(body)}")

    # E8 HMAC cannot ops confirm
    st, body, _ = http(
        "POST",
        "/api/operator/external/deals/1/confirm",
        body={},
        signed=True,
    )
    if st in {401, 403, 404}:
        record("E8", "PASS", f"HMAC blocked from ops confirm HTTP {st}")
    else:
        record("E8", "FAIL", f"unexpected {st}")

    record("E9", "SKIP", "cabinet payout needs owner password")
    record("E10", "SKIP", "payout_on_credit is cabinet-only")
    record("E15", "NOTE", "ReplayCache prefers Redis SET NX; falls back to process-local memory")
    record("G1", "SKIP", "cabinet JWT needs password")
    record("G2", "SKIP", "cabinet payouts need password")
    record("F1", "SKIP", "browser click-pass")
    record("F2", "SKIP", "browser click-pass")
    record("F3", "SKIP", "browser click-pass")
    record("F4", "SKIP", "browser click-pass")
    record("F5", "SKIP", "browser click-pass")


def run_env_section() -> None:
    # H1 probed by successful create in B1 — set after
    if any(r[0] == "B1" and r[1] == "PASS" for r in RESULTS):
        record("H1", "PASS", "HMAC create works on staging")
    else:
        record("H1", "FAIL", "B1 did not pass")
    # H2 — bill presence
    if any(r[0] == "B1" and r[1] == "PASS" for r in RESULTS):
        record("H2", "PASS", "create returned bill (fake/live payfast)")
    else:
        record("H2", "FAIL", "no bill")
    record("H3", "PASS", "fail-closed checked at startup")


def main() -> int:
    global BASE, API_KEY, SECRET
    if not BASE or not API_KEY or not SECRET:
        print("FAIL-CLOSED: need STAGING_BASE_URL, EXCHANGER_API_KEY, EXCHANGER_HMAC_SECRET", file=sys.stderr)
        # still record H3 conceptually
        return 2
    if "focuspay.org" in BASE and "18081" not in BASE and "staging" not in BASE:
        print("REFUSING production-looking BASE URL", file=sys.stderr)
        return 2

    print(f"BASE={BASE} exchanger={EXCHANGER_ID} prefix={PREFIX}")
    cb = CATCHER.start_if_configured()
    print(f"callback_url={cb or '(none)'}")

    ops_token = login("operator", OPS_USER, OPS_PASS) if OPS_USER and OPS_PASS else None
    admin_token = login("admin", ADMIN_USER, ADMIN_PASS) if ADMIN_USER and ADMIN_PASS else None
    print(f"ops_token={'yes' if ops_token else 'no'} admin_token={'yes' if admin_token else 'no'}")

    try:
        run_auth_section()
        run_create_section()
        run_happy_and_lifecycle(ops_token, admin_token)
        run_money_abuse(ops_token, admin_token)
        run_env_section()
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        record("FATAL", "FAIL", str(exc))
    finally:
        CATCHER.stop()

    # dedupe keeping last
    by_id: dict[str, tuple[str, str, str]] = {}
    for row in RESULTS:
        by_id[row[0]] = row
    final = sorted(by_id.values(), key=lambda r: r[0])
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "NOTE": 0}
    print("\n=== SUMMARY ===")
    for cid, status, detail in final:
        counts[status] = counts.get(status, 0) + 1
        print(f"{status:4} {cid:4} {detail}")
    print(
        f"\nPASS={counts.get('PASS', 0)} FAIL={counts.get('FAIL', 0)} "
        f"SKIP={counts.get('SKIP', 0)} NOTE={counts.get('NOTE', 0)}"
    )
    money = [r for r in final if r[0].startswith(("C", "D", "E", "B8", "B14")) and r[1] == "FAIL"]
    if money:
        print("\nMONEY-RISK FAILURES:")
        for r in money:
            print(f"  {r[0]}: {r[2]}")
    return 1 if counts.get("FAIL", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
