"""Продления заявки должны действовать: экспайрер не убивает ожидание чека/видео.

Регрессия с прода: дедлайн кандидатов читался из payment_snapshot.merchant_expires_at,
а продления писали только orders.expires_at — заявка умирала через 10 секунд после
запроса видео, хотя expires_at был на 11 часов вперёд.
"""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from services.order_expirer import _receipt_wait_deadline, expire_orders_task
from services.video_receipt_request import request_client_receipt_check

NOW = datetime.now(timezone.utc)


def _awaiting_video_order(**overrides) -> dict:
    order = {
        "order_id": "29638590",
        "user_id": 42,
        "direction": "buy",
        "status": "AWAITING_CHECK",
        "required_receipt_type": 3,
        "merchant_order_id": "37432abd-43ad-4542-8ed6-5c655c5f0a0e",
        "expires_at": NOW + timedelta(hours=11),
        "payment_snapshot": {
            "merchant_uuid": "37432abd-43ad-4542-8ed6-5c655c5f0a0e",
            "merchant_expires_at": (NOW - timedelta(minutes=11)).isoformat(),
            "receipt_requested_at": (NOW - timedelta(minutes=1)).isoformat(),
            "receipt_recheck_requested_at": (NOW - timedelta(minutes=1)).isoformat(),
        },
    }
    order.update(overrides)
    return order


class ExpiredCandidateQueryTests(unittest.IsolatedAsyncioTestCase):
    """Дедлайн кандидата — максимум из expires_at и окна мерчанта."""

    async def test_deadline_is_greatest_of_both_dates(self):
        from services.db import get_expired_orders

        captured = {}

        async def fetch(query, *args):
            captured["query"] = query
            return []

        conn = AsyncMock()
        conn.fetch = fetch
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("services.db.get_pool", new=AsyncMock(return_value=pool)):
            await get_expired_orders(limit=10)

        query = captured["query"]
        self.assertIn("GREATEST(", query)
        self.assertIn("expires_at", query)
        self.assertIn("merchant_expires_at", query)
        # Приоритет снапшота над expires_at обнулял любое продление.
        self.assertNotIn("COALESCE(\n                CASE", query)


class ReceiptWaitDeadlineTests(unittest.TestCase):
    def test_window_counted_from_recheck_request(self):
        with patch("services.config_rates.RECEIPT_WAIT_WINDOW_MINUTES", 1440):
            deadline = _receipt_wait_deadline(_awaiting_video_order())

        self.assertIsNotNone(deadline)
        self.assertAlmostEqual(
            (deadline - NOW).total_seconds(),
            timedelta(minutes=1439).total_seconds(),
            delta=5,
        )

    def test_no_window_without_recheck_marker(self):
        """Первичное «Я оплатил» истекает по таймеру оплаты, как и раньше."""
        order = _awaiting_video_order(required_receipt_type=2)
        order["payment_snapshot"].pop("receipt_recheck_requested_at")

        self.assertIsNone(_receipt_wait_deadline(order))

    def test_no_window_for_other_statuses(self):
        self.assertIsNone(_receipt_wait_deadline(_awaiting_video_order(status="PENDING")))


class ExpirerReceiptWaitTests(unittest.IsolatedAsyncioTestCase):
    async def _run_one_pass(
        self,
        order: dict,
        *,
        window_minutes: int,
        pf_result=(False, "payfast_not_paid", {}),
    ):
        """Один проход экспайрера по единственной заявке."""
        shutdown = asyncio.Event()
        passes = {"n": 0}

        async def expired_rows(limit=100):
            passes["n"] += 1
            if passes["n"] > 1:
                shutdown.set()
                return []
            return [{"order_id": order["order_id"], "user_id": order["user_id"]}]

        extend = AsyncMock()
        update_status = AsyncMock(return_value=True)
        notify_ops = AsyncMock()

        with patch(
            "services.order_expirer._send_payment_nudges", new=AsyncMock()
        ), patch(
            "services.order_expirer.release_orphan_balance_holds",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.order_expirer.get_expired_orders", new=expired_rows
        ), patch(
            "services.order_expirer.get_order", new=AsyncMock(return_value=order)
        ), patch(
            "services.order_expirer.update_order_status", new=update_status
        ), patch(
            "services.db.extend_order_expires_at", new=extend
        ), patch(
            "services.db.find_matching_paid_buy_payout",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.db.mark_ops_alert_once", new=AsyncMock(return_value=True)
        ), patch(
            "services.order_ops_notify.notify_ops_order", new=notify_ops
        ), patch(
            "services.payfast_payin_guard.verify_payfast_ready_for_payout",
            new=AsyncMock(return_value=pf_result),
        ), patch(
            "services.merchant_api_helpers.cancel_payin_for_order", new=AsyncMock()
        ), patch(
            "services.stale_payin_hold.sweep_superseded_completed_payins",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.config_rates.RECEIPT_WAIT_WINDOW_MINUTES", window_minutes
        ), patch(
            "services.order_expirer.CHECK_INTERVAL", 0.01
        ):
            await expire_orders_task(AsyncMock(), shutdown_event=shutdown)

        return extend, update_status, notify_ops

    async def test_waiting_for_video_is_not_expired(self):
        extend, update_status, notify_ops = await self._run_one_pass(
            _awaiting_video_order(), window_minutes=1440
        )

        update_status.assert_not_awaited()
        notify_ops.assert_not_awaited()
        extend.assert_awaited_once()
        self.assertGreater(extend.await_args.args[1], NOW)

    async def test_expires_with_ops_alert_after_window(self):
        order = _awaiting_video_order()
        order["payment_snapshot"]["receipt_recheck_requested_at"] = (
            NOW - timedelta(days=2)
        ).isoformat()

        _extend, update_status, notify_ops = await self._run_one_pass(
            order, window_minutes=1440
        )

        update_status.assert_awaited_once_with(order["order_id"], "EXPIRED")
        notify_ops.assert_awaited_once()
        self.assertEqual(notify_ops.await_args.args[0], "expired")
        self.assertIn("видео", notify_ops.await_args.kwargs.get("note", ""))

    async def test_provider_rejection_expires_without_waiting(self):
        """Payfast сказал CANCELED — ждать видео сутки незачем."""
        _extend, update_status, notify_ops = await self._run_one_pass(
            _awaiting_video_order(),
            window_minutes=1440,
            pf_result=(False, "payfast_status_canceled", {}),
        )

        update_status.assert_awaited_once_with("29638590", "EXPIRED")
        notify_ops.assert_not_awaited()


class RecheckMarkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_request_stamps_recheck_marker(self):
        order = {
            "order_id": "O1",
            "direction": "buy",
            "status": "PENDING",
            "user_id": 42,
        }
        merge = AsyncMock(return_value=True)

        with patch(
            "services.video_receipt_request.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.video_receipt_request.mark_ops_alert_once",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.video_receipt_request.update_order_to_awaiting_check",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.db.merge_order_payment_snapshot", new=merge
        ), patch(
            "services.order_ops_notify.notify_ops_order", new=AsyncMock()
        ), patch(
            "services.video_receipt_request._notify_user", new=AsyncMock()
        ):
            ok, _reason = await request_client_receipt_check(
                "O1", 3, source="appeals", allow_late=False
            )

        self.assertTrue(ok)
        merge.assert_awaited_once()
        self.assertIn("receipt_recheck_requested_at", merge.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
