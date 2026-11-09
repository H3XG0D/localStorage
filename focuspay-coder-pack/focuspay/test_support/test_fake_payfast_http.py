from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_support.fake_payfast_http import FakePayFastHttp


class FakePayFastHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakePayFastHttp()
        self.fake.__enter__()

    def tearDown(self) -> None:
        self.fake.__exit__()

    def post(self, path: str, payload: dict, *, signature: str | None = None, timestamp: str | None = None):
        raw = json.dumps(payload, separators=(",", ":")).encode()
        timestamp = timestamp or str(int(time.time()))
        signature = signature or hmac.new(
            self.fake.secret_key.encode(), timestamp.encode() + raw, hashlib.sha256
        ).hexdigest()
        request = Request(
            self.fake.base_url + path,
            data=raw,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-API-Key": self.fake.api_key,
                "X-Timestamp": timestamp,
                "X-Signature": signature,
            },
        )
        try:
            with urlopen(request, timeout=1) as response:  # nosec B310: loopback fake
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def create(self, client_id: str = "local-order") -> dict:
        status, body = self.post("/create_order_payin", {
            "token": "P2P", "sub_token": "CARDRUB", "fingerprint": "42",
            "client_transaction_id": client_id, "amount": 1000,
            "callback_url": "http://127.0.0.1:1/callback",
        })
        self.assertEqual(status, 200)
        return body

    def test_hmac_fails_closed_before_state_change(self) -> None:
        payload = {"uuid": "unknown"}
        for timestamp, signature in ((str(int(time.time())), "bad"), ("1", "bad")):
            status, body = self.post("/get_order", payload, timestamp=timestamp, signature=signature)
            self.assertEqual(status, 401)
            self.assertEqual(body["status_pending"], "error")
        self.assertEqual(self.fake.requests, [])

    def test_delay_next_created_bill_is_absent_once_then_resolves_on_get_order(self) -> None:
        self.fake.delay_next_created_bill(bank="Delayed Bank", receiver="+79991112233")
        created = self.create("delayed")
        merchant_uuid = created["uuid_system"]
        self.assertEqual(created["bill"], {})
        self.assertEqual(created["data_order"]["bill"], {})
        _, resolved = self.post("/get_order", {"uuid": merchant_uuid})
        self.assertEqual(resolved["bill"]["bank"], "Delayed Bank")
        self.assertEqual(resolved["bill"]["reciver"], "+79991112233")
        self.assertTrue(self.create("ordinary")["bill"])

    def test_ids_bills_cancellation_and_unknown_uuid(self) -> None:
        created = self.create("local-1")
        merchant_uuid = created["uuid_system"]
        self.assertNotEqual(merchant_uuid, "local-1")
        self.assertTrue(created["bill"])
        self.fake.set_delayed_bill(merchant_uuid)
        _, pending = self.post("/get_order", {"uuid": "local-1"})
        self.assertEqual(pending["bill"], {})
        self.fake.assign_bill(merchant_uuid)
        _, resolved = self.post("/get_order", {"uuid": merchant_uuid})
        self.assertTrue(resolved["bill"])
        status, canceled = self.post("/cancel_order_payin", {"uuid": "local-1"})
        self.assertEqual(status, 200)
        self.assertEqual(canceled["data_order"]["status"], "ERROR")
        status, unknown = self.post("/get_order", {"uuid": "missing"})
        self.assertEqual(status, 400)
        self.assertEqual(unknown["msg"], "NOT FOUND ORDER")

    def test_receipt_retry_settlement_and_scripted_failures(self) -> None:
        merchant_uuid = self.create()["uuid_system"]
        self.fake.reject_next_receipt(merchant_uuid)
        status, _ = self.post("/payin_set_check", {"uuid": merchant_uuid, "file": "https://example.invalid/a.pdf"})
        self.assertEqual(status, 500)
        self.assertIsNone(self.fake.order(merchant_uuid)["extra_info"]["check"])
        status, body = self.post("/payin_set_check", {"uuid": merchant_uuid, "file": "not-fetched://receipt"})
        self.assertEqual((status, body["status_pending"]), (200, "ok"))
        settled = self.fake.order(merchant_uuid)
        self.assertEqual((settled["status"], settled["status_file"]), ("PAID", 0))
        self.fake.queue_receipt_failure(
            merchant_uuid,
            status=400,
            body={"status_pending": "error", "error": "receipt rejected"},
        )
        status, rejected = self.post("/payin_set_check", {"uuid": merchant_uuid, "file": "not-fetched://permanent"})
        self.assertEqual((status, rejected["error"]), (400, "receipt rejected"))
        self.assertEqual(self.fake.order(merchant_uuid)["status"], "PAID")
        self.fake.set_order_state(merchant_uuid, status="PAID", status_file=1)
        self.assertEqual(self.fake.order(merchant_uuid)["status_file"], 1)
        self.fake.queue_response(status=429, body={"status_pending": "error", "error": "slow down"})
        status, _ = self.post("/get_order", {"uuid": merchant_uuid})
        self.assertEqual(status, 429)
        self.fake.queue_response(status=500, body={"status_pending": "error"}, delay=0.2)
        with self.assertRaises(TimeoutError):
            raw = json.dumps({"uuid": merchant_uuid}, separators=(",", ":")).encode()
            ts = str(int(time.time()))
            sig = hmac.new(self.fake.secret_key.encode(), ts.encode() + raw, hashlib.sha256).hexdigest()
            urlopen(Request(self.fake.base_url + "/get_order", data=raw, method="POST", headers={
                "X-API-Key": self.fake.api_key, "X-Timestamp": ts, "X-Signature": sig,
            }), timeout=0.01)  # nosec B310: loopback fake

    def test_callback_is_loopback_only_duplicate_and_mismatch_are_fixture_controlled(self) -> None:
        merchant_uuid = self.create()["uuid_system"]
        with self.assertRaises(ValueError):
            self.fake.deliver_callback("https://example.com/callback", merchant_uuid)

        received: list[dict] = []
        class Receiver(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
            def log_message(self, _format: str, *_args: object) -> None:
                return
        server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            statuses = self.fake.deliver_callback(
                f"http://127.0.0.1:{server.server_port}/callback", merchant_uuid,
                uuid="unknown-uuid",
                client_transaction_id="wrong-client-id",
                amount="1001.00",
                data_order={**self.fake.order(merchant_uuid), "status": "SUCCSES", "amount": 1001},
                repeats=2,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
        self.assertEqual(statuses, [200, 200])
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0]["uuid"], "unknown-uuid")
        self.assertEqual(received[0]["client_transaction_id"], "wrong-client-id")
        self.assertEqual(received[0]["amount"], "1001.00")
        self.assertEqual(received[0]["data_order"]["status"], "SUCCSES")
        self.assertEqual(self.fake.order(merchant_uuid)["status"], "ACCEPTED")


if __name__ == "__main__":
    unittest.main()
