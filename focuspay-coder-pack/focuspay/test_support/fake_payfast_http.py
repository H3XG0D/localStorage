"""Loopback-only Fake PayFast for contract and E2E tests."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class RecordedRequest:
    path: str
    payload: dict[str, Any]


class FakePayFastHttp:
    """In-memory PayFast HTTP fake that never accepts external callback targets."""

    def __init__(
        self,
        *,
        api_key: str = "test-api-key",
        secret_key: str = "test-secret-key",
        timestamp_tolerance: int = 300,
    ) -> None:
        self.api_key = api_key
        self.secret_key = secret_key
        self.timestamp_tolerance = timestamp_tolerance
        self.requests: list[RecordedRequest] = []
        self.callback_deliveries: list[dict[str, Any]] = []
        self._orders: dict[str, dict[str, Any]] = {}
        self._client_ids: dict[str, str] = {}
        self._delayed_bills: set[str] = set()
        self._delay_next_created_bill: dict[str, Any] | None = None
        self._receipt_rejections: set[str] = set()
        self._next_responses: list[tuple[int, dict[str, Any], float]] = []
        self._endpoint_responses: dict[str, list[tuple[int, dict[str, Any], float]]] = {}
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("Fake PayFast is not running")
        return f"http://127.0.0.1:{self._server.server_port}"

    def serve_forever(self, *, host: str = "0.0.0.0", port: int = 8081) -> None:
        self.start(host=host, port=port)
        assert self._thread is not None
        try:
            self._thread.join()
        finally:
            self.__exit__()

    def __enter__(self) -> "FakePayFastHttp":
        return self.start()

    def start(self, *, host: str = "127.0.0.1", port: int = 0) -> "FakePayFastHttp":
        if self._server is not None:
            raise RuntimeError("Fake PayFast is already running")
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                fake._handle(self)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/health":
                    fake._send(self, 200, {"status": "ok"})
                    return
                fake._send(self, 405, {"status_pending": "error", "error": "POST only"})

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
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

    def queue_response(
        self,
        *,
        status: int,
        body: dict[str, Any],
        delay: float = 0,
        endpoint: str | None = None,
    ) -> None:
        """Script one authenticated response globally or for a single API endpoint."""
        if endpoint is not None and endpoint not in {
            "/create_order_payin", "/get_order", "/payin_set_check", "/cancel_order_payin"
        }:
            raise ValueError(f"Unknown Fake PayFast endpoint: {endpoint}")
        response = (status, self._copy(body), delay)
        with self._lock:
            if endpoint is None:
                self._next_responses.append(response)
            else:
                self._endpoint_responses.setdefault(endpoint, []).append(response)

    def delay_next_created_bill(
        self,
        *,
        bank: str = "Test Bank",
        receiver: str = "+79990000000",
    ) -> None:
        """Hide the next created order's bill until its first ``get_order`` response."""
        with self._lock:
            self._delay_next_created_bill = {"bank": bank, "receiver": receiver}

    def set_delayed_bill(self, merchant_uuid: str) -> None:
        with self._lock:
            self._require_order(merchant_uuid)
            self._delayed_bills.add(merchant_uuid)
            self._orders[merchant_uuid]["bill"] = {}

    def assign_bill(self, merchant_uuid: str, *, bank: str = "Test Bank", receiver: str = "+79990000000") -> None:
        with self._lock:
            order = self._require_order(merchant_uuid)
            self._delayed_bills.discard(merchant_uuid)
            order["bill"] = self._bill(bank=bank, receiver=receiver, sub_token=str(order["sub_token"]))

    def reject_next_receipt(self, merchant_uuid: str) -> None:
        """Backward-compatible one-shot retryable receipt failure."""
        with self._lock:
            self._require_order(merchant_uuid)
            self._receipt_rejections.add(merchant_uuid)

    def queue_receipt_failure(
        self,
        merchant_uuid: str,
        *,
        status: int,
        body: dict[str, Any] | None = None,
        delay: float = 0,
    ) -> None:
        """Script a receipt failure for one order; supports retryable 5xx and permanent 4xx."""
        if status < 400:
            raise ValueError("Receipt failure status must be 4xx or 5xx")
        with self._lock:
            self._require_order(merchant_uuid)
            scripted = (status, self._copy(body or {"status_pending": "error", "error": "synthetic receipt failure"}), delay)
            self._endpoint_responses.setdefault(f"/payin_set_check:{merchant_uuid}", []).append(scripted)

    def set_order_state(
        self,
        merchant_uuid: str,
        *,
        status: str | None = None,
        status_file: int | None = None,
        status_check: int | None = None,
    ) -> None:
        with self._lock:
            order = self._require_order(merchant_uuid)
            if status is not None:
                order["status"] = status
            if status_file is not None:
                order["status_file"] = status_file
            if status_check is not None:
                order["status_check"] = status_check

    def order(self, merchant_uuid: str) -> dict[str, Any]:
        with self._lock:
            return self._copy(self._require_order(merchant_uuid))

    def deliver_callback(
        self,
        callback_url: str,
        merchant_uuid: str,
        *,
        order_override: dict[str, Any] | None = None,
        uuid: str | None = None,
        client_transaction_id: str | None = None,
        amount: Any | None = None,
        data_order: dict[str, Any] | None = None,
        repeats: int = 1,
        timeout: float = 1.0,
    ) -> list[int]:
        """Deliver a synthetic callback only to a loopback HTTP URL."""
        parsed = urlparse(callback_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Fake callbacks require an http loopback URL")
        if repeats < 1:
            raise ValueError("repeats must be positive")
        with self._lock:
            order = self._copy(self._require_order(merchant_uuid))
        payload = {
            "uuid": uuid if uuid is not None else merchant_uuid,
            "api_key": self.api_key,
            "id_merchant": 1,
            "client_transaction_id": (
                client_transaction_id if client_transaction_id is not None else order["client_transaction_id"]
            ),
            "amount": amount if amount is not None else order["amount"],
            "data_order": data_order if data_order is not None else (order_override or order),
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        statuses: list[int] = []
        for _ in range(repeats):
            request = Request(callback_url, data=raw, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urlopen(request, timeout=timeout) as response:  # nosec B310: target is loopback-validated
                    status = int(response.status)
            except Exception:
                status = 0
            self.callback_deliveries.append({"merchant_uuid": merchant_uuid, "status": status})
            statuses.append(status)
        return statuses

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        paths = {"/create_order_payin", "/get_order", "/payin_set_check", "/cancel_order_payin"}
        if handler.path not in paths:
            self._send(handler, 404, {"status_pending": "error", "error": "unknown endpoint"})
            return
        length = int(handler.headers.get("Content-Length") or 0)
        raw = handler.rfile.read(length)
        auth_error = self._auth_error(handler, raw)
        if auth_error:
            self._send(handler, 401, {"status_pending": "error", "error": auth_error})
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(handler, 400, {"status_pending": "error", "error": "invalid JSON"})
            return
        if not isinstance(payload, dict):
            self._send(handler, 400, {"status_pending": "error", "error": "JSON object required"})
            return
        self.requests.append(RecordedRequest(handler.path, self._copy(payload)))
        receipt_key = f"/payin_set_check:{payload.get('uuid')}"
        with self._lock:
            endpoint_queue = self._endpoint_responses.get(receipt_key) or self._endpoint_responses.get(handler.path)
            scripted = endpoint_queue.pop(0) if endpoint_queue else None
            if scripted is None and self._next_responses:
                scripted = self._next_responses.pop(0)
        if scripted is not None:
            status, body, delay = scripted
            if delay:
                time.sleep(delay)
            self._send(handler, status, body)
            return
        if handler.path == "/create_order_payin":
            status, body = self._create(payload)
        elif handler.path == "/get_order":
            status, body = self._get_order(payload)
        elif handler.path == "/payin_set_check":
            status, body = self._set_check(payload)
        else:
            status, body = self._cancel(payload)
        self._send(handler, status, body)

    def _auth_error(self, handler: BaseHTTPRequestHandler, raw: bytes) -> str | None:
        api_key = handler.headers.get("X-API-Key")
        timestamp = handler.headers.get("X-Timestamp")
        signature = handler.headers.get("X-Signature")
        if not api_key or not timestamp or not signature:
            return "missing authentication header"
        if not hmac.compare_digest(api_key, self.api_key):
            return "invalid API key"
        try:
            timestamp_value = int(timestamp)
        except ValueError:
            return "invalid timestamp"
        if abs(time.time() - timestamp_value) > self.timestamp_tolerance:
            return "timestamp too old or invalid"
        expected = hmac.new(
            self.secret_key.encode("utf-8"), timestamp.encode("utf-8") + raw, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return "invalid signature"
        return None

    def _create(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        required = {"token", "sub_token", "fingerprint", "client_transaction_id", "amount", "callback_url"}
        if not required <= payload.keys():
            return 500, {"status_pending": "error", "error": "Try later..."}
        client_id = str(payload["client_transaction_id"])
        with self._lock:
            existing = self._client_ids.get(client_id)
            if existing:
                return 200, self._create_response(self._orders[existing])
            merchant_uuid = str(uuid.uuid4())
            delayed = self._delay_next_created_bill
            self._delay_next_created_bill = None
            bill = {} if delayed else self._bill(sub_token=str(payload["sub_token"]))
            order = {
                "status_pending": "ok",
                "status": "ACCEPTED",
                "type": "payin",
                "token": str(payload["token"]),
                "sub_token": str(payload["sub_token"]),
                "fingerprint": str(payload["fingerprint"]),
                "amount": payload["amount"],
                "uuid_system": merchant_uuid,
                "client_transaction_id": client_id,
                "bill": bill,
                "delayed_bill": delayed,
                "status_check": 1,
                "status_file": None,
                "extra_info": {"check": None, "file": None, "message_id": None},
                "callback_url": str(payload["callback_url"]),
            }
            self._orders[merchant_uuid] = order
            self._client_ids[client_id] = merchant_uuid
            return 200, self._create_response(order)

    def _get_order(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        uuid_value = str(payload.get("uuid") or "")
        with self._lock:
            merchant_uuid = uuid_value if uuid_value in self._orders else self._client_ids.get(uuid_value)
            if merchant_uuid is None:
                return 400, {"status_pending": "error", "msg": "NOT FOUND ORDER"}
            order = self._orders[merchant_uuid]
            delayed = order.pop("delayed_bill", None)
            if isinstance(delayed, dict):
                order["bill"] = self._bill(
                    bank=str(delayed["bank"]),
                    receiver=str(delayed["receiver"]),
                    sub_token=str(order["sub_token"]),
                )
            return 200, self._copy(order)

    def _set_check(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        merchant_uuid = str(payload.get("uuid") or "")
        file_url = payload.get("file")
        with self._lock:
            if merchant_uuid not in self._orders or not isinstance(file_url, str) or not file_url:
                return 400, {"status_pending": "error", "error": "Заявка не найдена"}
            order = self._orders[merchant_uuid]
            if merchant_uuid in self._receipt_rejections:
                self._receipt_rejections.remove(merchant_uuid)
                return 500, {"status_pending": "error_server", "error": "Попробуйте позже"}
            order["status"] = "PAID"
            order["status_file"] = 0
            order["extra_info"]["check"] = "synthetic://receipt/" + merchant_uuid
            order["extra_info"]["file"] = file_url
            return 200, {"status_pending": "ok"}

    def _cancel(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        uuid_value = str(payload.get("uuid") or "")
        with self._lock:
            merchant_uuid = uuid_value if uuid_value in self._orders else self._client_ids.get(uuid_value)
            if merchant_uuid is None:
                return 400, {"status_pending": "error", "error": "Заявка не найдена"}
            self._orders[merchant_uuid]["status"] = "ERROR"
            return 200, {"status_pending": "ok", "data_order": self._copy(self._orders[merchant_uuid])}

    @staticmethod
    def _bill(*, sub_token: str, bank: str = "Test Bank", receiver: str = "+79990000000") -> dict[str, Any]:
        return {
            "bank": bank,
            "reciver": receiver,
            "limit_sum": 1_000_000,
            "fio": "Test Recipient",
            "sub_token": sub_token,
            "token": "P2P",
        }

    @staticmethod
    def _copy(value: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(value))

    def _create_response(self, order: dict[str, Any]) -> dict[str, Any]:
        return {
            "status_pending": "ok",
            "status": order["status"],
            "uuid_system": order["uuid_system"],
            "client_transaction_id": order["client_transaction_id"],
            "bill": self._copy(order["bill"]),
            "data_order": self._copy(order),
        }

    def _require_order(self, merchant_uuid: str) -> dict[str, Any]:
        try:
            return self._orders[merchant_uuid]
        except KeyError as error:
            raise KeyError(f"Unknown merchant UUID: {merchant_uuid}") from error

    @staticmethod
    def _send(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(raw)))
        handler.end_headers()
        try:
            handler.wfile.write(raw)
        except BrokenPipeError:
            pass
