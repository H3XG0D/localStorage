from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "site" / "exchange-backend"))

from test_support.fake_payfast_http import FakePayFastHttp


class BackendPayFastHttpFakeTest(unittest.IsolatedAsyncioTestCase):
    async def test_clients_use_documented_hmac_contract_and_uuid(self) -> None:
        import merchant_client
        import merchant_get_order

        with FakePayFastHttp() as fake, patch.multiple(
            merchant_client.settings,
            merchant_base_url=fake.base_url,
            merchant_api_key=fake.api_key,
            merchant_secret_key=fake.secret_key,
            merchant_default_sub_token="CARDRUB",
            merchant_callback_url="http://127.0.0.1:1/callback/{WEBHOOK_SECRET}",
            webhook_secret="synthetic",
        ), patch.multiple(
            merchant_get_order.settings,
            merchant_base_url=fake.base_url,
            merchant_api_key=fake.api_key,
            merchant_secret_key=fake.secret_key,
        ):
            created = await merchant_client.create_payin_order(
                order_id="backend-local", user_id=99, fiat_amount=1500,
            )
            merchant_uuid = created["uuid_system"]
            self.assertNotEqual(merchant_uuid, "backend-local")
            self.assertEqual(fake.requests[0].path, "/create_order_payin")
            self.assertEqual(fake.requests[0].payload["sub_token"], "CARDRUB")

            by_client_id = await merchant_get_order.get_merchant_order("backend-local")
            self.assertEqual(by_client_id["uuid_system"], merchant_uuid)
            receipt = await merchant_client.payin_set_check(merchant_uuid, "not-fetched://receipt")
            self.assertEqual(receipt["status"], 200)
            settled = await merchant_get_order.get_merchant_order(merchant_uuid)
            self.assertEqual((settled["status"], settled["status_file"]), ("PAID", 0))
            canceled = await merchant_client.cancel_payin(merchant_uuid)
            self.assertEqual(canceled["body"]["data_order"]["status"], "ERROR")

    async def test_http_errors_timeout_unknown_uuid_and_receipt_retry(self) -> None:
        import merchant_client
        import merchant_get_order

        with FakePayFastHttp() as fake, patch.multiple(
            merchant_client.settings,
            merchant_base_url=fake.base_url, merchant_api_key=fake.api_key,
            merchant_secret_key=fake.secret_key, merchant_default_sub_token="SBPRUB",
            merchant_callback_url="http://127.0.0.1:1/callback", webhook_secret="",
        ), patch.multiple(
            merchant_get_order.settings,
            merchant_base_url=fake.base_url, merchant_api_key=fake.api_key, merchant_secret_key=fake.secret_key,
        ):
            unknown = await merchant_get_order.get_merchant_order("unknown")
            self.assertEqual((unknown["status_pending"], unknown["msg"]), ("error", "NOT FOUND ORDER"))
            created = await merchant_client.create_payin_order(order_id="retry", user_id=2, fiat_amount=1)
            merchant_uuid = created["uuid_system"]
            fake.reject_next_receipt(merchant_uuid)
            rejected = await merchant_client.payin_set_check(merchant_uuid, "not-fetched://receipt")
            self.assertEqual(rejected["status"], 500)
            retried = await merchant_client.payin_set_check(merchant_uuid, "not-fetched://receipt")
            self.assertEqual(retried["status"], 200)
            fake.queue_response(status=429, body={"status_pending": "error", "error": "slow down"})
            limited = await merchant_get_order.get_merchant_order(merchant_uuid)
            self.assertEqual(limited["status_pending"], "error")
            fake.queue_response(status=500, body={"status_pending": "error", "error": "later"})
            failed = await merchant_get_order.get_merchant_order(merchant_uuid)
            self.assertEqual(failed["error"], "later")

    async def test_guard_requires_settled_get_order_state(self) -> None:
        from payfast_payin_guard import verify_payfast_ready_for_complete
        import merchant_get_order

        with FakePayFastHttp() as fake, patch.multiple(
            merchant_get_order.settings,
            merchant_base_url=fake.base_url, merchant_api_key=fake.api_key, merchant_secret_key=fake.secret_key,
        ), patch("payfast_payin_guard.get_merchant_order", merchant_get_order.get_merchant_order):
            payload = {
                "token": "P2P", "sub_token": "SBPRUB", "fingerprint": "2",
                "client_transaction_id": "guard", "amount": 10, "callback_url": "http://127.0.0.1:1/cb",
            }
            import json, hashlib, hmac, time
            raw = json.dumps(payload, separators=(",", ":")).encode()
            timestamp = str(int(time.time()))
            signature = hmac.new(fake.secret_key.encode(), timestamp.encode() + raw, hashlib.sha256).hexdigest()
            from urllib.request import Request, urlopen
            with urlopen(Request(fake.base_url + "/create_order_payin", data=raw, method="POST", headers={
                "X-API-Key": fake.api_key, "X-Timestamp": timestamp, "X-Signature": signature,
            }), timeout=1) as response:  # nosec B310: loopback fake
                merchant_uuid = json.loads(response.read())["uuid_system"]
            local_order = {
                "order_id": "guard",
                "direction": "buy",
                "payment_snapshot": {"merchant_uuid": merchant_uuid},
            }
            ok, error = await verify_payfast_ready_for_complete(local_order)
            self.assertFalse(ok)
            self.assertEqual(error, "payfast_not_paid")
            fake.set_order_state(merchant_uuid, status="PAID", status_file=0)
            ok, error = await verify_payfast_ready_for_complete(local_order)
            self.assertFalse(ok)
            self.assertEqual(error, "payfast_awaiting_trader")
            fake.set_order_state(merchant_uuid, status="SUCCSES", status_file=0)
            ok, error = await verify_payfast_ready_for_complete(local_order)
            self.assertTrue(ok)
            self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
