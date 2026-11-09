"""HMAC API внештатника: подпись, допуск часов, replay, fingerprint, expires_at."""
from __future__ import annotations

import asyncio
import time
import unittest
from datetime import datetime, timedelta, timezone

from exchanger_deal_callback import callback_payload
from exchanger_hmac import (
    ReplayCache,
    replay_key,
    sign_body,
    timestamp_fresh,
    verify_signature,
)
from external_deal_payin import deal_public_out, payin_user_id
from external_deal_timing import (
    EXTERNAL_DEAL_CLIENT_PAY_MIN,
    default_deal_expires_at,
    resolve_deal_expires_at,
)


class HmacSignTests(unittest.TestCase):
    def test_sign_matches_verify(self):
        secret = "s3cret"
        ts = "1710000000"
        body = '{"amount_rub":1000}'
        sig = sign_body(secret, ts, body)
        self.assertTrue(verify_signature(secret, ts, body, sig))
        self.assertFalse(verify_signature(secret, ts, body, "0" * 64))
        self.assertFalse(verify_signature(secret, ts, "{}", sig))

    def test_timestamp_skew(self):
        now = 1_710_000_000
        self.assertTrue(timestamp_fresh(str(now), now=now))
        self.assertTrue(timestamp_fresh(str(now - 300), now=now))
        self.assertFalse(timestamp_fresh(str(now - 301), now=now))
        self.assertFalse(timestamp_fresh("nope", now=now))

    def test_replay_same_timestamp_and_body(self):
        cache = ReplayCache(ttl_sec=300)
        now = time.time()
        key = replay_key("ak", "100", '{"a":1}')
        self.assertFalse(cache.seen_or_add(key, now=now))
        self.assertTrue(cache.seen_or_add(key, now=now))
        other = replay_key("ak", "101", '{"a":1}')
        self.assertFalse(cache.seen_or_add(other, now=now))


class PayinFingerprintTests(unittest.TestCase):
    def test_shop_fallback_is_negative_exchanger_id(self):
        self.assertEqual(payin_user_id(42), -42)
        self.assertEqual(payin_user_id(42, "  "), -42)

    def test_customer_fingerprint_not_shop_id(self):
        a = payin_user_id(42, "buyer-1")
        b = payin_user_id(42, "buyer-2")
        self.assertNotEqual(a, -42)
        self.assertNotEqual(a, b)
        self.assertEqual(a, payin_user_id(42, "buyer-1"))
        self.assertGreater(a, 0)


class ExpiresAtTests(unittest.TestCase):
    def test_default_is_20_minutes(self):
        now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        got = default_deal_expires_at(now)
        self.assertEqual(got, now + timedelta(minutes=EXTERNAL_DEAL_CLIENT_PAY_MIN))

    def test_merchant_date_end_wins(self):
        end = "2026-08-20T12:20:00Z"
        got = resolve_deal_expires_at({"dateEnd": end})
        self.assertEqual(got.isoformat(), "2026-08-20T12:20:00+00:00")

    def test_nested_data_order_date_end(self):
        got = resolve_deal_expires_at({"data_order": {"dateEnd": "2026-08-20T12:30:00Z"}})
        self.assertEqual(got.isoformat(), "2026-08-20T12:30:00+00:00")

    def test_bad_date_end_falls_back(self):
        now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        got = resolve_deal_expires_at({"dateEnd": "nope"}, now=now)
        self.assertEqual(got, now + timedelta(minutes=20))


class CallbackPayloadTests(unittest.TestCase):
    def test_credited_fields(self):
        payload = callback_payload(
            {
                "id": 9,
                "status": "confirmed",
                "client_transaction_id": "shop-1",
                "amount_rub": 1000,
                "client_pays_rub": 1150,
                "principal_usdt": 12.3,
                "expires_at": None,
            },
            "credited",
        )
        self.assertEqual(payload["event"], "credited")
        self.assertEqual(payload["event_id"], "ext-9-credited")
        self.assertEqual(payload["deal_id"], 9)
        self.assertEqual(payload["client_transaction_id"], "shop-1")
        self.assertEqual(payload["client_pays_rub"], 1150.0)


class CabinetApiKeyPolicyTests(unittest.TestCase):
    def test_cabinet_router_cannot_issue_or_revoke(self):
        from pathlib import Path

        from exchanger_api_keys import ADMIN_ONLY_API_KEY_DETAIL

        src = (Path(__file__).resolve().parents[1] / "routers" / "exchanger.py").read_text()
        self.assertIn("ADMIN_ONLY_API_KEY_DETAIL", src)
        self.assertNotIn("issue_key_for_exchanger", src)
        self.assertNotIn("revoke_key_for_exchanger", src)
        admin_src = (Path(__file__).resolve().parents[1] / "routers" / "admin_external.py").read_text()
        self.assertIn("issue_key_for_exchanger", admin_src)
        self.assertIn("revoke_key_for_exchanger", admin_src)
        self.assertIn("администратор площадки", ADMIN_ONLY_API_KEY_DETAIL)

    def test_cabinet_handlers_return_403(self):
        try:
            from fastapi import HTTPException

            from exchanger_api_keys import ADMIN_ONLY_API_KEY_DETAIL
            from routers.exchanger import api_keys_issue, api_keys_revoke
        except ModuleNotFoundError as e:
            self.skipTest(f"missing dependency: {e}")

        owner = {"external_exchanger_id": 1}
        for handler in (api_keys_issue, api_keys_revoke):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(handler(_exchanger=owner))
            self.assertEqual(ctx.exception.status_code, 403)
            self.assertEqual(ctx.exception.detail, ADMIN_ONLY_API_KEY_DETAIL)


class DealPublicOutExpiresTests(unittest.TestCase):
    def test_expires_at_and_client_tx(self):
        out = deal_public_out(
            {
                "id": 7,
                "status": "awaiting_receipt",
                "amount_rub": 1000,
                "client_pays_rub": 1150,
                "principal_usdt": 12.0,
                "expires_at": "2026-08-20T12:00:00+00:00",
                "client_transaction_id": "shop-1",
            }
        )
        self.assertEqual(out["expires_at"], "2026-08-20T12:00:00+00:00")
        self.assertEqual(out["client_transaction_id"], "shop-1")
        self.assertTrue(out["can_confirm_paid"])


class HmacDealCreateBodyTests(unittest.TestCase):
    def test_amount_crypto_ok(self):
        try:
            from pydantic import ValidationError
            from routers.exchanger_v1 import DealCreateBody
        except ModuleNotFoundError as e:
            self.skipTest(f"missing dependency: {e}")
        body = DealCreateBody(amount_crypto=1.5243, crypto="ltc")
        self.assertEqual(body.amount_crypto, 1.5243)
        self.assertIsNone(body.amount_rub)
        with self.assertRaises(ValidationError):
            DealCreateBody(sub_token="SBPRUB")


class HmacCancelRouteTests(unittest.TestCase):
    def test_cancel_route_registered(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "routers" / "exchanger_v1.py").read_text()
        self.assertIn('@router.post("/deals/{deal_id}/cancel")', src)
        self.assertIn("cancel_cabinet_deal", src)
        try:
            from routers.exchanger_v1 import router
        except ModuleNotFoundError:
            return
        found = any(
            getattr(route, "path", "") == "/deals/{deal_id}/cancel"
            and "POST" in (getattr(route, "methods", set()) or set())
            for route in router.routes
        )
        self.assertTrue(found, "POST /deals/{deal_id}/cancel missing on HMAC router")


class ClientStatParseTests(unittest.TestCase):
    def test_strips_pii_and_computes_conversion(self):
        from external_client_stat import coerce_client_stat_payload, deal_status_as_order

        got = coerce_client_stat_payload(
            {
                "paid_orders": 7,
                "buy_paid": 7,
                "buy_failed": 3,
                "turnover_rub": 84500,
                "telegram": "@secret",
                "fio": "Иван",
            }
        )
        self.assertIsNotNone(got)
        self.assertEqual(got["conversion_pct"], 70.0)
        self.assertEqual(got["total_orders"], 10)
        self.assertNotIn("telegram", got)
        self.assertNotIn("fio", got)
        self.assertEqual(deal_status_as_order("confirmed"), "PAID")
        self.assertEqual(deal_status_as_order("awaiting_receipt"), "PENDING")
        self.assertEqual(deal_status_as_order("pending"), "AWAITING_CHECK")

    def test_check_out_looks_like_order(self):
        from external_client_stat import check_public_out

        out = check_public_out(
            {
                "id": 12,
                "status": "confirmed",
                "client_pays_rub": 12000,
                "crypto": "usdt",
                "customer_fingerprint": "buyer-42",
            },
            {
                "paid_orders": 7,
                "buy_paid": 7,
                "buy_failed": 3,
                "turnover_rub": 84500,
            },
        )
        self.assertEqual(out["status"], "PAID")
        self.assertEqual(out["paid_orders"], 7)
        self.assertEqual(out["conversion_pct"], 70.0)
        self.assertNotIn("exchanger", str(out).lower())

    def test_client_stat_routes_registered(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "routers" / "exchanger_v1.py").read_text()
        self.assertIn('@router.post("/deals/{deal_id}/client-stat")', src)
        self.assertIn('@router.post("/clients/stat")', src)
        self.assertIn('@router.get("/deals/{deal_id}/check")', src)
        try:
            from routers.exchanger_v1 import DealCreateBody, router
        except ModuleNotFoundError:
            return
        paths = {(getattr(r, "path", ""), tuple(sorted(getattr(r, "methods", set()) or set()))) for r in router.routes}
        self.assertIn(("/deals/{deal_id}/client-stat", ("POST",)), paths)
        self.assertIn(("/clients/stat", ("POST",)), paths)
        self.assertIn(("/deals/{deal_id}/check", ("GET",)), paths)
        body = DealCreateBody(amount_rub=1000, client_stat={"paid_orders": 1})
        self.assertEqual(body.client_stat["paid_orders"], 1)


if __name__ == "__main__":
    unittest.main()
