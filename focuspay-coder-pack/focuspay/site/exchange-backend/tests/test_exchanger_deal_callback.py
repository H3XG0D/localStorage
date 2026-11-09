from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

import exchanger_deal_callback


class _Response:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Session:
    def __init__(self, *args, **kwargs):
        self.request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, url, **kwargs):
        self.request = (url, kwargs)
        _Session.last_request = self.request
        return _Response()


class ExchangerDealCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_configured_secret_signs_exact_serialized_body(self):
        deal = {
            "id": 9,
            "status": "confirmed",
            "client_transaction_id": "casino-dep-101-unique",
            "amount_rub": 1000,
            "callback_url": "https://casino.example/webhook",
            "callback_secret": "shop-secret",
        }

        with (
            patch.object(exchanger_deal_callback.aiohttp, "ClientSession", _Session),
            patch.object(exchanger_deal_callback.time, "time", return_value=1_710_000_000),
        ):
            await exchanger_deal_callback.fire_exchanger_deal_callback(deal, "credited")

        url, kwargs = _Session.last_request
        self.assertEqual(url, deal["callback_url"])
        self.assertNotIn("json", kwargs)
        body = kwargs["data"]
        self.assertIsInstance(body, bytes)
        parsed = json.loads(body)
        self.assertEqual(parsed, exchanger_deal_callback.callback_payload(deal, "credited"))
        self.assertEqual(parsed.get("event_id"), "ext-9-credited")
        headers = kwargs["headers"]
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["X-Timestamp"], "1710000000")
        self.assertEqual(headers.get("X-Event-Id"), "ext-9-credited")
        self.assertTrue(
            exchanger_deal_callback.verify_callback_signature(
                "shop-secret",
                headers["X-Timestamp"],
                body,
                headers["X-Signature"],
            )
        )
        self.assertNotIn("shop-secret", body.decode("utf-8"))

    async def test_unconfigured_callback_remains_unsigned_for_other_consumers(self):
        deal = {
            "id": 10,
            "status": "cancelled",
            "callback_url": "https://legacy.example/webhook",
        }

        with patch.object(exchanger_deal_callback.aiohttp, "ClientSession", _Session):
            await exchanger_deal_callback.fire_exchanger_deal_callback(deal, "cancelled")

        _, kwargs = _Session.last_request
        self.assertNotIn("X-Timestamp", kwargs["headers"])
        self.assertNotIn("X-Signature", kwargs["headers"])

    def test_signature_changes_when_exact_body_changes(self):
        timestamp = "1710000000"
        compact = b'{"event":"credited","deal_id":9}'
        spaced = b'{"event": "credited", "deal_id": 9}'
        signature = exchanger_deal_callback.sign_callback_body(
            "shop-secret", timestamp, compact
        )

        self.assertTrue(
            exchanger_deal_callback.verify_callback_signature(
                "shop-secret", timestamp, compact, signature
            )
        )
        self.assertFalse(
            exchanger_deal_callback.verify_callback_signature(
                "shop-secret", timestamp, spaced, signature
            )
        )


if __name__ == "__main__":
    unittest.main()
