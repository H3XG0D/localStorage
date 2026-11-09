"""Тесты guard Payfast перед COMPLETED/выплатой."""
import unittest
from unittest.mock import AsyncMock, patch

from services.payfast_payin_guard import (
    is_payfast_failure_status,
    is_payfast_settled,
    is_webhook_payment_failure,
    payfast_block_message,
    payfast_amount_from_payload,
    payfast_status_from_payload,
    verify_payfast_ready_for_payout,
)
from services.webhook_security import is_payment_success_payload


class PayfastSettledTests(unittest.TestCase):
    def test_succses_is_settled(self):
        self.assertTrue(is_payfast_settled("SUCCSES", None))
        self.assertTrue(is_payfast_settled("SUCCESS", 1))
        self.assertTrue(is_payfast_settled("COMPLETED", 0))

    def test_paid_is_never_settled(self):
        """Инцидент 2026-09-10: PAID+file=0 закрывал BUY до апрува трейдера."""
        self.assertFalse(is_payfast_settled("PAID", 0))
        self.assertFalse(is_payfast_settled("PAID", 1))
        self.assertFalse(is_payfast_settled("PAID", None))

    def test_accepted_with_status_check_not_settled(self):
        self.assertFalse(is_payfast_settled("ACCEPTED", 1))

    def test_error_not_settled(self):
        self.assertFalse(is_payfast_settled("ERROR", 0))


class PayfastStatusParseTests(unittest.TestCase):
    def test_status_from_nested_data_order(self):
        payload = {"data_order": {"status": "ERROR", "status_check": 1}}
        self.assertEqual(payfast_status_from_payload(payload), "ERROR")

    def test_amount_from_live_response_containers(self):
        self.assertEqual(payfast_amount_from_payload({"amount": "1000"}), "1000")
        self.assertEqual(
            payfast_amount_from_payload({"data_order": {"amount": 1001}}), 1001
        )
        self.assertEqual(
            payfast_amount_from_payload({"order": {"amount": "1002"}}), "1002"
        )
        self.assertEqual(
            payfast_amount_from_payload({"body": {"amount": "1003"}}), "1003"
        )
        self.assertIsNone(payfast_amount_from_payload({"data_order": {}}))

    def test_failure_detection(self):
        self.assertTrue(is_payfast_failure_status("ERROR"))
        self.assertTrue(is_webhook_payment_failure("CANCELED"))
        self.assertFalse(is_payfast_failure_status("ACCEPTED"))


class PayfastSuccessPayloadTests(unittest.TestCase):
    def test_error_never_success(self):
        self.assertFalse(is_payment_success_payload("ERROR", None, 1))
        self.assertFalse(is_payment_success_payload("ERROR", "ok", 1))
        self.assertFalse(is_payment_success_payload("CANCELED", None, 1))

    def test_buy_only_succses_is_success(self):
        self.assertTrue(
            is_payment_success_payload("SUCCSES", None, None, "buy")
        )
        self.assertFalse(
            is_payment_success_payload("PAID", None, None, "buy", status_file=0)
        )
        self.assertFalse(
            is_payment_success_payload("PAID", None, None, "buy", status_file=1)
        )

    def test_buy_succses_overrides_recheck_status(self):
        for status_check in (2, 3, 4, "2", "3", "4"):
            with self.subTest(status_check=status_check):
                self.assertTrue(
                    is_payment_success_payload("SUCCSES", None, status_check, "buy")
                )

    def test_buy_accepted_status_check_not_success(self):
        self.assertFalse(
            is_payment_success_payload("ACCEPTED", "ok", 1, "buy")
        )


class PayfastBlockMessageTests(unittest.TestCase):
    def test_error_status_message(self):
        msg = payfast_block_message("payfast_status_error")
        self.assertIn("ERROR", msg)
        self.assertIn("запрещена", msg.lower())

    def test_check_pending_message(self):
        msg = payfast_block_message("payfast_check_pending")
        self.assertIn("status_file", msg)

    def test_awaiting_trader_message(self):
        msg = payfast_block_message("payfast_awaiting_trader")
        self.assertIn("SUCCSES", msg)


class VerifyPayfastPayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_skip_non_payfast_buy(self):
        ok, err, resp = await verify_payfast_ready_for_payout(
            {"direction": "buy", "order_id": "1"}
        )
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertIsNone(resp)

    async def test_blocks_error_status(self):
        order = {
            "direction": "buy",
            "order_id": "19632531",
            "merchant_order_id": "742d71f4-1375-4fbb-b46d-7b5547752172",
        }
        with patch(
            "services.merchant_client.get_merchant_order",
            new_callable=AsyncMock,
            return_value={"status": "ERROR", "status_check": 1},
        ):
            ok, err, _ = await verify_payfast_ready_for_payout(order)
        self.assertFalse(ok)
        self.assertEqual(err, "payfast_status_error")

    async def test_allows_succses(self):
        order = {
            "direction": "buy",
            "order_id": "1",
            "merchant_order_id": "uuid-ok",
        }
        with patch(
            "services.merchant_client.get_merchant_order",
            new_callable=AsyncMock,
            return_value={"status": "SUCCSES"},
        ):
            ok, err, _ = await verify_payfast_ready_for_payout(order)
        self.assertTrue(ok)
        self.assertIsNone(err)

    async def test_blocks_paid_file_accepted_until_succses(self):
        order = {
            "direction": "buy",
            "order_id": "1",
            "merchant_order_id": "uuid-paid",
        }
        with patch(
            "services.merchant_client.get_merchant_order",
            new_callable=AsyncMock,
            return_value={"status": "PAID", "status_file": 0},
        ):
            ok, err, _ = await verify_payfast_ready_for_payout(order)
        self.assertFalse(ok)
        self.assertEqual(err, "payfast_awaiting_trader")

    async def test_blocks_accepted_status_check(self):
        order = {
            "direction": "buy",
            "order_id": "1",
            "merchant_order_id": "uuid-pending",
        }
        with patch(
            "services.merchant_client.get_merchant_order",
            new_callable=AsyncMock,
            return_value={"status": "ACCEPTED", "status_check": 1},
        ):
            ok, err, _ = await verify_payfast_ready_for_payout(order)
        self.assertFalse(ok)
        self.assertEqual(err, "payfast_not_paid")

    async def test_blocks_paid_file_pending(self):
        order = {
            "direction": "buy",
            "order_id": "1",
            "merchant_order_id": "uuid-check",
        }
        with patch(
            "services.merchant_client.get_merchant_order",
            new_callable=AsyncMock,
            return_value={"status": "PAID", "status_file": 1},
        ):
            ok, err, _ = await verify_payfast_ready_for_payout(order)
        self.assertFalse(ok)
        self.assertEqual(err, "payfast_check_pending")

    async def test_require_uuid_fail_closed(self):
        order = {"direction": "buy", "order_id": "19632531"}
        ok, err, _ = await verify_payfast_ready_for_payout(order, require_uuid=True)
        self.assertFalse(ok)
        self.assertEqual(err, "payfast_uuid_missing")

    async def test_no_require_uuid_skips(self):
        order = {"direction": "buy", "order_id": "1"}
        ok, err, _ = await verify_payfast_ready_for_payout(order)
        self.assertTrue(ok)
        self.assertIsNone(err)


class VerifyPayfastCompleteTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_fail_closed_without_uuid(self):
        from services.payfast_payin_guard import verify_payfast_ready_for_complete

        order = {"direction": "buy", "order_id": "1"}
        ok, err, _ = await verify_payfast_ready_for_complete(order, {"status": "ACCEPTED"})
        self.assertFalse(ok)
        self.assertEqual(err, "payfast_uuid_missing")

    async def test_complete_rejects_error_webhook(self):
        from services.payfast_payin_guard import verify_payfast_ready_for_complete

        order = {"direction": "buy", "order_id": "1", "merchant_order_id": "u-1"}
        ok, err, _ = await verify_payfast_ready_for_complete(order, {"status": "ERROR"})
        self.assertFalse(ok)
        self.assertEqual(err, "webhook_status_error")


if __name__ == "__main__":
    unittest.main()
