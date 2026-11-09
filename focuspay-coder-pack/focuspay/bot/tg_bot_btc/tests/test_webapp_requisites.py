"""Тесты Mini App initData, prompt helper, cancel_payin_safe gates."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from services.buy_payment_prompt import (
    format_buy_payment_html,
    requisites_webapp_url,
    webapp_requisites_enabled,
)
from services.callback_signatures import (
    sign_device_review,
    sign_order,
    verify_device_review_signature,
    verify_order_signature,
)
from services.tg_webapp_initdata import InitDataError, verify_webapp_init_data


def _make_init_data(bot_token: str, user_id: int = 42, *, skew: int = 0) -> str:
    user = json.dumps({"id": user_id, "username": "alice", "first_name": "A"})
    auth_date = str(int(time.time()) + skew)
    pairs = [("auth_date", auth_date), ("user", user)]
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**dict(pairs), "hash": h})


class InitDataTests(unittest.TestCase):
    def test_ok(self):
        token = "123:ABC"
        raw = _make_init_data(token, 99)
        v = verify_webapp_init_data(raw, token)
        self.assertEqual(v.user.id, 99)

    def test_bad_sig(self):
        token = "123:ABC"
        raw = _make_init_data(token, 99) + "x"
        with self.assertRaises(InitDataError):
            verify_webapp_init_data(raw, token)

    def test_expired(self):
        token = "123:ABC"
        raw = _make_init_data(token, 99, skew=-7200)
        with self.assertRaises(InitDataError):
            verify_webapp_init_data(raw, token, max_age_seconds=3600)


class SignatureTests(unittest.TestCase):
    def test_order_and_device(self):
        with patch("services.callback_signatures.config_rates") as cfg:
            cfg.CALLBACK_SECRET = "test-secret-key"
            s = sign_order("OID1")
            self.assertTrue(verify_order_signature("OID1", s))
            self.assertFalse(verify_order_signature("OID1", "0" * 32))
            ds = sign_device_review(7)
            self.assertTrue(verify_device_review_signature(7, ds))


class PromptTests(unittest.TestCase):
    def test_legacy_bill_when_flag_off(self):
        with patch.dict("os.environ", {"WEBAPP_REQUISITES": "0"}, clear=False):
            self.assertFalse(webapp_requisites_enabled())
            html = format_buy_payment_html(
                {
                    "order_id": "OID",
                    "fiat_amount": 1000,
                    "crypto": "btc",
                    "payment_snapshot": {
                        "bill": {"bank": "Tinkoff", "reciver": "7900", "fio": "Ivan"}
                    },
                },
                include_legacy_bill=True,
            )
            self.assertIn("7900", html)
            self.assertIn("Tinkoff", html)
            self.assertIn("Уралсиба", html)
            self.assertIn("МТС Банка", html)

    def test_webapp_mode_hides_bill(self):
        now = datetime.now(timezone.utc)
        html = format_buy_payment_html(
            {
                "order_id": "OID",
                "fiat_amount": 1000,
                "crypto": "btc",
                "expires_at": (now + timedelta(minutes=8)).isoformat(),
                "payment_snapshot": {
                    "bill": {"bank": "Tinkoff", "reciver": "7900", "fio": "Ivan"}
                },
            },
            include_legacy_bill=False,
        )
        self.assertNotIn("7900", html)
        self.assertIn("Открыть реквизиты", html)
        self.assertIn("8", html)

    def test_webapp_url_has_sig(self):
        with patch("services.callback_signatures.config_rates") as cfg:
            cfg.CALLBACK_SECRET = "test-secret-key"
            url = requisites_webapp_url("OID99")
            self.assertIn("order_id=OID99", url)
            self.assertIn("sig=", url)


class RequisitesDeadlineTests(unittest.TestCase):
    def test_closes_only_new_payfast_order_after_internal_deadline(self):
        from services.webapp_requisites import _payfast_requisites_closed

        now = datetime.now(timezone.utc)
        closed, remaining = _payfast_requisites_closed(
            {
                "expires_at": now - timedelta(seconds=1),
                "required_receipt_type": 2,
            },
            {"merchant_expires_at": (now + timedelta(minutes=7)).isoformat()},
        )

        self.assertTrue(closed)
        self.assertIsNotNone(remaining)
        self.assertGreater(remaining, 0)

    def test_recheck_video_is_not_blocked_by_initial_deadline(self):
        from services.webapp_requisites import _payfast_requisites_closed

        now = datetime.now(timezone.utc)
        closed, remaining = _payfast_requisites_closed(
            {
                "expires_at": now - timedelta(seconds=1),
                "required_receipt_type": 3,
            },
            {"merchant_expires_at": (now + timedelta(minutes=7)).isoformat()},
        )

        self.assertFalse(closed)
        self.assertIsNone(remaining)

    def test_closed_message_is_plain_text(self):
        from services.webapp_requisites import _requisites_closed_message

        message = _requisites_closed_message(7 * 60)
        self.assertIn("Реквизиты закрыты", message)
        self.assertIn("7", message)
        self.assertNotIn("<b>", message)


class CancelPayinSafeTests(unittest.IsolatedAsyncioTestCase):
    async def test_refuses_completed(self):
        from services.merchant_api_helpers import cancel_payin_safe

        with patch(
            "services.db.get_order",
            AsyncMock(return_value={"order_id": "O1", "status": "COMPLETED"}),
        ):
            out = await cancel_payin_safe({"order_id": "O1", "status": "CREATED"})
        self.assertTrue(out["refused"])
        self.assertFalse(out.get("merchant_ok"))


if __name__ == "__main__":
    unittest.main()
