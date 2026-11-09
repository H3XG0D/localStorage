"""Тесты payfast_buy_complete и reconciler."""
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

from services.payfast_buy_complete import (
    _order_needs_wallet_confirm,
    advance_awaiting_check_to_pending,
    awaiting_check_can_settle,
    complete_buy_from_payfast_settled,
    finalize_buy_payfast_completed,
    has_client_video_file,
)


class PayfastBuyCompleteTests(unittest.IsolatedAsyncioTestCase):
    async def test_advance_awaiting_to_pending(self):
        order = {"order_id": "O1", "status": "AWAITING_CHECK", "direction": "buy"}
        pending = {"order_id": "O1", "status": "PENDING", "direction": "buy"}
        with patch(
            "services.payfast_buy_complete.update_order_status",
            new=AsyncMock(return_value=True),
        ) as upd, patch(
            "services.payfast_buy_complete.get_order",
            new=AsyncMock(return_value=pending),
        ):
            out, changed = await advance_awaiting_check_to_pending("O1", order)
        upd.assert_awaited_once_with("O1", "PENDING")
        self.assertTrue(changed)
        self.assertEqual(out["status"], "PENDING")

    async def test_video_hold_blocks_completion(self):
        """AWAITING_CHECK + required_receipt_type=3 без ролика не завершается."""
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "required_receipt_type": 3,
            "user_id": 1,
        }
        with patch(
            "services.payfast_buy_complete.advance_awaiting_check_to_pending",
            new=AsyncMock(),
        ) as advance, patch(
            "services.payfast_buy_complete.complete_buy_on_payfast_confirmed",
            new=AsyncMock(),
        ) as confirm, patch(
            "services.payfast_buy_complete.finalize_buy_payfast_completed",
            new=AsyncMock(),
        ) as finalize:
            ok, err = await complete_buy_from_payfast_settled(
                "O1", order, receipt_bypass=True
            )
        self.assertFalse(ok)
        self.assertEqual(err, "awaiting_video_hold")
        advance.assert_not_awaited()
        confirm.assert_not_awaited()
        finalize.assert_not_awaited()

    async def test_video_hold_blocks_when_only_old_pdf(self):
        """После запроса видео старый PDF не считается подтверждением."""
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "required_receipt_type": 3,
            "receipt_file": "old.pdf",
            "user_id": 1,
        }
        with patch(
            "services.payfast_buy_complete.advance_awaiting_check_to_pending",
            new=AsyncMock(),
        ) as advance, patch(
            "services.payfast_buy_complete.complete_buy_on_payfast_confirmed",
            new=AsyncMock(),
        ) as confirm, patch(
            "services.payfast_buy_complete.finalize_buy_payfast_completed",
            new=AsyncMock(),
        ) as finalize:
            ok, err = await complete_buy_from_payfast_settled("O1", order)
        self.assertFalse(ok)
        self.assertEqual(err, "awaiting_video_hold")
        advance.assert_not_awaited()
        confirm.assert_not_awaited()
        finalize.assert_not_awaited()

    async def test_video_hold_settles_when_mp4_on_file(self):
        """AWAITING_CHECK + req_type=3 + mp4: Payfast SUCCSES может закрыть."""
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "required_receipt_type": 3,
            "receipt_file": "clip.mp4",
            "user_id": 1,
        }
        pending = {**order, "status": "PENDING"}
        with patch(
            "services.payfast_buy_complete.advance_awaiting_check_to_pending",
            new=AsyncMock(return_value=(pending, True)),
        ) as advance, patch(
            "services.payfast_buy_complete.complete_buy_on_payfast_confirmed",
            new=AsyncMock(return_value=(True, None, None)),
        ), patch(
            "services.payfast_buy_complete.finalize_buy_payfast_completed",
            new=AsyncMock(),
        ) as finalize, patch(
            "services.db.clear_receipt_ops_pending",
            new=AsyncMock(),
        ) as clear:
            ok, err = await complete_buy_from_payfast_settled("O1", order)
        self.assertTrue(ok)
        self.assertIsNone(err)
        advance.assert_awaited_once()
        clear.assert_awaited_once_with("O1")
        finalize.assert_awaited_once()

    async def test_completion_resumes_after_video_submitted(self):
        """После присылки видео (PENDING, req_type=3) заявка снова завершается."""
        order = {
            "order_id": "O1",
            "status": "PENDING",
            "direction": "buy",
            "required_receipt_type": 3,
            "user_id": 1,
        }
        with patch(
            "services.payfast_buy_complete.advance_awaiting_check_to_pending",
            new=AsyncMock(return_value=(order, False)),
        ), patch(
            "services.payfast_buy_complete.complete_buy_on_payfast_confirmed",
            new=AsyncMock(return_value=(True, None, None)),
        ), patch(
            "services.payfast_buy_complete.finalize_buy_payfast_completed",
            new=AsyncMock(),
        ) as finalize:
            ok, err = await complete_buy_from_payfast_settled(
                "O1", order, receipt_bypass=True
            )
        self.assertTrue(ok)
        self.assertIsNone(err)
        finalize.assert_awaited_once()

    async def test_complete_from_awaiting_check(self):
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "user_id": 1,
            "fiat_amount": 1000,
        }
        pending = {**order, "status": "PENDING"}
        with patch(
            "services.payfast_buy_complete.advance_awaiting_check_to_pending",
            new=AsyncMock(return_value=(pending, True)),
        ), patch(
            "services.payfast_buy_complete.complete_buy_on_payfast_confirmed",
            new=AsyncMock(return_value=(True, None, None)),
        ), patch(
            "services.payfast_buy_complete.finalize_buy_payfast_completed",
            new=AsyncMock(),
        ) as finalize:
            ok, err = await complete_buy_from_payfast_settled(
                "O1", order, receipt_bypass=True
            )
        self.assertFalse(ok)
        self.assertEqual(err, "receipt_not_submitted")
        finalize.assert_not_awaited()

    async def test_complete_from_awaiting_check_when_pdf_on_file(self):
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "user_id": 1,
            "fiat_amount": 1000,
            "receipt_file": "r.pdf",
            "required_receipt_type": 2,
        }
        pending = {**order, "status": "PENDING"}
        with patch(
            "services.payfast_buy_complete.advance_awaiting_check_to_pending",
            new=AsyncMock(return_value=(pending, True)),
        ) as advance, patch(
            "services.payfast_buy_complete.complete_buy_on_payfast_confirmed",
            new=AsyncMock(return_value=(True, None, None)),
        ), patch(
            "services.payfast_buy_complete.finalize_buy_payfast_completed",
            new=AsyncMock(),
        ) as finalize, patch(
            "services.db.clear_receipt_ops_pending",
            new=AsyncMock(),
        ) as clear:
            ok, err = await complete_buy_from_payfast_settled("O1", order)
        self.assertTrue(ok)
        self.assertIsNone(err)
        advance.assert_awaited_once()
        clear.assert_awaited_once_with("O1")
        finalize.assert_awaited_once()


class VideoFileDetectTests(unittest.TestCase):
    def test_has_client_video_file_by_extension(self):
        self.assertTrue(has_client_video_file({"receipt_file": "a.mp4"}))
        self.assertTrue(has_client_video_file({"receipt_file": "a.MOV"}))
        self.assertFalse(has_client_video_file({"receipt_file": "a.pdf"}))
        self.assertFalse(has_client_video_file({"receipt_file": ""}))
        self.assertFalse(has_client_video_file({}))

    def test_awaiting_check_can_settle_video_vs_pdf(self):
        base = {"status": "AWAITING_CHECK", "required_receipt_type": 3}
        self.assertFalse(awaiting_check_can_settle(base))
        self.assertFalse(
            awaiting_check_can_settle({**base, "receipt_file": "old.pdf"})
        )
        self.assertTrue(
            awaiting_check_can_settle({**base, "receipt_file": "clip.mp4"})
        )
        self.assertTrue(
            awaiting_check_can_settle(
                {
                    "status": "AWAITING_CHECK",
                    "required_receipt_type": 2,
                    "receipt_file": "r.pdf",
                }
            )
        )


class PayfastReconcilerTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_one_order_completes(self):
        order = {
            "order_id": "O9",
            "status": "AWAITING_CHECK",
            "direction": "buy",
        }
        with patch(
            "services.payfast_order_reconciler.verify_payfast_ready_for_payout",
            new=AsyncMock(return_value=(True, None, {})),
        ), patch(
            "services.payfast_order_reconciler.complete_buy_from_payfast_settled",
            new=AsyncMock(return_value=(False, "receipt_not_submitted")),
        ) as complete:
            from services.payfast_order_reconciler import reconcile_one_order

            result = await reconcile_one_order(order)
        self.assertFalse(result)
        complete.assert_awaited_once()

    async def test_reconcile_awaiting_check_with_receipt_completes(self):
        order = {
            "order_id": "O9",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "receipt_file": "r.pdf",
        }
        with patch(
            "services.payfast_order_reconciler.verify_payfast_ready_for_payout",
            new=AsyncMock(return_value=(True, None, {"status": "SUCCSES"})),
        ), patch(
            "services.payfast_order_reconciler.complete_buy_from_payfast_settled",
            new=AsyncMock(return_value=(True, None)),
        ) as complete:
            from services.payfast_order_reconciler import reconcile_one_order

            result = await reconcile_one_order(order)
        self.assertTrue(result)
        complete.assert_awaited_once()

    async def test_reconcile_passes_verified_live_response_to_completion(self):
        order = {"order_id": "O10", "status": "PENDING", "direction": "buy"}
        response = {"data_order": {"amount": "3823", "status": "SUCCSES"}}
        with patch(
            "services.payfast_order_reconciler.verify_payfast_ready_for_payout",
            new=AsyncMock(return_value=(True, None, response)),
        ), patch(
            "services.payfast_order_reconciler.complete_buy_from_payfast_settled",
            new=AsyncMock(return_value=(True, None)),
        ) as complete:
            from services.payfast_order_reconciler import reconcile_one_order

            result = await reconcile_one_order(order)
        self.assertTrue(result)
        complete.assert_awaited_once_with(
            "O10", dict(order), verified_payfast_response=response
        )

    async def test_reconcile_skips_unpaid(self):
        order = {"order_id": "O9", "status": "PENDING", "direction": "buy"}
        with patch(
            "services.payfast_order_reconciler.verify_payfast_ready_for_payout",
            new=AsyncMock(return_value=(False, "payfast_not_paid", None)),
        ), patch(
            "services.payfast_order_reconciler.handle_payfast_recheck",
            new=AsyncMock(),
        ) as handle, patch(
            "services.payfast_order_reconciler.complete_buy_from_payfast_settled",
            new=AsyncMock(),
        ) as complete:
            from services.payfast_order_reconciler import reconcile_one_order

            result = await reconcile_one_order(order)
        self.assertFalse(result)
        handle.assert_not_awaited()
        complete.assert_not_awaited()

    async def test_finalize_attaches_5min_wallet_timer_for_btc_and_retry(self):
        self.assertTrue(_order_needs_wallet_confirm({"direction": "buy", "crypto": "btc"}))
        self.assertFalse(_order_needs_wallet_confirm({"direction": "buy", "crypto": "usdt_trc20"}))
        self.assertTrue(
            _order_needs_wallet_confirm(
                {
                    "direction": "buy",
                    "crypto": "usdt_trc20",
                    "payment_snapshot": {"requisite_retry": True},
                }
            )
        )
        btc_order = {"order_id": "O55", "direction": "buy", "crypto": "btc", "status": "COMPLETED"}
        with patch(
            "services.db.mark_ops_alert_once",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.payfast_buy_complete.get_order",
            new=AsyncMock(return_value=btc_order),
        ), patch(
            "services.payfast_buy_complete.notify_ops_order",
            new=AsyncMock(),
        ) as notify_ops:
            await finalize_buy_payfast_completed("O55", btc_order)
        notify_ops.assert_awaited_once()
        self.assertTrue(notify_ops.await_args.kwargs.get("wallet_early"))
        self.assertIn("Таймер 5 мин", notify_ops.await_args.kwargs.get("note", ""))


if __name__ == "__main__":
    unittest.main()
