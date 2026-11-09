from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "bot" / "tg_bot_btc"))

from test_support.fake_payfast_http import FakePayFastHttp


class BotPayFastHttpFakeTest(unittest.IsolatedAsyncioTestCase):
    async def test_merchant_client_hmac_get_order_cancellation_and_http_errors(self) -> None:
        from services import config_rates, merchant_client

        with FakePayFastHttp() as fake, patch.object(config_rates, "MERCHANT", {
            "base_url": fake.base_url, "api_key": fake.api_key, "secret_key": fake.secret_key,
        }):
            created = await merchant_client.merchant_post("/create_order_payin", {
                "token": "P2P", "sub_token": "CARDRUB", "fingerprint": "17",
                "client_transaction_id": "bot-order", "amount": 900,
                "callback_url": "http://127.0.0.1:1/callback",
            })
            self.assertEqual(created["status_pending"], "ok")
            merchant_uuid = created["uuid_system"]
            order = await merchant_client.get_merchant_order(merchant_uuid)
            self.assertEqual(order["client_transaction_id"], "bot-order")
            self.assertEqual(fake.requests[0].path, "/create_order_payin")
            self.assertEqual(fake.requests[0].payload["client_transaction_id"], "bot-order")

            canceled = await merchant_client.cancel_order_payin(merchant_uuid)
            self.assertTrue(canceled["ok"])
            self.assertEqual(canceled["body"]["data_order"]["status"], "ERROR")

            fake.queue_response(status=500, body={"status_pending": "error", "error": "Try later"})
            server_error = await merchant_client.get_merchant_order(merchant_uuid)
            self.assertEqual((server_error["_http_status"], server_error["status_pending"]), (500, "error"))
            fake.queue_response(status=429, body={"status_pending": "error", "error": "slow down"})
            limited = await merchant_client.get_merchant_order(merchant_uuid)
            self.assertEqual(limited["_http_status"], 429)
            fake.queue_response(status=500, body={"status_pending": "error"}, delay=0.1)
            with self.assertRaises(TimeoutError):
                await merchant_client.get_merchant_order(merchant_uuid, timeout=0.01)

    async def test_discovery_uses_fake_for_immediate_and_card_to_sbp_fallback(self) -> None:
        from services import merchant_client
        from services.payin_discovery import discover_payin_plan

        with FakePayFastHttp() as fake:
            async def create(*, order_id: str, user_id: int, fiat_amount: int, sub_token: str) -> dict:
                return await merchant_client.merchant_post("/create_order_payin", {
                    "token": "P2P", "sub_token": sub_token, "fingerprint": str(user_id),
                    "client_transaction_id": order_id, "amount": fiat_amount,
                    "callback_url": "http://127.0.0.1:1/callback",
                }, timeout=1)

            async def cancel(uuid_value: str) -> dict:
                return await merchant_client.merchant_post("/cancel_order_payin", {"uuid": uuid_value}, timeout=1)

            from services import config_rates
            with patch.object(config_rates, "MERCHANT", {
                "base_url": fake.base_url, "api_key": fake.api_key, "secret_key": fake.secret_key,
            }):
                immediate = await discover_payin_plan(
                    fiat_amount=1000, sub_token="SBPRUB", user_id=1, create_payin_fn=create,
                    cancel_payin_fn=cancel, generate_order_id_fn=lambda: "immediate", poll_bill=False,
                )
                self.assertEqual(immediate.plan.mode, "single")

                order_ids = iter(("card", "sbp"))
                card_merchant_uuids: list[str] = []
                original_create = create
                async def card_without_bill(**kwargs: object) -> dict:
                    response = await original_create(**kwargs)  # type: ignore[arg-type]
                    if kwargs["sub_token"] == "CARDRUB":
                        card_merchant_uuids.append(response["uuid_system"])
                        fake.set_delayed_bill(response["uuid_system"])
                        response["bill"] = {}
                        response["data_order"]["bill"] = {}
                    return response
                fallback = await discover_payin_plan(
                    fiat_amount=1000, sub_token="CARDRUB", user_id=1, create_payin_fn=card_without_bill,
                    cancel_payin_fn=cancel, generate_order_id_fn=lambda: next(order_ids), poll_bill=False,
                )
                self.assertEqual(fallback.plan.resolved_sub_token, "SBPRUB")
                self.assertEqual(fallback.probe_order_id, "sbp")
                self.assertEqual(fake.order(card_merchant_uuids[0])["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
