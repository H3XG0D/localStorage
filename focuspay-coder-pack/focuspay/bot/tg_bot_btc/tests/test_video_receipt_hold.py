"""Тесты удержания выплаты крипты при запросе видео после COMPLETED."""
import unittest
from unittest.mock import AsyncMock, patch

from services.order_transitions import allowed_status_transition
from services.video_receipt_request import request_client_receipt_check


class TransitionTests(unittest.TestCase):
    def test_completed_to_awaiting_check_allowed(self):
        self.assertTrue(
            allowed_status_transition("COMPLETED", "AWAITING_CHECK", direction="buy")
        )

    def test_completed_to_paid_still_allowed(self):
        self.assertTrue(
            allowed_status_transition("COMPLETED", "PAID", direction="buy")
        )


class VideoHoldRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_request_on_completed_puts_on_hold(self):
        order = {
            "order_id": "O1",
            "direction": "buy",
            "status": "COMPLETED",
            "user_id": 42,
        }
        with patch(
            "services.video_receipt_request.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.video_receipt_request.mark_ops_alert_once",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.video_receipt_request.update_order_to_awaiting_check",
            new=AsyncMock(return_value=True),
        ) as upd, patch(
            "services.db.clear_ops_alert_once",
            new=AsyncMock(),
        ) as clear, patch(
            "services.order_ops_notify.notify_ops_order",
            new=AsyncMock(),
        ) as notify_ops, patch(
            "services.video_receipt_request._notify_user",
            new=AsyncMock(),
        ) as notify_user:
            ok, reason = await request_client_receipt_check(
                "O1", 3, source="appeals", allow_late=False
            )

        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        upd.assert_awaited_once_with("O1", 3)
        clear.assert_awaited_once_with("O1", "merchant_confirmed_notify")
        notify_user.assert_awaited_once()

        args, kwargs = notify_ops.call_args
        self.assertEqual(args[0], "video_requested")
        self.assertIn("УДЕРЖАНИИ", kwargs.get("note", ""))

    async def test_paid_still_blocked(self):
        order = {
            "order_id": "O2",
            "direction": "buy",
            "status": "PAID",
            "user_id": 42,
        }
        with patch(
            "services.video_receipt_request.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.video_receipt_request.mark_ops_alert_once",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.video_receipt_request.update_order_to_awaiting_check",
            new=AsyncMock(return_value=True),
        ) as upd, patch(
            "services.order_ops_notify.notify_ops_order",
            new=AsyncMock(),
        ):
            ok, reason = await request_client_receipt_check(
                "O2", 3, source="appeals", allow_late=False
            )

        self.assertFalse(ok)
        self.assertIn("status_blocked", reason)
        upd.assert_not_awaited()

    async def test_skips_rollback_when_video_already_submitted(self):
        """Повторный recheck не откатывает PENDING, если mp4 уже на заявке."""
        order = {
            "order_id": "O3",
            "direction": "buy",
            "status": "PENDING",
            "user_id": 42,
            "required_receipt_type": 3,
            "receipt_file": "clip.mp4",
        }
        with patch(
            "services.video_receipt_request.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.video_receipt_request.update_order_to_awaiting_check",
            new=AsyncMock(return_value=True),
        ) as upd, patch(
            "services.video_receipt_request.mark_ops_alert_once",
            new=AsyncMock(return_value=True),
        ) as mark:
            ok, reason = await request_client_receipt_check(
                "O3", 3, source="reconciler"
            )
        self.assertTrue(ok)
        self.assertEqual(reason, "video_already_submitted")
        upd.assert_not_awaited()
        mark.assert_not_awaited()

    async def test_still_requests_video_when_only_old_pdf(self):
        order = {
            "order_id": "O4",
            "direction": "buy",
            "status": "PENDING",
            "user_id": 42,
            "receipt_file": "old.pdf",
        }
        with patch(
            "services.video_receipt_request.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.video_receipt_request.mark_ops_alert_once",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.video_receipt_request.update_order_to_awaiting_check",
            new=AsyncMock(return_value=True),
        ) as upd, patch(
            "services.db.merge_order_payment_snapshot",
            new=AsyncMock(),
        ), patch(
            "services.order_ops_notify.notify_ops_order",
            new=AsyncMock(),
        ), patch(
            "services.video_receipt_request._notify_user",
            new=AsyncMock(),
        ):
            ok, reason = await request_client_receipt_check(
                "O4", 3, source="reconciler"
            )
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        upd.assert_awaited_once_with("O4", 3)


if __name__ == "__main__":
    unittest.main()
