"""Дедуп ops-карточек: awaiting_receipt один раз, receipt_attached один раз на доставку."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class FinalizeReceiptAttachedDedupTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_call_sends_second_skips(self):
        from services.receipt_ops_review import finalize_receipt_payfast_success

        order = {
            "order_id": "D1",
            "status": "AWAITING_CHECK",
            "user_id": 7,
            "required_receipt_type": 2,
        }
        marks = {"n": 0}

        async def fake_mark(order_id, kind):
            marks["n"] += 1
            return marks["n"] == 1

        with patch(
            "services.db.mark_ops_alert_once", new=AsyncMock(side_effect=fake_mark)
        ), patch(
            "services.db.clear_receipt_ops_pending", new=AsyncMock()
        ), patch(
            "services.db.update_order_status", new=AsyncMock(return_value=True)
        ), patch(
            "services.db.get_order", new=AsyncMock(return_value=dict(order))
        ), patch(
            "services.order_ops_notify.notify_ops_order", new=AsyncMock()
        ) as notify, patch(
            "services.receipt_ops_review._try_reconcile_payfast_settled",
            new=AsyncMock(),
        ):
            await finalize_receipt_payfast_success(dict(order), bot=MagicMock())
            await finalize_receipt_payfast_success(dict(order), bot=MagicMock())
        self.assertEqual(notify.await_count, 1)

    async def test_hold_clears_attached_dedup(self):
        from services.receipt_ops_review import hold_receipt_for_ops_review

        order = {
            "order_id": "D2",
            "status": "AWAITING_CHECK",
            "user_id": 7,
            "required_receipt_type": 2,
        }
        with patch(
            "services.receipt_ops_review.inspect_receipt_pdf_meta",
            return_value=None,
        ), patch(
            "services.db.merge_order_payment_snapshot", new=AsyncMock()
        ), patch(
            "services.db.get_order", new=AsyncMock(return_value=dict(order))
        ), patch(
            "services.receipt_ops_review._build_receipt_risk_note",
            new=AsyncMock(return_value=("note", "ok")),
        ), patch(
            "services.db.clear_ops_alert_once", new=AsyncMock()
        ) as clear, patch(
            "services.db.mark_ops_alert_once", new=AsyncMock(return_value=True)
        ), patch(
            "services.order_ops_notify.notify_ops_receipt_review",
            new=AsyncMock(),
        ), patch(
            "services.receipt_ops_review._receipt_local_path"
        ) as local_path, patch(
            "services.callback_signatures.sign_receipt_review",
            return_value="sig",
        ):
            local_path.return_value.is_file.return_value = False
            with patch(
                "services.order_ops_notify._admin_chat_id", return_value=None
            ):
                await hold_receipt_for_ops_review(
                    dict(order), "abc.pdf", bot=MagicMock()
                )
        clear.assert_awaited_once_with("D2", "receipt_attached_notify")

    async def test_review_card_dedup_per_file(self):
        from services.receipt_ops_review import hold_receipt_for_ops_review

        order = {
            "order_id": "D3",
            "status": "AWAITING_CHECK",
            "user_id": 7,
            "required_receipt_type": 2,
        }
        marks = {"n": 0}

        async def fake_mark(order_id, kind):
            self.assertEqual(kind, "receipt_ops_review_abc.pdf")
            marks["n"] += 1
            return marks["n"] == 1

        with patch(
            "services.receipt_ops_review.inspect_receipt_pdf_meta",
            return_value=None,
        ), patch(
            "services.db.merge_order_payment_snapshot", new=AsyncMock()
        ), patch(
            "services.db.get_order", new=AsyncMock(return_value=dict(order))
        ), patch(
            "services.receipt_ops_review._build_receipt_risk_note",
            new=AsyncMock(return_value=("note", "ok")),
        ), patch(
            "services.db.clear_ops_alert_once", new=AsyncMock()
        ), patch(
            "services.db.mark_ops_alert_once", new=AsyncMock(side_effect=fake_mark)
        ), patch(
            "services.order_ops_notify.notify_ops_receipt_review",
            new=AsyncMock(),
        ) as review_notify, patch(
            "services.receipt_ops_review._receipt_local_path"
        ) as local_path, patch(
            "services.callback_signatures.sign_receipt_review",
            return_value="sig",
        ):
            local_path.return_value.is_file.return_value = False
            with patch(
                "services.order_ops_notify._admin_chat_id", return_value=None
            ):
                await hold_receipt_for_ops_review(
                    dict(order), "abc.pdf", bot=MagicMock()
                )
                await hold_receipt_for_ops_review(
                    dict(order), "abc.pdf", bot=MagicMock()
                )
        self.assertEqual(review_notify.await_count, 1)


if __name__ == "__main__":
    unittest.main()
