"""Отложенная досылка чеков + /stat строка + resolve_client_ip."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class ResolveClientIpTests(unittest.TestCase):
    def _load(self):
        import services.webhook_security as ws

        return ws.resolve_client_ip

    def test_cf_header_wins_over_x_real_ip(self):
        resolve_client_ip = self._load()
        with patch(
            "services.webhook_security._configured_networks",
            return_value=(),
        ):
            got = resolve_client_ip(
                "127.0.0.1",
                cf_connecting_ip="203.0.113.7",
                real_ip="198.51.100.9",
            )
        self.assertEqual(got, "203.0.113.7")

    def test_untrusted_peer_ignores_headers(self):
        resolve_client_ip = self._load()
        with patch(
            "services.webhook_security._configured_networks",
            return_value=(),
        ):
            got = resolve_client_ip(
                "203.0.113.99",
                cf_connecting_ip="203.0.113.7",
                real_ip="198.51.100.9",
            )
        self.assertEqual(got, "203.0.113.99")


class ReceiptSendPendingTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_delivers_and_finalizes(self):
        from services.receipt_ops_review import (
            OUTCOME_SUCCESS,
            retry_pending_receipt_send,
        )

        order = {
            "order_id": "R1",
            "status": "AWAITING_CHECK",
            "payment_snapshot": {
                "receipt_send_pending": {"receipt_name": "abc.pdf", "attempts": 0}
            },
        }
        with patch(
            "services.db.get_order", new=AsyncMock(return_value=order)
        ), patch(
            "services.receipt_ops_review.submit_receipt_to_payfast",
            new=AsyncMock(return_value=(OUTCOME_SUCCESS, 200, {})),
        ) as submit, patch(
            "services.db.clear_receipt_ops_pending", new=AsyncMock()
        ), patch(
            "services.receipt_ops_review.clear_receipt_send_pending",
            new=AsyncMock(),
        ) as clear, patch(
            "services.receipt_ops_review.finalize_receipt_payfast_success",
            new=AsyncMock(),
        ) as finalize:
            done = await retry_pending_receipt_send("R1", bot=MagicMock())
        self.assertTrue(done)
        submit.assert_awaited_once()
        clear.assert_awaited_once_with("R1")
        finalize.assert_awaited_once()

    async def test_retry_keeps_pending_on_503(self):
        from services.receipt_ops_review import (
            OUTCOME_RETRYABLE,
            retry_pending_receipt_send,
        )

        order = {
            "order_id": "R2",
            "status": "AWAITING_CHECK",
            "payment_snapshot": {
                "receipt_send_pending": {"receipt_name": "abc.pdf", "attempts": 1}
            },
        }
        with patch(
            "services.db.get_order", new=AsyncMock(return_value=order)
        ), patch(
            "services.receipt_ops_review.submit_receipt_to_payfast",
            new=AsyncMock(
                return_value=(OUTCOME_RETRYABLE, 503, {"body": {"error": "later"}})
            ),
        ), patch(
            "services.db.merge_order_payment_snapshot", new=AsyncMock()
        ) as merge, patch(
            "services.receipt_ops_review.finalize_receipt_payfast_success",
            new=AsyncMock(),
        ) as finalize:
            done = await retry_pending_receipt_send("R2")
        self.assertFalse(done)
        finalize.assert_not_awaited()
        merge.assert_awaited_once()
        patch_arg = merge.await_args.args[1]
        self.assertEqual(patch_arg["receipt_send_pending"]["attempts"], 2)
        self.assertEqual(patch_arg["receipt_send_pending"]["receipt_name"], "abc.pdf")

    async def test_no_pending_returns_done(self):
        from services.receipt_ops_review import retry_pending_receipt_send

        order = {"order_id": "R3", "status": "AWAITING_CHECK", "payment_snapshot": {}}
        with patch("services.db.get_order", new=AsyncMock(return_value=order)):
            self.assertTrue(await retry_pending_receipt_send("R3"))

    async def test_terminal_status_clears_pending(self):
        from services.receipt_ops_review import retry_pending_receipt_send

        order = {
            "order_id": "R4",
            "status": "COMPLETED",
            "payment_snapshot": {
                "receipt_send_pending": {"receipt_name": "abc.pdf"}
            },
        }
        with patch(
            "services.db.get_order", new=AsyncMock(return_value=order)
        ), patch(
            "services.receipt_ops_review.clear_receipt_send_pending",
            new=AsyncMock(),
        ) as clear:
            self.assertTrue(await retry_pending_receipt_send("R4"))
        clear.assert_awaited_once_with("R4")

    async def test_defer_writes_marker(self):
        from services.receipt_ops_review import defer_receipt_send_to_background

        with patch(
            "services.db.merge_order_payment_snapshot", new=AsyncMock()
        ) as merge:
            await defer_receipt_send_to_background("R5", "abc.pdf", req_type=2)
        merge.assert_awaited_once()
        patch_arg = merge.await_args.args[1]
        self.assertEqual(
            patch_arg["receipt_send_pending"]["receipt_name"], "abc.pdf"
        )
        self.assertIn("next_try_at", patch_arg["receipt_send_pending"])


class StatReceiptStateTests(unittest.TestCase):
    def test_ops_pending(self):
        from handlers.appeals_stat import _fmt_receipt_state

        line = _fmt_receipt_state(
            {
                "order_id": "1",
                "status": "AWAITING_CHECK",
                "receipt_file": "a.pdf",
                "payment_snapshot": {"receipt_ops_pending": True},
            }
        )
        self.assertIn("на проверке у оператора", line)
        self.assertIn("a.pdf", line)

    def test_autoretry(self):
        from handlers.appeals_stat import _fmt_receipt_state

        line = _fmt_receipt_state(
            {
                "order_id": "1",
                "status": "AWAITING_CHECK",
                "receipt_file": "a.pdf",
                "payment_snapshot": {
                    "receipt_send_pending": {"receipt_name": "a.pdf", "attempts": 2}
                },
            }
        )
        self.assertIn("автоповтор", line)
        self.assertIn("попыток 2", line)

    def test_sent_to_merchant(self):
        from handlers.appeals_stat import _fmt_receipt_state

        line = _fmt_receipt_state(
            {
                "order_id": "1",
                "status": "PENDING",
                "receipt_file": "a.pdf",
                "payment_snapshot": {},
            }
        )
        self.assertIn("отправлен мерчанту", line)

    def test_no_receipt(self):
        from handlers.appeals_stat import _fmt_receipt_state

        self.assertIsNone(
            _fmt_receipt_state(
                {"order_id": "1", "status": "PENDING", "payment_snapshot": {}}
            )
        )


class PendingReceiptSqlTests(unittest.TestCase):
    def test_query_filters_pending(self):
        import inspect

        from services.db import get_orders_with_pending_receipt_send

        src = inspect.getsource(get_orders_with_pending_receipt_send)
        self.assertIn("receipt_send_pending", src)
        self.assertIn("next_try_at", src)
        self.assertIn("AWAITING_CHECK", src)


if __name__ == "__main__":
    unittest.main()
