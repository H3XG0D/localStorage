"""Тесты обработки Payfast recheck (видео/PDF) и продления expires_at."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from services.payfast_payin_guard import (
    handle_payfast_recheck,
    is_payfast_appeal_active,
    keep_order_alive_for_payfast_review,
    payfast_date_end_appeal_from_payload,
    payfast_recheck_req_type,
)


class PayfastRecheckParseTests(unittest.TestCase):
    def test_date_end_appeal_parses_utc(self):
        payload = {"dateEndAppeal": "2026-07-10T12:54:52.000Z"}
        dt = payfast_date_end_appeal_from_payload(payload)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_recheck_req_type_video(self):
        self.assertEqual(payfast_recheck_req_type(3), 3)
        self.assertEqual(payfast_recheck_req_type("3"), 3)

    def test_recheck_req_type_always_video(self):
        # Payfast 2/4 = повторный PDF / неизвестно — у нас всё равно видео
        self.assertEqual(payfast_recheck_req_type(2), 3)
        self.assertEqual(payfast_recheck_req_type(4), 3)
        self.assertEqual(payfast_recheck_req_type("2"), 3)


class PayfastAppealActiveTests(unittest.TestCase):
    def test_active_when_future_appeal_end(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        payload = {"status_check": 3, "dateEndAppeal": future}
        self.assertTrue(is_payfast_appeal_active(payload))

    def test_inactive_when_appeal_ended(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        payload = {"status_check": 3, "dateEndAppeal": past}
        self.assertFalse(is_payfast_appeal_active(payload))

    def test_active_without_appeal_end(self):
        self.assertTrue(is_payfast_appeal_active({"status_check": 3}))


class HandlePayfastRecheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_requests_video_and_extends_expires(self):
        order = {"order_id": "11580117", "direction": "buy", "status": "PENDING"}
        future = (datetime.now(timezone.utc) + timedelta(minutes=20)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        api_resp = {"status": "PAID", "status_check": 3, "dateEndAppeal": future}
        with patch(
            "services.db.extend_order_expires_at",
            new=AsyncMock(),
        ) as extend, patch(
            "services.video_receipt_request.request_client_receipt_check",
            new=AsyncMock(return_value=(True, "ok")),
        ) as req:
            ok, reason = await handle_payfast_recheck(
                order, api_resp, source="reconciler"
            )
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        extend.assert_awaited_once()
        req.assert_awaited_once_with(
            "11580117", 3, bot=None, source="reconciler"
        )

    async def test_skips_when_appeal_ended(self):
        order = {"order_id": "1", "direction": "buy"}
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        api_resp = {"status": "PAID", "status_check": 3, "dateEndAppeal": past}
        with patch(
            "services.db.extend_order_expires_at",
            new=AsyncMock(),
        ) as extend, patch(
            "services.video_receipt_request.request_client_receipt_check",
            new=AsyncMock(),
        ) as req:
            ok, reason = await handle_payfast_recheck(order, api_resp)
        self.assertFalse(ok)
        self.assertEqual(reason, "appeal_ended")
        extend.assert_not_awaited()
        req.assert_not_awaited()


class KeepAliveCheckPendingTests(unittest.IsolatedAsyncioTestCase):
    async def test_extends_expires_for_check_pending(self):
        order = {"order_id": "O1", "direction": "buy", "status": "PENDING"}
        api_resp = {"status": "PAID", "status_file": 1}
        with patch(
            "services.db.extend_order_expires_at",
            new=AsyncMock(),
        ) as extend:
            ok = await keep_order_alive_for_payfast_review(
                order, api_resp, pf_err="payfast_check_pending", source="expirer"
            )
        self.assertTrue(ok)
        extend.assert_awaited_once()

    async def test_extends_expires_for_awaiting_trader(self):
        order = {"order_id": "O1", "direction": "buy", "status": "PENDING"}
        api_resp = {"status": "PAID", "status_file": 0}
        with patch(
            "services.db.extend_order_expires_at",
            new=AsyncMock(),
        ) as extend:
            ok = await keep_order_alive_for_payfast_review(
                order, api_resp, pf_err="payfast_awaiting_trader", source="reconciler"
            )
        self.assertTrue(ok)
        extend.assert_awaited_once()

    async def test_ignores_other_errors(self):
        order = {"order_id": "O1"}
        with patch("services.db.extend_order_expires_at", new=AsyncMock()) as extend:
            ok = await keep_order_alive_for_payfast_review(
                order, {}, pf_err="payfast_not_paid"
            )
        self.assertFalse(ok)
        extend.assert_not_awaited()


class WebhookRecheckTests(unittest.TestCase):
    def test_status_check_uses_handle_payfast_recheck(self):
        from fastapi.testclient import TestClient

        order = {
            "order_id": "O1",
            "user_id": 555,
            "status": "PENDING",
            "direction": "buy",
        }
        with patch(
            "services.webhook_server.verify_webhook_client_ip", return_value=True
        ), patch(
            "services.webhook_server.verify_incoming_webhook", return_value=True
        ), patch(
            "services.webhook_server.get_order",
            new=AsyncMock(return_value=dict(order)),
        ), patch(
            "services.payfast_payin_guard.handle_payfast_recheck",
            new=AsyncMock(return_value=(True, "ok")),
        ) as handle:
            from services.webhook_server import app

            r = TestClient(app).post(
                "/callback",
                json={
                    "client_transaction_id": "O1",
                    "status": "PAID",
                    "status_check": 3,
                    "dateEndAppeal": "2026-07-10T12:54:52.000Z",
                },
            )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        handle.assert_awaited_once()


class PayfastReconcilerRecheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_triggers_recheck_handler(self):
        order = {"order_id": "O1", "status": "PENDING", "direction": "buy"}
        api_resp = {"status": "PAID", "status_check": 3}
        with patch(
            "services.payfast_order_reconciler.verify_payfast_ready_for_payout",
            new=AsyncMock(return_value=(False, "payfast_recheck_requested", api_resp)),
        ), patch(
            "services.payfast_order_reconciler.handle_payfast_recheck",
            new=AsyncMock(return_value=(True, "ok")),
        ) as handle, patch(
            "services.payfast_order_reconciler.complete_buy_from_payfast_settled",
            new=AsyncMock(),
        ) as complete:
            from services.payfast_order_reconciler import reconcile_one_order

            result = await reconcile_one_order(order)
        self.assertFalse(result)
        handle.assert_awaited_once()
        complete.assert_not_awaited()

    async def test_reconcile_keeps_alive_on_check_pending(self):
        order = {"order_id": "O1", "status": "PENDING", "direction": "buy"}
        api_resp = {"status": "PAID", "status_file": 1}
        with patch(
            "services.payfast_order_reconciler.verify_payfast_ready_for_payout",
            new=AsyncMock(return_value=(False, "payfast_check_pending", api_resp)),
        ), patch(
            "services.payfast_order_reconciler.keep_order_alive_for_payfast_review",
            new=AsyncMock(return_value=True),
        ) as keep, patch(
            "services.payfast_order_reconciler.complete_buy_from_payfast_settled",
            new=AsyncMock(),
        ) as complete:
            from services.payfast_order_reconciler import reconcile_one_order

            result = await reconcile_one_order(order)
        self.assertFalse(result)
        keep.assert_awaited_once()
        complete.assert_not_awaited()

    async def test_reconcile_keeps_alive_on_awaiting_trader(self):
        order = {"order_id": "O1", "status": "PENDING", "direction": "buy"}
        api_resp = {"status": "PAID", "status_file": 0}
        with patch(
            "services.payfast_order_reconciler.verify_payfast_ready_for_payout",
            new=AsyncMock(return_value=(False, "payfast_awaiting_trader", api_resp)),
        ), patch(
            "services.payfast_order_reconciler.keep_order_alive_for_payfast_review",
            new=AsyncMock(return_value=True),
        ) as keep, patch(
            "services.payfast_order_reconciler.complete_buy_from_payfast_settled",
            new=AsyncMock(),
        ) as complete:
            from services.payfast_order_reconciler import reconcile_one_order

            result = await reconcile_one_order(order)
        self.assertFalse(result)
        keep.assert_awaited_once()
        complete.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
