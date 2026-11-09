"""Подпись и разбор вебхуков finance666."""
from __future__ import annotations

import asyncio
import json
import time
import unittest
from decimal import Decimal
from unittest.mock import patch

from services.finance666_client import (
    GROUP_SUCCEEDED,
    is_nspk_qr,
    merchant_balance,
    parse_payment,
    parse_status,
)
from services.webhook_security import (
    sign_finance666_webhook,
    verify_finance666_webhook,
)

SECRET = "whsec_test_secret_value"
WEBHOOK_ID = "7c0e5a52-2f7b-4b51-9a8e-3b1f0d6c9e24"

# Тело как его присылает платформа: компактный JSON, суммы с шестью знаками,
# кириллица без escape. Пересобирать его нельзя — подпись считается по этим байтам.
BODY = (
    '{"transaction_id":"3d835d21-3356-4588-af17-f6e26446fa09",'
    '"merchant_transaction_id":"qr-abcdef0123456789",'
    '"amount_in_currency":1000.000000,"currency":"RUB",'
    '"amount_usdt":100.010000,"fee_usdt":2.000200,"method":"QR_SBP_DIRECT",'
    '"status":{"group":"SUCCEEDED","code":"SUCCESS","is_final":true},'
    '"updated_at":"2026-08-23T10:37:10.701510Z","payee_name":"ЖКХ Москва"}'
).encode("utf-8")


def _signed(body: bytes = BODY, *, skew: int = 0, webhook_id: str = WEBHOOK_ID):
    ts = str(int(time.time()) + skew)
    return ts, sign_finance666_webhook(SECRET, webhook_id, ts, body)


class WebhookSignatureTests(unittest.TestCase):
    def test_valid_signature_accepted(self):
        ts, sig = _signed()
        self.assertTrue(
            verify_finance666_webhook(
                BODY,
                webhook_id=WEBHOOK_ID,
                timestamp=ts,
                signature=sig,
                secret=SECRET,
            )
        )

    def test_tampered_body_rejected(self):
        ts, sig = _signed()
        self.assertFalse(
            verify_finance666_webhook(
                BODY + b" ",
                webhook_id=WEBHOOK_ID,
                timestamp=ts,
                signature=sig,
                secret=SECRET,
            )
        )

    def test_reserialized_json_does_not_match(self):
        """Подпись считается по сырым байтам: пересобранный JSON не сойдётся."""
        ts, sig = _signed()
        reserialized = json.dumps(json.loads(BODY)).encode("utf-8")
        self.assertNotEqual(reserialized, BODY)
        self.assertFalse(
            verify_finance666_webhook(
                reserialized,
                webhook_id=WEBHOOK_ID,
                timestamp=ts,
                signature=sig,
                secret=SECRET,
            )
        )

    def test_stale_timestamp_rejected(self):
        ts, sig = _signed(skew=-600)
        self.assertFalse(
            verify_finance666_webhook(
                BODY,
                webhook_id=WEBHOOK_ID,
                timestamp=ts,
                signature=sig,
                secret=SECRET,
            )
        )

    def test_other_webhook_id_rejected(self):
        ts, sig = _signed(webhook_id="00000000-0000-0000-0000-000000000000")
        self.assertFalse(
            verify_finance666_webhook(
                BODY,
                webhook_id=WEBHOOK_ID,
                timestamp=ts,
                signature=sig,
                secret=SECRET,
            )
        )

    def test_missing_headers_and_secret_rejected(self):
        ts, sig = _signed()
        self.assertFalse(
            verify_finance666_webhook(
                BODY, webhook_id=None, timestamp=ts, signature=sig, secret=SECRET
            )
        )
        self.assertFalse(
            verify_finance666_webhook(
                BODY,
                webhook_id=WEBHOOK_ID,
                timestamp=ts,
                signature=sig,
                secret="",
            )
        )


class PayloadTests(unittest.TestCase):
    def test_parse_payment_keeps_six_decimals(self):
        payment = parse_payment(json.loads(BODY))
        self.assertEqual(payment.amount_in_currency, Decimal("1000.0"))
        self.assertEqual(payment.fee_usdt, Decimal("2.0002"))
        self.assertEqual(payment.total_usdt, Decimal("102.0102"))
        self.assertTrue(payment.status.succeeded)
        self.assertEqual(payment.status.group, GROUP_SUCCEEDED)

    def test_unknown_code_does_not_break_decision(self):
        status = parse_status(
            {"group": "DECLINED", "code": "SOME_BRAND_NEW_REASON", "is_final": True}
        )
        self.assertTrue(status.lost)
        self.assertFalse(status.succeeded)
        self.assertFalse(status.unknown_outcome)

    def test_unknown_group_marked_as_unknown_outcome(self):
        status = parse_status({"group": "WAT", "code": "X", "is_final": True})
        self.assertTrue(status.unknown_outcome)
        self.assertFalse(status.lost)

    def test_missing_fields_are_none(self):
        payment = parse_payment({"transaction_id": "t1", "status": {"group": "PROCESSING"}})
        self.assertIsNone(payment.amount_in_currency)
        self.assertIsNone(payment.payee_name)
        self.assertFalse(payment.status.is_final)


class RequestHeaderTests(unittest.TestCase):
    def test_request_asks_for_encoding_aiohttp_can_decode(self):
        """Платформа отдаёт brotli, если его предложить, а aiohttp его не разберёт."""
        captured: dict = {}

        class FakeResponse:
            status = 200

            async def text(self):
                return "{}"

            async def json(self, content_type=None):
                return {"success": True}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        class FakeSession:
            def request(self, method, url, json=None, headers=None):
                captured.update(headers or {})
                return FakeResponse()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        with patch("aiohttp.ClientSession", lambda *a, **kw: FakeSession()), patch(
            "services.finance666_client._api_key", return_value="pk_test"
        ), patch("services.finance666_client._base_url", return_value="https://api.example"):
            asyncio.run(merchant_balance())

        self.assertEqual(captured.get("X-Api-Key"), "pk_test")
        self.assertNotIn("br", captured.get("Accept-Encoding", ""))


class QrSourceTests(unittest.TestCase):
    def test_only_nspk_links_accepted(self):
        self.assertTrue(is_nspk_qr("https://qr.nspk.ru/AD10000000000000000000000000001"))
        self.assertFalse(is_nspk_qr("https://evil.example/AD1"))
        self.assertFalse(is_nspk_qr("qr.nspk.ru.evil.example/AD1"))
        self.assertFalse(is_nspk_qr(""))
        self.assertFalse(is_nspk_qr("ST00012|Name=..."))


if __name__ == "__main__":
    unittest.main()
