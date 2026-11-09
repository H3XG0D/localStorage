"""Тесты проверки чека оператором перед Payfast."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.callback_signatures import sign_receipt_review, verify_receipt_review_signature
from services.db import is_receipt_ops_pending
from services.receipt_ops_review import (
    OUTCOME_RETRYABLE,
    OUTCOME_SUCCESS,
    approve_receipt_and_send_to_payfast,
    deliver_video_to_payfast_appeals,
    needs_receipt_ops_review,
    reject_receipt_ban_and_cancel,
    should_auto_forward_video_to_payfast,
    should_hold_receipt_for_ops,
    submit_receipt_to_payfast,
)


class RoundUpOpsNoticeTests(unittest.TestCase):
    def test_round_up_order_warns_operator_about_expected_sum_and_credit(self):
        from services.receipt_ops_review import round_up_ops_notice

        text = round_up_ops_notice(
            {"fiat_amount": 3990, "overpay_credit_rub": 390, "payin_requisite_id": 7}
        )
        self.assertIn("3 990 ₽", text)
        self.assertIn("3 600 ₽", text)
        self.assertIn("390 ₽ на баланс", text)
        self.assertIn("отклоняй", text)
        self.assertNotIn("не начислится", text)

    def test_pdf_without_amount_adds_hold_warning(self):
        from services.receipt_ops_review import round_up_ops_notice

        text = round_up_ops_notice(
            {"fiat_amount": 3990, "overpay_credit_rub": 390},
            pdf_meta={"amount_present": False},
        )
        self.assertIn("не начислится", text)

    def test_plain_payin_order_has_no_notice(self):
        from services.receipt_ops_review import round_up_ops_notice

        self.assertEqual(round_up_ops_notice({"fiat_amount": 3600, "overpay_credit_rub": 0}), "")
        self.assertEqual(round_up_ops_notice({"fiat_amount": None, "overpay_credit_rub": "x"}), "")


class ReceiptOpsReviewSignatureTests(unittest.TestCase):
    def test_sign_and_verify(self):
        sig = sign_receipt_review("ABC12345")
        self.assertTrue(verify_receipt_review_signature("ABC12345", sig))
        self.assertFalse(verify_receipt_review_signature("ABC12345", "bad"))


class IsReceiptOpsPendingTests(unittest.TestCase):
    def test_pending_true(self):
        order = {"payment_snapshot": {"receipt_ops_pending": True}}
        self.assertTrue(is_receipt_ops_pending(order))

    def test_pending_false(self):
        order = {"payment_snapshot": {"receipt_ops_pending": False}}
        self.assertFalse(is_receipt_ops_pending(order))

    def test_pending_json_string(self):
        order = {"payment_snapshot": '{"receipt_ops_pending": true}'}
        self.assertTrue(is_receipt_ops_pending(order))


class NeedsReceiptOpsReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_paid_count_zero(self):
        with patch(
            "services.db.get_buyer_ops_stats",
            new=AsyncMock(return_value={"paid_count": 0}),
        ):
            self.assertTrue(await needs_receipt_ops_review(1))

    async def test_paid_count_two(self):
        with patch(
            "services.db.get_buyer_ops_stats",
            new=AsyncMock(return_value={"paid_count": 2}),
        ):
            self.assertTrue(await needs_receipt_ops_review(1))

    async def test_paid_count_three_skips(self):
        with patch(
            "services.db.get_buyer_ops_stats",
            new=AsyncMock(return_value={"paid_count": 3}),
        ):
            self.assertFalse(await needs_receipt_ops_review(1))


class ShouldHoldReceiptForOpsTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_buyer_held_even_if_ok(self):
        with patch(
            "services.db.get_buyer_ops_stats",
            new=AsyncMock(return_value={"paid_count": 0}),
        ):
            self.assertTrue(await should_hold_receipt_for_ops(1, risk_level="OK"))

    async def test_trusted_ok_autopass(self):
        with patch(
            "services.db.get_buyer_ops_stats",
            new=AsyncMock(return_value={"paid_count": 5}),
        ):
            self.assertFalse(await should_hold_receipt_for_ops(1, risk_level="OK"))

    async def test_trusted_watch_autopass(self):
        with patch(
            "services.db.get_buyer_ops_stats",
            new=AsyncMock(return_value={"paid_count": 5}),
        ):
            self.assertFalse(await should_hold_receipt_for_ops(1, risk_level="СМОТРЕТЬ"))

    async def test_trusted_strict_autopass(self):
        with patch(
            "services.db.get_buyer_ops_stats",
            new=AsyncMock(return_value={"paid_count": 14}),
        ):
            self.assertFalse(
                await should_hold_receipt_for_ops(1, risk_level="ДОСКОНАЛЬНО")
            )

    async def test_video_not_held_even_for_new_buyer(self):
        order = {
            "direction": "buy",
            "required_receipt_type": 3,
            "order_id": "O1",
        }
        with patch(
            "services.db.get_buyer_ops_stats",
            new=AsyncMock(return_value={"paid_count": 0}),
        ):
            self.assertFalse(
                await should_hold_receipt_for_ops(1, risk_level="OK", order=order)
            )

    async def test_payfast_settled_skips_hold_for_new_buyer(self):
        order = {
            "direction": "buy",
            "required_receipt_type": 2,
            "order_id": "O1",
            "merchant_order_id": "uuid-1",
        }
        with patch(
            "services.db.get_buyer_ops_stats",
            new=AsyncMock(return_value={"paid_count": 0}),
        ), patch(
            "services.receipt_ops_review._payfast_order_is_settled",
            new=AsyncMock(return_value=True),
        ) as settled:
            self.assertFalse(
                await should_hold_receipt_for_ops(
                    1, risk_level="СМОТРЕТЬ", order=order
                )
            )
        settled.assert_awaited_once()

    async def test_payin_rail_still_held_when_payfast_would_be_settled(self):
        order = {
            "direction": "buy",
            "required_receipt_type": 2,
            "order_id": "O1",
            "payin_requisite_id": 9,
        }
        with patch(
            "services.db.get_buyer_ops_stats",
            new=AsyncMock(return_value={"paid_count": 5}),
        ), patch(
            "services.receipt_ops_review._payfast_order_is_settled",
            new=AsyncMock(return_value=True),
        ) as settled:
            self.assertTrue(
                await should_hold_receipt_for_ops(
                    1, risk_level="СМОТРЕТЬ", order=order
                )
            )
        settled.assert_not_awaited()


class BuyerOpsStatsSqlTests(unittest.TestCase):
    def test_counts_paid_and_completed(self):
        import inspect

        from services.db import get_buyer_ops_stats

        src = inspect.getsource(get_buyer_ops_stats)
        self.assertIn("status IN ('PAID', 'COMPLETED')", src)


class AutoForwardVideoTests(unittest.TestCase):
    def test_buy_video_forwards(self):
        self.assertTrue(
            should_auto_forward_video_to_payfast(
                {"direction": "buy", "required_receipt_type": 3}
            )
        )

    def test_pdf_does_not_forward(self):
        self.assertFalse(
            should_auto_forward_video_to_payfast(
                {"direction": "buy", "required_receipt_type": 2}
            )
        )
        self.assertFalse(
            should_auto_forward_video_to_payfast(
                {
                    "direction": "buy",
                    "required_receipt_type": 3,
                    "receipt_file": "cheque.pdf",
                }
            )
        )

    def test_payin_rail_does_not_forward(self):
        self.assertFalse(
            should_auto_forward_video_to_payfast(
                {
                    "direction": "buy",
                    "required_receipt_type": 3,
                    "payin_requisite_id": 9,
                }
            )
        )

    def test_exchange_flow_auto_forwards_video(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        flow = (root / "handlers" / "exchange_flow.py").read_text()
        review = (root / "services" / "receipt_ops_review.py").read_text()
        self.assertIn("route_client_receipt", flow)
        self.assertIn("should_auto_forward_video_to_payfast", review)
        self.assertIn("deliver_video_to_payfast_appeals", review)


class MiniappReceiptFileTests(unittest.IsolatedAsyncioTestCase):
    async def test_pdf_goes_to_ops_as_document(self):
        from services.receipt_ops_review import post_miniapp_receipt_file

        bot = MagicMock()
        bot.send_document = AsyncMock()
        bot.send_video = AsyncMock()
        path = MagicMock()
        path.is_file.return_value = True
        path.open.return_value.__enter__.return_value = object()
        with patch(
            "services.db.ops_alert_was_sent", new=AsyncMock(return_value=False)
        ), patch(
            "services.db.mark_ops_alert_once", new=AsyncMock(return_value=True)
        ), patch(
            "services.receipt_ops_review._receipt_local_path", return_value=path
        ), patch(
            "services.order_ops_notify._admin_chat_id", return_value=-100
        ):
            await post_miniapp_receipt_file(
                {
                    "order_id": "317",
                    "order_source": "tg_miniapp",
                    "receipt_file": "cheque.pdf",
                    "required_receipt_type": 3,
                    "merchant_order_id": "8ed70f7c-2c75-41d5-882c-6a8420ebf4d6",
                },
                bot=bot,
            )
        bot.send_video.assert_not_awaited()
        bot.send_document.assert_awaited_once()
        self.assertEqual(
            bot.send_document.await_args.kwargs["caption"],
            "Миниаппка · 8ed70f7c-2c75-41d5-882c-6a8420ebf4d6",
        )


class NotifyAppealsVideoTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_chat_returns_false(self):
        from services.order_ops_notify import notify_appeals_video

        bot = MagicMock()
        bot.send_video = AsyncMock()
        with patch("services.config_rates.appeals_group_id", return_value=0):
            ok = await notify_appeals_video(
                {"order_id": "O1", "merchant_order_id": "uuid-1"},
                bot=bot,
                file_id="file-1",
            )
        self.assertFalse(ok)
        bot.send_video.assert_not_awaited()

    async def test_sends_video_with_payfast_id(self):
        from services.order_ops_notify import notify_appeals_video

        bot = MagicMock()
        bot.send_video = AsyncMock()
        order = {
            "order_id": "O1",
            "merchant_order_id": "9829b175-d163-4447-9e91-9c5a23af8c56",
        }
        with patch("services.config_rates.appeals_group_id", return_value=-100):
            ok = await notify_appeals_video(order, bot=bot, file_id="file-1")
        self.assertTrue(ok)
        bot.send_video.assert_awaited_once()
        kwargs = bot.send_video.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], -100)
        self.assertEqual(kwargs["video"], "file-1")
        self.assertEqual(kwargs["caption"], "9829b175-d163-4447-9e91-9c5a23af8c56")

    async def test_document_fallback_when_send_video_fails(self):
        from services.order_ops_notify import notify_appeals_video

        bot = MagicMock()
        bot.send_video = AsyncMock(side_effect=RuntimeError("bad file"))
        bot.send_document = AsyncMock()
        with patch("services.config_rates.appeals_group_id", return_value=-100):
            ok = await notify_appeals_video(
                {"order_id": "O1", "merchant_order_id": "uuid-1"},
                bot=bot,
                file_id="file-1",
            )
        self.assertTrue(ok)
        bot.send_document.assert_awaited_once()


class DeliverVideoToAppealsTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_finalizes_without_api(self):
        order = {
            "order_id": "O1",
            "direction": "buy",
            "required_receipt_type": 3,
        }
        bot = MagicMock()
        with patch(
            "services.order_ops_notify.notify_appeals_video",
            new=AsyncMock(return_value=True),
        ) as notify, patch(
            "services.receipt_ops_review.finalize_receipt_payfast_success",
            new=AsyncMock(),
        ) as finalize, patch(
            "services.receipt_ops_review.submit_receipt_to_payfast",
            new=AsyncMock(),
        ) as submit:
            ok = await deliver_video_to_payfast_appeals(
                order, bot=bot, file_id="file-1"
            )
        self.assertTrue(ok)
        notify.assert_awaited_once()
        finalize.assert_awaited_once()
        submit.assert_not_awaited()

    async def test_failed_send_does_not_finalize(self):
        order = {"order_id": "O1", "direction": "buy", "required_receipt_type": 3}
        with patch(
            "services.order_ops_notify.notify_appeals_video",
            new=AsyncMock(return_value=False),
        ), patch(
            "services.receipt_ops_review.finalize_receipt_payfast_success",
            new=AsyncMock(),
        ) as finalize:
            ok = await deliver_video_to_payfast_appeals(
                order, bot=MagicMock(), file_id="file-1"
            )
        self.assertFalse(ok)
        finalize.assert_not_awaited()


class SubmitReceiptToPayfastTests(unittest.IsolatedAsyncioTestCase):
    async def test_success(self):
        order = {"order_id": "O1"}
        mock_fn = AsyncMock(return_value={"status": 200, "body": {}})
        with patch(
            "services.receipt_public_url.build_receipt_public_url",
            return_value="https://example.com/r.pdf",
        ), patch(
            "services.merchant_api_helpers.payin_set_check_for_order",
            new=AsyncMock(return_value={"status": 200, "body": {}}),
        ):
            outcome, status, _ = await submit_receipt_to_payfast(
                order, "abc.pdf", payin_set_check_fn=mock_fn
            )
        self.assertEqual(outcome, OUTCOME_SUCCESS)
        self.assertEqual(status, 200)

    async def test_retries_on_503_then_success(self):
        order = {"order_id": "O1"}
        mock_fn = AsyncMock(
            side_effect=[
                {"status": 503, "body": {"status_pending": "error", "error": "Попробуйте позже"}},
                {"status": 200, "body": {"status_pending": "ok"}},
            ]
        )
        with patch(
            "services.receipt_public_url.build_receipt_public_url",
            return_value="https://example.com/r.pdf",
        ), patch(
            "services.merchant_api_helpers.payin_set_check_for_order",
            new=mock_fn,
        ), patch(
            "services.receipt_ops_review.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep:
            outcome, status, _ = await submit_receipt_to_payfast(
                order, "abc.pdf", payin_set_check_fn=AsyncMock()
            )
        self.assertEqual(outcome, OUTCOME_SUCCESS)
        self.assertEqual(status, 200)
        self.assertEqual(mock_fn.await_count, 2)
        sleep.assert_awaited_once()

    async def test_exhausted_retries_returns_retryable(self):
        order = {"order_id": "O1"}
        mock_fn = AsyncMock(
            return_value={"status": 503, "body": {"status_pending": "error_server"}}
        )
        with patch(
            "services.receipt_public_url.build_receipt_public_url",
            return_value="https://example.com/r.pdf",
        ), patch(
            "services.merchant_api_helpers.payin_set_check_for_order",
            new=mock_fn,
        ), patch(
            "services.receipt_ops_review.PAYIN_SET_CHECK_MAX_ATTEMPTS",
            2,
        ), patch(
            "services.receipt_ops_review.asyncio.sleep",
            new=AsyncMock(),
        ):
            outcome, status, _ = await submit_receipt_to_payfast(
                order, "abc.pdf", payin_set_check_fn=AsyncMock()
            )
        self.assertEqual(outcome, OUTCOME_RETRYABLE)
        self.assertEqual(status, 503)
        self.assertEqual(mock_fn.await_count, 2)

    async def test_already_paid_400_is_success(self):
        order = {"order_id": "O1"}
        mock_fn = AsyncMock(
            return_value={
                "status": 400,
                "body": {"status_pending": "error", "error": "Заявка уже успешно оплачена"},
            }
        )
        with patch(
            "services.receipt_public_url.build_receipt_public_url",
            return_value="https://example.com/r.pdf",
        ), patch(
            "services.merchant_api_helpers.payin_set_check_for_order",
            new=mock_fn,
        ):
            outcome, status, result = await submit_receipt_to_payfast(
                order, "abc.pdf", payin_set_check_fn=AsyncMock()
            )
        self.assertEqual(outcome, OUTCOME_SUCCESS)
        self.assertEqual(status, 400)
        self.assertTrue(result["already_settled"])
        self.assertEqual(mock_fn.await_count, 1)

    async def test_400_probes_live_payfast_and_succeeds_if_settled(self):
        order = {"order_id": "O1"}
        mock_fn = AsyncMock(
            return_value={"status": 400, "body": {"error": "invalid file"}}
        )
        with patch(
            "services.receipt_public_url.build_receipt_public_url",
            return_value="https://example.com/r.pdf",
        ), patch(
            "services.merchant_api_helpers.payin_set_check_for_order",
            new=mock_fn,
        ), patch(
            "services.receipt_ops_review._payfast_order_is_settled",
            new=AsyncMock(return_value=True),
        ):
            outcome, status, result = await submit_receipt_to_payfast(
                order, "abc.pdf", payin_set_check_fn=AsyncMock()
            )
        self.assertEqual(outcome, OUTCOME_SUCCESS)
        self.assertEqual(status, 400)
        self.assertTrue(result["already_settled"])

    async def test_genuine_400_stays_rejected(self):
        order = {"order_id": "O1"}
        mock_fn = AsyncMock(
            return_value={"status": 400, "body": {"error": "PDF rejected"}}
        )
        with patch(
            "services.receipt_public_url.build_receipt_public_url",
            return_value="https://example.com/r.pdf",
        ), patch(
            "services.merchant_api_helpers.payin_set_check_for_order",
            new=mock_fn,
        ), patch(
            "services.receipt_ops_review._payfast_order_is_settled",
            new=AsyncMock(return_value=False),
        ):
            outcome, status, _ = await submit_receipt_to_payfast(
                order, "abc.pdf", payin_set_check_fn=AsyncMock()
            )
        self.assertEqual(outcome, "rejected")
        self.assertEqual(status, 400)


class PayfastAlreadyPaidHelperTests(unittest.TestCase):
    def test_russian_already_paid(self):
        from services.merchant_api_helpers import payfast_set_check_already_paid

        self.assertTrue(
            payfast_set_check_already_paid(
                {"status": 400, "body": {"error": "Заявка уже успешно оплачена"}}
            )
        )
        self.assertFalse(
            payfast_set_check_already_paid(
                {"status": 400, "body": {"error": "PDF не пройден"}}
            )
        )


class ApproveReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_approve_sends_to_payfast(self):
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "user_id": 99,
            "receipt_file": "r.pdf",
            "payment_snapshot": {"receipt_ops_pending": True},
            "required_receipt_type": 2,
        }
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.db.is_receipt_ops_pending",
            return_value=True,
        ), patch(
            "services.receipt_ops_review.submit_receipt_to_payfast",
            new=AsyncMock(return_value=(OUTCOME_SUCCESS, 200, {})),
        ) as submit, patch(
            "services.receipt_ops_review.finalize_receipt_payfast_success",
            new=AsyncMock(),
        ) as finalize:
            ok, err = await approve_receipt_and_send_to_payfast("O1", 1, bot=bot)
        self.assertTrue(ok)
        self.assertIsNone(err)
        submit.assert_awaited_once()
        finalize.assert_awaited_once()

    async def test_approve_video_skips_payfast_api(self):
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "user_id": 99,
            "receipt_file": "clip.mp4",
            "payment_snapshot": {"receipt_ops_pending": True},
            "required_receipt_type": 3,
        }
        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.db.is_receipt_ops_pending",
            return_value=True,
        ), patch(
            "services.receipt_ops_review.submit_receipt_to_payfast",
            new=AsyncMock(),
        ) as submit, patch(
            "services.receipt_ops_review.finalize_receipt_payfast_success",
            new=AsyncMock(),
        ) as finalize:
            ok, err = await approve_receipt_and_send_to_payfast("O1", 1, bot=MagicMock())
        self.assertTrue(ok)
        self.assertIsNone(err)
        submit.assert_not_awaited()
        finalize.assert_awaited_once()

    async def test_approve_payin_rail_skips_payfast(self):
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "user_id": 99,
            "receipt_file": "r.pdf",
            "payin_requisite_id": 12,
            "payment_snapshot": {"receipt_ops_pending": True},
        }
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.db.is_receipt_ops_pending",
            return_value=True,
        ), patch(
            "services.db.clear_receipt_ops_pending",
            new=AsyncMock(),
        ) as clear, patch(
            "services.db.update_order_status",
            new=AsyncMock(return_value=True),
        ) as upd, patch(
            "services.receipt_ops_review.submit_receipt_to_payfast",
            new=AsyncMock(),
        ) as submit, patch(
            "services.menu.main_menu_keyboard",
            new=AsyncMock(return_value=None),
        ):
            ok, err = await approve_receipt_and_send_to_payfast("O1", 1, bot=bot)
        self.assertTrue(ok)
        self.assertIsNone(err)
        submit.assert_not_awaited()
        clear.assert_awaited_once_with("O1")
        upd.assert_awaited_once_with("O1", "COMPLETED")
        bot.send_message.assert_awaited_once()

    async def test_missing_uuid_is_local_error_not_payfast_reject(self):
        from services.merchant_api_helpers import payin_set_check_for_order

        result = await payin_set_check_for_order(
            {"order_id": "O1", "payment_snapshot": {}},
            "https://example.com/r.pdf",
            AsyncMock(),
        )
        self.assertEqual(result["status"], 422)
        self.assertEqual(result["local_error"], "missing_payfast_uuid")

    async def test_approve_reports_missing_payfast_uuid(self):
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "receipt_file": "r.pdf",
            "payment_snapshot": {"receipt_ops_pending": True},
        }
        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.db.is_receipt_ops_pending",
            return_value=True,
        ), patch(
            "services.receipt_ops_review.submit_receipt_to_payfast",
            new=AsyncMock(
                return_value=(
                    "error",
                    422,
                    {"local_error": "missing_payfast_uuid"},
                )
            ),
        ):
            ok, err = await approve_receipt_and_send_to_payfast("O1", 1, bot=MagicMock())
        self.assertFalse(ok)
        self.assertEqual(err, "Не найден ID Payfast заявки — сообщите администратору")

    async def test_approve_idempotent_when_not_pending(self):
        order = {
            "order_id": "O1",
            "status": "PENDING",
            "receipt_file": "r.pdf",
            "payment_snapshot": {},
        }
        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.db.is_receipt_ops_pending",
            return_value=False,
        ):
            ok, err = await approve_receipt_and_send_to_payfast("O1", 1, bot=MagicMock())
        self.assertFalse(ok)
        self.assertEqual(err, "Заявка не ожидает чек")

    async def test_approve_already_paid_finalizes_and_reconciles(self):
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "user_id": 99,
            "receipt_file": "r.pdf",
            "payment_snapshot": {"receipt_ops_pending": True},
            "required_receipt_type": 2,
        }
        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.db.is_receipt_ops_pending",
            return_value=True,
        ), patch(
            "services.receipt_ops_review.submit_receipt_to_payfast",
            new=AsyncMock(
                return_value=(
                    OUTCOME_SUCCESS,
                    400,
                    {
                        "already_settled": True,
                        "body": {"error": "Заявка уже успешно оплачена"},
                    },
                )
            ),
        ), patch(
            "services.receipt_ops_review.finalize_receipt_payfast_success",
            new=AsyncMock(),
        ) as finalize, patch(
            "services.receipt_ops_review._try_reconcile_payfast_settled",
            new=AsyncMock(),
        ) as reconcile:
            ok, err = await approve_receipt_and_send_to_payfast("O1", 1, bot=MagicMock())
        self.assertTrue(ok)
        self.assertIsNone(err)
        finalize.assert_awaited_once()
        reconcile.assert_not_awaited()

    async def test_allow_resend_when_ops_pending_cleared(self):
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "user_id": 99,
            "receipt_file": "r.pdf",
            "payment_snapshot": {"receipt_ops_pending": False},
            "required_receipt_type": 2,
        }
        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.db.is_receipt_ops_pending",
            return_value=False,
        ), patch(
            "services.receipt_ops_review.submit_receipt_to_payfast",
            new=AsyncMock(return_value=(OUTCOME_SUCCESS, 200, {})),
        ) as submit, patch(
            "services.receipt_ops_review.finalize_receipt_payfast_success",
            new=AsyncMock(),
        ) as finalize, patch(
            "services.receipt_ops_review._try_reconcile_payfast_settled",
            new=AsyncMock(),
        ) as reconcile:
            ok, err = await approve_receipt_and_send_to_payfast(
                "O1", 1, bot=MagicMock(), allow_resend=True
            )
        self.assertTrue(ok)
        self.assertIsNone(err)
        submit.assert_awaited_once()
        finalize.assert_awaited_once()
        reconcile.assert_not_awaited()


class FinalizeReceiptPayfastSuccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconciles_after_receipt_accepted(self):
        from services.receipt_ops_review import finalize_receipt_payfast_success

        order = {"order_id": "O1", "user_id": 1, "required_receipt_type": 2}
        pending = {**order, "status": "PENDING"}
        with patch(
            "services.db.mark_ops_alert_once",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.db.clear_receipt_ops_pending", new=AsyncMock()
        ) as clear, patch(
            "services.db.update_order_status", new=AsyncMock(return_value=True)
        ), patch(
            "services.db.get_order", new=AsyncMock(return_value=pending)
        ), patch(
            "services.order_ops_notify.notify_ops_order", new=AsyncMock()
        ), patch(
            "services.receipt_ops_review._try_reconcile_payfast_settled",
            new=AsyncMock(),
        ) as recon:
            await finalize_receipt_payfast_success(order, bot=None)
        clear.assert_awaited_once_with("O1")
        recon.assert_awaited_once_with("O1")


class RejectReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_reject_cancels_and_bans(self):
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "user_id": 99,
            "payment_snapshot": {"receipt_ops_pending": True},
        }
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.db.is_receipt_ops_pending",
            return_value=True,
        ), patch(
            "services.merchant_api_helpers.cancel_payin_for_order",
            new=AsyncMock(return_value={"status": 200}),
        ) as cancel_pf, patch(
            "services.db.update_order_status",
            new=AsyncMock(return_value=True),
        ) as upd, patch(
            "services.db.clear_receipt_ops_pending",
            new=AsyncMock(),
        ), patch(
            "services.db.ban_user",
            new=AsyncMock(return_value=True),
        ) as ban, patch(
            "services.menu.main_menu_keyboard",
            new=AsyncMock(return_value=None),
        ):
            ok, err = await reject_receipt_ban_and_cancel("O1", 42, bot=bot)
        self.assertTrue(ok)
        self.assertIsNone(err)
        cancel_pf.assert_awaited_once()
        upd.assert_awaited_once_with("O1", "CANCELED")
        ban.assert_awaited_once()
        bot.send_message.assert_awaited_once()

    async def test_reject_payin_rail_skips_merchant_cancel(self):
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "user_id": 99,
            "payin_requisite_id": 12,
            "payment_snapshot": {"receipt_ops_pending": True},
        }
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.db.is_receipt_ops_pending",
            return_value=True,
        ), patch(
            "services.merchant_api_helpers.cancel_payin_for_order",
            new=AsyncMock(return_value={"status": 200}),
        ) as cancel_pf, patch(
            "services.db.update_order_status",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.db.clear_receipt_ops_pending",
            new=AsyncMock(),
        ), patch(
            "services.db.ban_user",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.menu.main_menu_keyboard",
            new=AsyncMock(return_value=None),
        ):
            ok, err = await reject_receipt_ban_and_cancel("O1", 42, bot=bot)
        self.assertTrue(ok)
        self.assertIsNone(err)
        cancel_pf.assert_not_awaited()

    async def test_reject_keeps_button_when_local_cancel_is_refused(self):
        order = {
            "order_id": "O1",
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "user_id": 99,
            "payment_snapshot": {"receipt_ops_pending": True},
        }
        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.db.is_receipt_ops_pending",
            return_value=True,
        ), patch(
            "services.merchant_api_helpers.cancel_payin_for_order",
            new=AsyncMock(return_value={"status": 200}),
        ), patch(
            "services.db.update_order_status",
            new=AsyncMock(return_value=False),
        ), patch(
            "services.db.clear_receipt_ops_pending",
            new=AsyncMock(),
        ) as clear, patch(
            "services.db.ban_user",
            new=AsyncMock(),
        ) as ban:
            ok, err = await reject_receipt_ban_and_cancel("O1", 42, bot=MagicMock())
        self.assertFalse(ok)
        self.assertEqual(err, "Не удалось отменить заявку — повторите")
        clear.assert_not_awaited()
        ban.assert_not_awaited()

    async def test_reject_idempotent_when_already_closed(self):
        order = {
            "order_id": "O1",
            "status": "CANCELED",
            "direction": "buy",
            "user_id": 99,
            "payment_snapshot": {"receipt_ops_pending": False},
        }
        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.db.is_receipt_ops_pending",
            return_value=False,
        ), patch(
            "services.db.is_user_banned",
            new=AsyncMock(return_value=(True, "x", "hard")),
        ):
            ok, err = await reject_receipt_ban_and_cancel("O1", 42, bot=MagicMock())
        self.assertFalse(ok)
        self.assertEqual(err, "Заявка уже закрыта")

    async def test_reject_retries_ban_after_midflight_fail(self):
        order = {
            "order_id": "O1",
            "status": "CANCELED",
            "direction": "buy",
            "user_id": 99,
            "payment_snapshot": {},
        }
        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.db.is_receipt_ops_pending",
            return_value=False,
        ), patch(
            "services.db.is_user_banned",
            new=AsyncMock(return_value=(False, None, "hard")),
        ), patch(
            "services.db.ban_user",
            new=AsyncMock(return_value=True),
        ) as ban:
            ok, err = await reject_receipt_ban_and_cancel("O1", 8718118115, bot=MagicMock())
        self.assertTrue(ok)
        self.assertIsNone(err)
        ban.assert_awaited_once()
        self.assertEqual(ban.await_args.kwargs["operator_id"], 8718118115)


class RouteClientReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_hold_does_not_send_to_payfast(self):
        from services.receipt_ops_review import route_client_receipt

        order = {
            "order_id": "O1",
            "user_id": 5,
            "direction": "buy",
            "required_receipt_type": 2,
            "status": "AWAITING_CHECK",
        }
        with patch("services.db.merge_order_payment_snapshot", new=AsyncMock()), patch(
            "services.db.extend_order_expires_at", new=AsyncMock()
        ), patch(
            "services.receipt_ops_review.inspect_receipt_pdf_meta", return_value=None
        ), patch(
            "services.receipt_ops_review._build_receipt_risk_note",
            new=AsyncMock(return_value=("note", "OK")),
        ), patch(
            "services.receipt_ops_review.should_hold_receipt_for_ops",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.receipt_ops_review._order_is_payin_rail", return_value=False
        ), patch(
            "services.receipt_ops_review.hold_receipt_for_ops_review", new=AsyncMock()
        ) as hold, patch(
            "services.receipt_ops_review.submit_receipt_to_payfast", new=AsyncMock()
        ) as submit:
            result = await route_client_receipt(order, "a.pdf", bot=None)
        hold.assert_awaited_once()
        submit.assert_not_awaited()
        self.assertEqual(result["route"], "held")
        self.assertEqual(result["status"], "AWAITING_CHECK")

    async def test_reki_pdf_goes_to_reki_not_payfast(self):
        from services.receipt_ops_review import route_client_receipt

        order = {
            "order_id": "O1",
            "user_id": 5,
            "direction": "buy",
            "required_receipt_type": 2,
            "status": "AWAITING_CHECK",
            "payment_snapshot": {
                "reki_payfast_id": "d84a6631-28dc-4afd-aa52-533a5b5bdaa3",
            },
        }
        send = AsyncMock(return_value=True)
        with patch("services.db.merge_order_payment_snapshot", new=AsyncMock()), patch(
            "services.db.extend_order_expires_at", new=AsyncMock()
        ), patch(
            "services.receipt_ops_review.inspect_receipt_pdf_meta", return_value=None
        ), patch(
            "services.receipt_ops_review._build_receipt_risk_note",
            new=AsyncMock(return_value=("note", "OK")),
        ), patch(
            "services.receipt_ops_review.should_hold_receipt_for_ops",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.receipt_ops_review.hold_receipt_for_ops_review", new=AsyncMock()
        ) as hold, patch(
            "services.receipt_ops_review.submit_receipt_to_payfast", new=AsyncMock()
        ) as submit, patch(
            "services.receipt_ops_review.deliver_video_to_payfast_appeals", new=AsyncMock()
        ) as video, patch(
            "services.receipt_ops_review._receipt_local_path", return_value="a.pdf"
        ), patch(
            "services.reki_request.send_receipt_to_reki", new=send
        ), patch(
            "services.db.update_order_status", new=AsyncMock(return_value=True)
        ), patch(
            "services.order_ops_notify.notify_ops_order", new=AsyncMock()
        ):
            result = await route_client_receipt(order, "a.pdf", bot=None)
        send.assert_awaited_once()
        self.assertEqual(send.await_args.args[0], "d84a6631-28dc-4afd-aa52-533a5b5bdaa3")
        self.assertFalse(send.await_args.kwargs["video"])
        submit.assert_not_awaited()
        video.assert_not_awaited()
        hold.assert_not_awaited()
        self.assertEqual(result["route"], "reki_sent")
        self.assertEqual(result["status"], "PENDING")

    async def test_reki_video_is_not_appeals(self):
        from services.receipt_ops_review import route_client_receipt

        order = {
            "order_id": "O1",
            "user_id": 5,
            "direction": "buy",
            "required_receipt_type": 3,
            "status": "AWAITING_CHECK",
            "payment_snapshot": {
                "reki_payfast_id": "ce8c63d1-5230-47d6-b8e7-4610d4b6991b",
            },
        }
        send = AsyncMock(return_value=True)
        with patch("services.db.merge_order_payment_snapshot", new=AsyncMock()), patch(
            "services.db.extend_order_expires_at", new=AsyncMock()
        ), patch(
            "services.receipt_ops_review.inspect_receipt_pdf_meta", return_value=None
        ), patch(
            "services.receipt_ops_review._build_receipt_risk_note",
            new=AsyncMock(return_value=("note", "OK")),
        ), patch(
            "services.receipt_ops_review.should_hold_receipt_for_ops",
            new=AsyncMock(return_value=False),
        ), patch(
            "services.receipt_ops_review.submit_receipt_to_payfast", new=AsyncMock()
        ) as submit, patch(
            "services.receipt_ops_review.deliver_video_to_payfast_appeals", new=AsyncMock()
        ) as video, patch(
            "services.receipt_ops_review._receipt_local_path", return_value="clip.mp4"
        ), patch(
            "services.reki_request.send_receipt_to_reki", new=send
        ), patch(
            "services.db.update_order_status", new=AsyncMock(return_value=True)
        ), patch(
            "services.order_ops_notify.notify_ops_order", new=AsyncMock()
        ):
            result = await route_client_receipt(order, "clip.mp4", bot=None)
        self.assertTrue(send.await_args.kwargs["video"])
        submit.assert_not_awaited()
        video.assert_not_awaited()
        self.assertEqual(result["route"], "reki_sent")

    async def test_review_card_without_bot_uses_http(self):
        from services.order_ops_notify import notify_ops_receipt_review

        with patch(
            "services.order_ops_notify._admin_chat_id", return_value=-100
        ), patch(
            "services.order_ops_notify._resolve_buyer_stats",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.order_ops_notify._resolve_client_contact",
            new=AsyncMock(return_value={}),
        ), patch(
            "services.db.get_latest_device_signal_for_order",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.order_ops_notify._ensure_reuse_matches_on_order",
            new=AsyncMock(),
        ), patch(
            "services.order_ops_notify.send_telegram_message_http", return_value=True
        ) as send:
            await notify_ops_receipt_review(
                {"order_id": "O1", "direction": "buy", "user_id": 5, "status": "AWAITING_CHECK"},
                None,
                review_signature="sig",
            )
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], -100)
        self.assertIn("rcpt:approve:O1:sig", str(send.call_args.args[2]))
