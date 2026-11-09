"""Opt-in harness for an isolated PayFast external-deal E2E test.

This module never provisions infrastructure. It accepts only an explicitly supplied
loopback database or an owned internal Compose database and starts the real FastAPI
application in-process so the test can seed its rate cache without contacting a
market-data provider.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import socket
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import urlparse


OPT_IN_FLAG = "STAGING_E2E_PAYFAST"
DSN_VARIABLE = "STAGING_E2E_PAYFAST_DSN"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
INTERNAL_COMPOSE_HOST = "postgres"
INTERNAL_COMPOSE_FLAG = "STAGING_E2E_PAYFAST_INTERNAL"


class E2EConfigurationError(RuntimeError):
    """The E2E environment is absent or violates the isolated-test contract."""


@dataclass(frozen=True)
class E2EConfig:
    dsn: str

    @classmethod
    def from_environment(cls) -> "E2EConfig":
        if os.environ.get(OPT_IN_FLAG) != "1":
            raise E2EConfigurationError(f"{OPT_IN_FLAG}=1 is required")
        dsn = os.environ.get(DSN_VARIABLE, "").strip()
        if not dsn:
            raise E2EConfigurationError(
                f"{DSN_VARIABLE} must name a disposable loopback or owned internal Compose database"
            )
        parsed = urlparse(dsn)
        database = (parsed.path or "").strip("/").lower()
        is_loopback = parsed.hostname in LOOPBACK_HOSTS
        is_owned_compose_db = (
            os.environ.get(INTERNAL_COMPOSE_FLAG) == "1"
            and parsed.hostname == INTERNAL_COMPOSE_HOST
            and database.startswith("e2e_payfast_")
        )
        if parsed.scheme not in {"postgres", "postgresql"} or not (is_loopback or is_owned_compose_db):
            raise E2EConfigurationError(
                "PayFast E2E accepts only a loopback DSN or the owned internal Compose database"
            )
        if not database.startswith(("staging_", "e2e_", "test_")):
            raise E2EConfigurationError("PayFast E2E database name must begin staging_, e2e_, or test_")
        return cls(dsn=dsn)


def loopback_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise E2EConfigurationError(f"external network is forbidden in PayFast E2E: {url!r}")
    return url


@contextmanager
def deny_external_network() -> Iterator[None]:
    """Fail closed for new TCP connections outside loopback during the E2E test."""
    original_create_connection = socket.create_connection
    original_connect = socket.socket.connect

    def verify_host(address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if str(host).lower() in LOOPBACK_HOSTS:
            return
        if os.environ.get(INTERNAL_COMPOSE_FLAG) == "1" and str(host).lower() == INTERNAL_COMPOSE_HOST:
            return
        raise E2EConfigurationError(f"external network is forbidden in PayFast E2E: {host!r}")

    def guarded_create_connection(address: Any, *args: Any, **kwargs: Any):
        verify_host(address)
        return original_create_connection(address, *args, **kwargs)

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        verify_host(address)
        return original_connect(sock, address)

    socket.create_connection = guarded_create_connection
    socket.socket.connect = guarded_connect
    try:
        yield
    finally:
        socket.create_connection = original_create_connection
        socket.socket.connect = original_connect


def raw_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def hmac_headers(api_key: str, secret: str, body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
        "X-Timestamp": timestamp,
        "X-Signature": signature,
    }


def backend_root() -> Path:
    return Path(__file__).resolve().parents[2] / "site" / "exchange-backend"


@contextmanager
def isolated_backend_import_directory() -> Iterator[None]:
    """Prevent BaseSettings from discovering the repository's .env during backend imports."""
    original_directory = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="payfast-e2e-") as directory:
        os.chdir(directory)
        try:
            yield
        finally:
            os.chdir(original_directory)


class _CallbackReceiver:
    def __init__(self, handler: Any) -> None:
        self._handler = handler
        self.requests: list[bytes] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("callback receiver is not running")
        return f"http://127.0.0.1:{self._server.server_port}/payfast-callback"

    def __enter__(self) -> "_CallbackReceiver":
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                receiver.requests.append(raw)
                status = int(receiver._handler(raw))
                self.send_response(status)
                self.end_headers()

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None


@contextmanager
def callback_receiver(handler: Any) -> Iterator[_CallbackReceiver]:
    """Start a controlled loopback-only receiver for Fake PayFast delivery."""
    with _CallbackReceiver(handler) as receiver:
        yield receiver


async def seed_payfast_e2e_fixture(conn: Any, *, api_key: str, api_secret: str) -> int:
    """Insert only synthetic actor rows into an already-migrated disposable database."""
    for role in ("client", "finance"):
        operator_id = await conn.fetchval(
            """
            INSERT INTO operator_accounts (
                username, password_hash, percent, is_active, operator_role, operator_roles
            ) VALUES ($1, 'e2e-no-login', 0, TRUE, $2, ARRAY[$2]::TEXT[])
            RETURNING id
            """,
            f"e2e-payfast-{role}-{api_key[-12:]}",
            role,
        )
        await conn.execute(
            "INSERT INTO operator_shifts (operator_id, started_at) VALUES ($1, now())",
            operator_id,
        )
    exchanger_id = await conn.fetchval(
        """
        INSERT INTO external_exchangers (
            name, contact, is_active, net_percent, markup_pct, markup_mode,
            is_trusted_client, auto_credit_on_payfast
        ) VALUES ('PayFast E2E synthetic exchanger', 'synthetic-only', TRUE, 20, 0, 'on_deal', TRUE, TRUE)
        RETURNING id
        """
    )
    await conn.execute(
        """
        INSERT INTO external_exchanger_api_keys (
            exchanger_id, api_key, secret, secret_hash, secret_hint, is_active
        ) VALUES ($1, $2, $3, 'e2e-only', 'e2e', TRUE)
        """,
        exchanger_id,
        api_key,
        api_secret,
    )
    return int(exchanger_id)


async def assert_payment_schema(conn: Any) -> None:
    required = {
        "external_exchangers",
        "external_exchanger_api_keys",
        "external_deals",
        "external_ledger",
        "operator_accounts",
        "operator_shifts",
        "operator_payroll_ledger",
    }
    found = {
        str(row["table_name"])
        for row in await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
    }
    missing = sorted(required - found)
    if missing:
        raise E2EConfigurationError(
            "disposable DB is not payment-E2E ready; missing tables: " + ", ".join(missing)
        )


async def deal_snapshot(conn: Any, deal_id: int) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        SELECT id, status, merchant_order_id, payment_snapshot, client_transaction_id,
               paid_confirmed_at, receipt_submitted_at, receipt_file, principal_usdt,
               required_receipt_type
        FROM external_deals WHERE id = $1
        """,
        deal_id,
    )
    if not row:
        raise AssertionError(f"deal {deal_id} was not persisted")
    snapshot = dict(row)
    payment_snapshot = snapshot.get("payment_snapshot")
    if isinstance(payment_snapshot, str):
        snapshot["payment_snapshot"] = json.loads(payment_snapshot)
    return snapshot


async def principal_ledger_count(conn: Any, deal_id: int) -> int:
    return int(
        await conn.fetchval(
            "SELECT count(*) FROM external_ledger WHERE deal_id = $1 AND type = 'principal'", deal_id
        )
    )


async def payfast_review_count(
    conn: Any,
    *,
    deal_id: int | None = None,
    merchant_ref: str | None = None,
    incident_type: str | None = None,
) -> int:
    clauses: list[str] = []
    values: list[Any] = []
    if deal_id is not None:
        values.append(deal_id)
        clauses.append(f"deal_id = ${len(values)}")
    if merchant_ref is not None:
        values.append(merchant_ref)
        clauses.append(f"merchant_ref = ${len(values)}")
    if incident_type is not None:
        values.append(incident_type)
        clauses.append(f"incident_type = ${len(values)}")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return int(await conn.fetchval(f"SELECT count(*) FROM external_deal_payfast_reviews{where}", *values))


async def start_real_app() -> tuple[Any, Any]:
    """Create the actual route graph and pre-fill its rate cache without lifespan tasks.

    Production lifespan starts Telegram-adjacent bridges and schedulers.  This harness
    deliberately exercises the real routes without entering that lifespan, so it cannot
    start polling or background outbound clients.
    """
    import sys

    root = str(backend_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    from routers import public

    public._store_rates({"usdt": 100.0, "btc": 6_000_000.0, "ltc": 8_000.0, "trx": 10.0}, source="e2e")
    from main import app

    return app, public


async def shutdown_background_refresh(public_module: Any) -> None:
    task = public_module._bg_refresh
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
