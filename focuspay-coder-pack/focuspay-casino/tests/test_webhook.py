import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import webhook


SECRET = "callback-test-secret"


def serialized(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def signed_headers(
    body: bytes,
    *,
    secret: str = SECRET,
    timestamp: str | None = None,
) -> dict[str, str]:
    timestamp = timestamp or str(int(time.time()))
    signature = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Timestamp": timestamp,
        "X-Signature": signature,
        "Content-Type": "application/json",
    }


def callback_payload(*, event: str = "credited") -> dict:
    return {
        "event": event,
        "deal_id": 321,
        "client_transaction_id": "casino-dep-999999999-forged-callback",
        "status": "confirmed" if event == "credited" else "cancelled",
        "amount_rub": 999999.99,
    }


def trusted_deal(*, status: str = "confirmed", **overrides) -> dict:
    deal = {
        "id": 321,
        "deal_id": 321,
        "client_transaction_id": "casino-dep-123456789-authoritative_001",
        "status": status,
        "amount_rub": 150.25,
    }
    deal.update(overrides)
    return deal


def credit_result(**overrides) -> dict:
    result = {
        "success": True,
        "idempotent": False,
        "deal_id": 321,
        "telegram_id": 123456789,
        "amount_rub": "150.25",
        "status": "credited",
    }
    result.update(overrides)
    return result


class FocusPayWebhookTests(unittest.TestCase):
    def setUp(self):
        webhook.callback_replay_cache.clear()
        self.client = TestClient(webhook.app)

    def post_signed(self, payload: dict, *, secret: str = SECRET, timestamp=None):
        body = serialized(payload)
        return self.client.post(
            "/webhook",
            content=body,
            headers=signed_headers(body, secret=secret, timestamp=timestamp),
        )

    def test_credited_callback_uses_only_authoritative_deal_and_durable_credit(self):
        payload = callback_payload()
        focuspay = AsyncMock()
        focuspay.get_deal_status.return_value = trusted_deal()
        focuspay.credit_deposit.return_value = credit_result()
        focuspay.get_wagering.return_value = {
            "locked_rub": "150.25",
            "remaining_rub": "31.55",
        }

        with (
            patch.object(webhook, "FOCUSPAY_EXCHANGER_SECRET", SECRET),
            patch.object(webhook, "get_focuspay_client", AsyncMock(return_value=focuspay)),
            patch.object(webhook.bot, "send_message", AsyncMock()) as send_message,
        ):
            response = self.post_signed(payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "success": True,
            "event": "credited",
            "deal_id": 321,
            "idempotent": False,
        })
        focuspay.get_deal_status.assert_awaited_once_with(321)
        focuspay.credit_deposit.assert_awaited_once_with(deal_id=321)
        focuspay.get_wagering.assert_awaited_once_with(123456789)
        focuspay.payout.assert_not_awaited()
        send_message.assert_awaited_once()
        self.assertEqual(send_message.await_args.args[0], 123456789)
        self.assertIn("150.25 ₽", send_message.await_args.args[1])
        self.assertIn("31.55 ₽", send_message.await_args.args[1])
        self.assertNotIn("999999.99", send_message.await_args.args[1])

    def test_credit_callback_returns_503_without_durable_backend_endpoint(self):
        focuspay = AsyncMock()
        focuspay.get_deal_status.return_value = trusted_deal()
        focuspay.credit_deposit.side_effect = AttributeError("missing endpoint")

        with (
            patch.object(webhook, "FOCUSPAY_EXCHANGER_SECRET", SECRET),
            patch.object(webhook, "get_focuspay_client", AsyncMock(return_value=focuspay)),
        ):
            response = self.post_signed(callback_payload())

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "Durable casino deposit credit is not available",
        )
        focuspay.get_deal_status.assert_awaited_once_with(321)
        focuspay.credit_deposit.assert_awaited_once_with(deal_id=321)
        focuspay.payout.assert_not_awaited()

    def test_credited_callback_delivers_credit_when_wagering_status_unavailable(self):
        focuspay = AsyncMock()
        focuspay.get_deal_status.return_value = trusted_deal()
        focuspay.credit_deposit.return_value = credit_result()
        focuspay.get_wagering.side_effect = RuntimeError("status unavailable")

        with (
            patch.object(webhook, "FOCUSPAY_EXCHANGER_SECRET", SECRET),
            patch.object(webhook, "get_focuspay_client", AsyncMock(return_value=focuspay)),
            patch.object(webhook.bot, "send_message", AsyncMock()) as send_message,
        ):
            response = self.post_signed(callback_payload())

        self.assertEqual(response.status_code, 200)
        focuspay.credit_deposit.assert_awaited_once_with(deal_id=321)
        focuspay.get_wagering.assert_awaited_once_with(123456789)
        self.assertIn("150.25 ₽", send_message.await_args.args[1])
        self.assertNotIn("Отыгрыш выполнен", send_message.await_args.args[1])

    def test_rejects_bad_signature_before_authoritative_lookup(self):
        focuspay = AsyncMock()

        with (
            patch.object(webhook, "FOCUSPAY_EXCHANGER_SECRET", SECRET),
            patch.object(webhook, "get_focuspay_client", AsyncMock(return_value=focuspay)),
        ):
            response = self.post_signed(callback_payload(), secret="wrong-secret")

        self.assertEqual(response.status_code, 401)
        focuspay.get_deal_status.assert_not_awaited()
        focuspay.credit_deposit.assert_not_awaited()

    def test_rejects_expired_signature(self):
        focuspay = AsyncMock()

        with (
            patch.object(webhook, "FOCUSPAY_EXCHANGER_SECRET", SECRET),
            patch.object(webhook, "get_focuspay_client", AsyncMock(return_value=focuspay)),
        ):
            response = self.post_signed(
                callback_payload(event="cancelled"),
                timestamp=str(int(time.time()) - webhook.CALLBACK_MAX_SKEW_SECONDS - 1),
            )

        self.assertEqual(response.status_code, 401)
        focuspay.get_deal_status.assert_not_awaited()

    def test_rejects_replay_after_successful_processing(self):
        payload = callback_payload(event="cancelled")
        body = serialized(payload)
        timestamp = str(int(time.time()))
        headers = signed_headers(body, timestamp=timestamp)
        focuspay = AsyncMock()
        focuspay.get_deal_status.return_value = trusted_deal(status="cancelled")

        with (
            patch.object(webhook, "FOCUSPAY_EXCHANGER_SECRET", SECRET),
            patch.object(webhook, "get_focuspay_client", AsyncMock(return_value=focuspay)),
            patch.object(webhook.bot, "send_message", AsyncMock()),
        ):
            first = self.client.post("/webhook", content=body, headers=headers)
            second = self.client.post("/webhook", content=body, headers=headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        focuspay.get_deal_status.assert_awaited_once_with(321)

    def test_rejects_authoritative_deal_with_invalid_transaction_id(self):
        focuspay = AsyncMock()
        focuspay.get_deal_status.return_value = trusted_deal(
            client_transaction_id="casino-dep-123456789"
        )

        with (
            patch.object(webhook, "FOCUSPAY_EXCHANGER_SECRET", SECRET),
            patch.object(webhook, "get_focuspay_client", AsyncMock(return_value=focuspay)),
        ):
            response = self.post_signed(callback_payload())

        self.assertEqual(response.status_code, 409)
        focuspay.credit_deposit.assert_not_awaited()

    def test_rejects_callback_when_authoritative_status_does_not_match_event(self):
        focuspay = AsyncMock()
        focuspay.get_deal_status.return_value = trusted_deal(status="cancelled")

        with (
            patch.object(webhook, "FOCUSPAY_EXCHANGER_SECRET", SECRET),
            patch.object(webhook, "get_focuspay_client", AsyncMock(return_value=focuspay)),
        ):
            response = self.post_signed(callback_payload())

        self.assertEqual(response.status_code, 409)
        focuspay.credit_deposit.assert_not_awaited()

    def test_missing_shared_secret_fails_closed(self):
        focuspay = AsyncMock()
        body = serialized(callback_payload())

        with (
            patch.object(webhook, "FOCUSPAY_EXCHANGER_SECRET", ""),
            patch.object(webhook, "get_focuspay_client", AsyncMock(return_value=focuspay)),
        ):
            response = self.client.post(
                "/webhook",
                content=body,
                headers={"Content-Type": "application/json"},
            )

        self.assertEqual(response.status_code, 503)
        focuspay.get_deal_status.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
