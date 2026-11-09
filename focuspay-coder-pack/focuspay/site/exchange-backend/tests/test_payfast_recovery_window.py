"""Регрессии разделённых сроков PayFast для веб-заявок."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _buy_row(*, expires_at: datetime, merchant_expires_at: datetime, **overrides):
    row = {
        "order_id": "PF-1",
        "user_id": 7,
        "status": "CREATED",
        "direction": "buy",
        "crypto": "USDT_TRC20",
        "crypto_amount": 10,
        "fiat_amount": 1000,
        "rate": 100,
        "requisites": "wallet",
        "created_at": NOW,
        "expires_at": expires_at,
        "payment_snapshot": {
            "bill": {"reciver": "79990000000"},
            "merchant_expires_at": merchant_expires_at.isoformat(),
        },
        "required_receipt_type": None,
    }
    row.update(overrides)
    return row


class PayfastDeadlineTests(unittest.TestCase):
    def test_fallback_keeps_seven_minute_recovery_window(self):
        from buy_order_web import _payfast_deadlines

        deadlines = _payfast_deadlines({}, now=NOW)

        self.assertEqual(deadlines.merchant_expires_at, NOW + timedelta(minutes=20))
        self.assertEqual(deadlines.requisites_expires_at, NOW + timedelta(minutes=13))
        self.assertFalse(deadlines.merchant_deadline_from_provider)
        self.assertFalse(deadlines.merchant_window_too_short)

    def test_provider_deadline_has_seven_minute_recovery_window(self):
        from buy_order_web import _payfast_deadlines

        deadlines = _payfast_deadlines(
            {"dateEnd": (NOW + timedelta(minutes=20)).isoformat()}, now=NOW
        )

        self.assertEqual(deadlines.merchant_expires_at, NOW + timedelta(minutes=20))
        self.assertEqual(deadlines.requisites_expires_at, NOW + timedelta(minutes=13))
        self.assertTrue(deadlines.merchant_deadline_from_provider)
        self.assertFalse(deadlines.merchant_window_too_short)

    def test_provider_deadline_at_seven_minutes_is_too_short(self):
        from buy_order_web import _payfast_deadlines

        deadlines = _payfast_deadlines(
            {"data_order": {"dateEnd": (NOW + timedelta(minutes=7)).isoformat()}},
            now=NOW,
        )

        self.assertTrue(deadlines.merchant_window_too_short)


class PayfastRequisitesVisibilityTests(unittest.IsolatedAsyncioTestCase):
    def test_requisites_close_at_internal_deadline(self):
        from order_service import payfast_requisites_are_closed

        row = _buy_row(
            expires_at=NOW - timedelta(seconds=1),
            merchant_expires_at=NOW + timedelta(minutes=6),
        )

        self.assertTrue(payfast_requisites_are_closed(row, now=NOW))

    def test_recheck_receipt_remains_available_after_internal_deadline(self):
        from order_service import payfast_requisites_are_closed

        row = _buy_row(
            expires_at=NOW - timedelta(seconds=1),
            merchant_expires_at=NOW + timedelta(minutes=6),
            required_receipt_type=3,
        )

        self.assertFalse(payfast_requisites_are_closed(row, now=NOW))

    def test_cancel_is_locked_during_recovery_window(self):
        from order_service import payfast_cancellation_is_locked

        row = _buy_row(
            expires_at=NOW - timedelta(seconds=1),
            merchant_expires_at=NOW + timedelta(minutes=6),
        )

        self.assertTrue(payfast_cancellation_is_locked(row, now=NOW))

    def test_cancel_is_locked_for_video_recheck(self):
        from order_service import payfast_cancellation_is_locked

        row = _buy_row(
            expires_at=NOW + timedelta(minutes=5),
            merchant_expires_at=NOW + timedelta(minutes=12),
            required_receipt_type=3,
        )

        self.assertTrue(payfast_cancellation_is_locked(row, now=NOW))

    def test_cancel_remains_available_before_recovery_window(self):
        from order_service import payfast_cancellation_is_locked

        row = _buy_row(
            expires_at=NOW + timedelta(minutes=1),
            merchant_expires_at=NOW + timedelta(minutes=8),
        )

        self.assertFalse(payfast_cancellation_is_locked(row, now=NOW))

    async def test_active_order_hides_payment_after_internal_deadline(self):
        from order_service import get_active_web_order

        now = datetime.now(timezone.utc)
        row = _buy_row(
            expires_at=now - timedelta(seconds=1),
            merchant_expires_at=now + timedelta(minutes=6),
        )
        with patch("order_service._get_active_order", new=AsyncMock(return_value=row)):
            result = await get_active_web_order(7)

        self.assertTrue(result["requisites_closed"])
        self.assertIsNone(result["payment"])
        self.assertEqual(result["merchant_expires_at"], row["payment_snapshot"]["merchant_expires_at"])


class OperatorBuyMessageTests(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "order_id": "22226692",
            "user_id": 7,
            "status": "OPERATOR_PENDING",
            "direction": "buy",
            "crypto": "BTC",
            "crypto_amount": 0.00071133,
            "fiat_amount": 6301,
            "rate": 8857474,
            "requisites": "bc1qexamplewallet",
            "created_at": NOW,
            "expires_at": NOW + timedelta(hours=24),
            "payment_snapshot": None,
            "required_receipt_type": None,
            "sub_token": "SBPRUB",
            "merchant_id": None,
            "payout_tx_hash": None,
        }
        row.update(overrides)
        return row

    def test_message_names_operator_and_order(self):
        from order_service import buy_without_requisites_message

        text = buy_without_requisites_message("22226692")

        self.assertIn("@focus_operator", text)
        self.assertIn("#22226692", text)
        self.assertIn("попробуем что-нибудь придумать", text)
        self.assertNotIn("минимум", text)

    def test_pending_buy_without_bill_points_to_operator(self):
        from order_service import _attach_buy_operator_message, _order_response, buy_payment_for_active_row

        row = self._row()
        payment = buy_payment_for_active_row(row)
        out = _attach_buy_operator_message(_order_response(row, payment=payment), row, payment)

        self.assertEqual(payment["type"], "operator")
        self.assertEqual(out["operator_message"], payment["message"])
        self.assertIn("#22226692", out["operator_message"])

    def test_pending_buy_with_bill_keeps_requisites(self):
        from order_service import buy_payment_for_active_row

        row = self._row(payment_snapshot={"bill": {"reciver": "79990000000", "bank": "Сбер"}})
        payment = buy_payment_for_active_row(row)

        self.assertEqual(payment["type"], "buy")
        self.assertEqual(payment["bill"]["reciver"], "79990000000")


class OperatorBuyActiveOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_order_keeps_operator_message(self):
        from order_service import get_active_web_order

        row = OperatorBuyMessageTests()._row()
        with patch("order_service._get_active_order", new=AsyncMock(return_value=row)):
            result = await get_active_web_order(7)

        self.assertEqual(result["payment"]["type"], "operator")
        self.assertEqual(result["operator_message"], result["payment"]["message"])
        self.assertIn("Реквизитов сейчас нет", result["operator_message"])


if __name__ == "__main__":
    unittest.main()
