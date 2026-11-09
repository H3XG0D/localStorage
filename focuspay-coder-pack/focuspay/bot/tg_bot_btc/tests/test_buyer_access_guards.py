"""Тесты гейтов: конверсия, кулдаун, подозрительный аккаунт, подписи areview."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from services.buyer_access_guards import (
    PAYFAST_RECOVERY_BUFFER_MINUTES,
    PAYMENT_WINDOW_MINUTES,
    REASON_FRESH_ACCOUNT,
    REASON_NO_USERNAME,
    REASON_USERNAME_CHANGED,
    UNPAID_COOLDOWN_MINUTES,
    calculate_payfast_deadlines,
    cancel_cooldown_remaining_sec,
    clamp_payin_expires_at,
    compute_conversion_pct,
    format_cancel_followup_message,
    format_conversion_line,
    format_cooldown_message,
    format_expire_followup_message,
    format_low_conversion_warning,
    format_payment_rules_block,
    format_requisites_closed_message,
    format_soft_ban_no_requisites_message,
    is_low_conversion,
    is_suspicious_account,
    payfast_requisites_are_closed,
    soft_ban_blocks_buy_requisites,
)
from services.callback_signatures import (
    sign_account_review,
    verify_account_review_signature,
)
from handlers.exchange_flow import _payfast_cancellation_is_locked_for_order


class ConversionFormulaTests(unittest.TestCase):
    def test_zero_denom_is_none(self):
        self.assertIsNone(compute_conversion_pct(0, 0))

    def test_basic_pct(self):
        self.assertEqual(compute_conversion_pct(2, 2), 50.0)
        self.assertEqual(compute_conversion_pct(1, 0), 100.0)

    def test_format_no_data(self):
        text = format_conversion_line({"paid": 0, "failed": 0, "conversion_pct": None})
        self.assertIn("нет данных", text)

    def test_format_with_data(self):
        text = format_conversion_line({"paid": 3, "failed": 7, "conversion_pct": 30.0})
        self.assertIn("3", text)
        self.assertIn("10", text)
        self.assertIn("30", text)
        self.assertIn("Процент успеха", text)

    def test_low_conversion_warning(self):
        self.assertIsNone(
            format_low_conversion_warning({"paid": 5, "failed": 1, "conversion_pct": 83.0})
        )
        warn = format_low_conversion_warning(
            {"paid": 1, "failed": 5, "conversion_pct": 16.7}
        )
        self.assertIsNotNone(warn)
        self.assertIn("часто берёте", warn)
        self.assertTrue(is_low_conversion({"paid": 0, "failed": 2, "conversion_pct": 0.0}))
        self.assertFalse(is_low_conversion({"paid": 0, "failed": 1, "conversion_pct": 0.0}))


class CooldownTests(unittest.TestCase):
    def test_none_when_no_cancel(self):
        self.assertIsNone(cancel_cooldown_remaining_sec(None))

    def test_active_cooldown(self):
        now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
        last = now - timedelta(minutes=10)
        rem = cancel_cooldown_remaining_sec(last, now=now, minutes=30)
        self.assertIsNotNone(rem)
        self.assertAlmostEqual(rem, 20 * 60, delta=2)

    def test_expired_cooldown(self):
        now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
        last = now - timedelta(minutes=31)
        self.assertIsNone(cancel_cooldown_remaining_sec(last, now=now, minutes=30))

    def test_cooldown_message(self):
        msg = format_cooldown_message(90, {"paid": 1, "failed": 1, "conversion_pct": 50.0})
        self.assertIn("заблокирован", msg.lower())
        self.assertIn("не совершили оплату", msg.lower())
        self.assertIn("50", msg)

    def test_cancel_followup(self):
        msg = format_cancel_followup_message({"paid": 0, "failed": 1, "conversion_pct": 0.0})
        self.assertIn(str(UNPAID_COOLDOWN_MINUTES), msg)
        self.assertIn("открывали реквизиты", msg.lower())

    def test_expire_followup(self):
        msg = format_expire_followup_message({"paid": 0, "failed": 2, "conversion_pct": 0.0})
        self.assertIn("истекло", msg.lower())
        self.assertIn(str(UNPAID_COOLDOWN_MINUTES), msg)
        self.assertIn("часто берёте", msg.lower())

    def test_payment_rules(self):
        msg = format_payment_rules_block()
        self.assertIn(str(PAYMENT_WINDOW_MINUTES - PAYFAST_RECOVERY_BUFFER_MINUTES), msg)
        self.assertIn(str(PAYFAST_RECOVERY_BUFFER_MINUTES), msg)
        self.assertIn(
            "FocusPay может принять уже отправленный перевод ещё "
            f"<b>{PAYFAST_RECOVERY_BUFFER_MINUTES}</b> минут, после средства будут утеряны.",
            msg,
        )
        self.assertIn("Не закрывайте", msg)
        self.assertIn("МТС Банка", msg)
        self.assertIn("Уралсиба", msg)
        self.assertIn("не принимаем", msg)

    def test_payment_rules_use_actual_internal_deadline(self):
        now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        msg = format_payment_rules_block(now + timedelta(minutes=8), now=now)

        self.assertIn("8", msg)
        self.assertNotIn("13", msg)

    def test_payfast_deadlines_without_provider_deadline(self):
        now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        deadlines = calculate_payfast_deadlines(None, now=now)

        self.assertFalse(deadlines.merchant_deadline_from_provider)
        self.assertEqual(deadlines.merchant_expires_at, now + timedelta(minutes=20))
        self.assertEqual(deadlines.requisites_expires_at, now + timedelta(minutes=13))
        self.assertFalse(deadlines.merchant_window_too_short)

    def test_payfast_deadlines_with_provider_deadline(self):
        now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        merchant_end = now + timedelta(minutes=15)
        deadlines = calculate_payfast_deadlines(merchant_end, now=now)

        self.assertTrue(deadlines.merchant_deadline_from_provider)
        self.assertEqual(deadlines.merchant_expires_at, merchant_end)
        self.assertEqual(deadlines.requisites_expires_at, now + timedelta(minutes=8))

    def test_too_short_provider_deadline_is_rejected(self):
        now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        deadlines = calculate_payfast_deadlines(now + timedelta(minutes=7), now=now)

        self.assertTrue(deadlines.merchant_window_too_short)

    def test_recovery_window_and_message(self):
        now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        requisites_end = now - timedelta(seconds=1)
        merchant_end = now + timedelta(minutes=7)

        self.assertTrue(
            payfast_requisites_are_closed(requisites_end, merchant_end, now=now)
        )
        self.assertFalse(
            payfast_requisites_are_closed(requisites_end, merchant_end, now=merchant_end)
        )
        self.assertIn("Реквизиты закрыты", format_requisites_closed_message(7 * 60))
        self.assertIn("7", format_requisites_closed_message(7 * 60))

    def test_bot_cancel_is_locked_for_video_recheck(self):
        self.assertTrue(
            _payfast_cancellation_is_locked_for_order({"required_receipt_type": 3})
        )

    def test_bot_cancel_is_not_locked_by_payfast_order_id(self):
        self.assertFalse(
            _payfast_cancellation_is_locked_for_order(
                {"direction": "buy", "merchant_order_id": "payfast-uuid"}
            )
        )
        self.assertFalse(
            _payfast_cancellation_is_locked_for_order(
                {"direction": "sell", "merchant_order_id": "payfast-uuid"}
            )
        )
        self.assertFalse(
            _payfast_cancellation_is_locked_for_order({"direction": "buy"})
        )

    def test_bot_cancel_is_locked_during_payfast_recovery(self):
        now = datetime.now(timezone.utc)
        self.assertTrue(
            _payfast_cancellation_is_locked_for_order(
                {
                    "direction": "buy",
                    "expires_at": now - timedelta(seconds=1),
                    "payment_snapshot": {
                        "merchant_expires_at": (now + timedelta(minutes=7)).isoformat(),
                    },
                }
            )
        )

    def test_clamp_expires(self):
        now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
        long_end = now + timedelta(minutes=45)
        capped = clamp_payin_expires_at(long_end, now=now, window_minutes=20)
        self.assertEqual(capped, now + timedelta(minutes=20))
        short_end = now + timedelta(minutes=10)
        capped2 = clamp_payin_expires_at(short_end, now=now, window_minutes=20)
        self.assertEqual(capped2, short_end)
        capped3 = clamp_payin_expires_at(None, now=now, window_minutes=20)
        self.assertEqual(capped3, now + timedelta(minutes=20))


class SuspiciousAccountTests(unittest.TestCase):
    def test_paid_user_never_suspicious(self):
        user = {
            "username": None,
            "first_seen_at": datetime.now(tz=timezone.utc),
            "previous_username": "old",
            "account_review_status": "none",
        }
        self.assertEqual(is_suspicious_account(user, paid_count=1), [])

    def test_approved_skips(self):
        user = {
            "username": None,
            "first_seen_at": datetime.now(tz=timezone.utc),
            "account_review_status": "approved",
        }
        self.assertEqual(is_suspicious_account(user, paid_count=0), [])

    def test_no_username(self):
        user = {
            "username": None,
            "first_seen_at": datetime.now(tz=timezone.utc) - timedelta(days=10),
            "previous_username": None,
            "account_review_status": "none",
        }
        self.assertIn(REASON_NO_USERNAME, is_suspicious_account(user, 0))

    def test_fresh_account(self):
        user = {
            "username": "alice",
            "first_seen_at": datetime.now(tz=timezone.utc) - timedelta(hours=2),
            "previous_username": None,
            "account_review_status": "none",
        }
        self.assertIn(REASON_FRESH_ACCOUNT, is_suspicious_account(user, 0))

    def test_username_changed(self):
        user = {
            "username": "newname",
            "first_seen_at": datetime.now(tz=timezone.utc) - timedelta(days=10),
            "previous_username": "oldname",
            "account_review_status": "none",
        }
        self.assertIn(REASON_USERNAME_CHANGED, is_suspicious_account(user, 0))

    def test_clean_old_user(self):
        user = {
            "username": "alice",
            "first_name": "Alice",
            "first_seen_at": datetime.now(tz=timezone.utc) - timedelta(days=10),
            "previous_username": None,
            "account_review_status": "none",
        }
        self.assertEqual(
            is_suspicious_account(user, 0, has_avatar=True, first_name="Alice"),
            [],
        )


class AccountReviewSignatureTests(unittest.TestCase):
    def test_sign_verify(self):
        sig = sign_account_review(42)
        self.assertTrue(verify_account_review_signature(42, sig))
        self.assertFalse(verify_account_review_signature(43, sig))
        self.assertFalse(verify_account_review_signature(42, "deadbeef"))


class AccountReviewCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_approve_callback(self):
        from services.account_review_callbacks import account_review_callback_handler
        from services.callback_signatures import sign_account_review

        sig = sign_account_review(1001)
        query = MagicMock()
        query.message.chat_id = -100
        query.from_user.id = 1
        query.from_user.username = "admin"
        query.data = f"areview:ok:1001:{sig}"
        query.answer = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        query.message.reply_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()
        context.bot = MagicMock()

        with patch(
            "services.account_review_callbacks.config_rates.is_ops_group_chat",
            return_value=True,
        ), patch(
            "services.account_review_callbacks.config_rates.is_client_review_group_chat",
            return_value=False,
        ), patch(
            "services.account_review_callbacks.TELEGRAM_ADMIN_IDS",
            frozenset({1}),
        ), patch(
            "services.account_review_callbacks.approve_account_review",
            new=AsyncMock(return_value=(True, "ok")),
        ) as approve:
            await account_review_callback_handler(update, context)

        approve.assert_awaited_once()
        query.answer.assert_awaited()

    async def test_soft_block_callback(self):
        from services.account_review_callbacks import account_review_callback_handler
        from services.callback_signatures import sign_account_review

        sig = sign_account_review(1002)
        query = MagicMock()
        query.message.chat_id = -100
        query.from_user.id = 1
        query.from_user.username = "admin"
        query.data = f"areview:soft:1002:{sig}"
        query.answer = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        query.message.reply_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()
        context.bot = MagicMock()

        with patch(
            "services.account_review_callbacks.config_rates.is_ops_group_chat",
            return_value=False,
        ), patch(
            "services.account_review_callbacks.config_rates.is_client_review_group_chat",
            return_value=True,
        ), patch(
            "services.account_review_callbacks.TELEGRAM_ADMIN_IDS",
            frozenset({1}),
        ), patch(
            "services.account_review_callbacks.soft_block_account_review",
            new=AsyncMock(return_value=(True, "ok")),
        ) as soft:
            await account_review_callback_handler(update, context)

        soft.assert_awaited_once()
        query.answer.assert_awaited()


class AccountReviewClientCopyTests(unittest.TestCase):
    def test_pending_looks_like_no_requisites(self):
        from services.buyer_access_guards import format_account_review_pending_message

        msg = format_account_review_pending_message()
        self.assertIn("Нет реквизитов", msg)
        self.assertIn("оператору", msg)
        self.assertNotIn("Подозрительный", msg)
        self.assertNotIn("проверк", msg.lower())


class BuyerStatsBlockConversionTests(unittest.TestCase):
    def test_includes_conversion_line(self):
        from services.order_ops_notify import _format_buyer_stats_block

        block = _format_buyer_stats_block(
            {
                "paid_count": 2,
                "last_paid_at": None,
                "total_volume_rub": 1000.0,
                "payfast_taken": 10,
                "payfast_paid": 4,
                "payfast_failed": 6,
                "conversion_pct": 40.0,
            }
        )
        self.assertIn("Конверсия", block)
        self.assertIn("40", block)
        self.assertIn("4/10", block)
        self.assertIn("низкая", block)

    def test_first_order_no_data(self):
        from services.order_ops_notify import _format_buyer_stats_block

        block = _format_buyer_stats_block(
            {
                "paid_count": 0,
                "last_paid_at": None,
                "total_volume_rub": 0,
                "payfast_taken": 0,
                "payfast_paid": 0,
                "payfast_failed": 0,
                "conversion_pct": None,
            }
        )
        self.assertIn("первая заявка", block)


class DashPayfastBlockTests(unittest.IsolatedAsyncioTestCase):
    async def test_dash_contains_payfast_block(self):
        from datetime import datetime

        from services.owner_analytics import (
            AudiencePeriod,
            FunnelPeriod,
            MoneyPeriod,
            OwnerSnapshot,
            PayfastConversionPeriod,
        )
        from services.owner_dashboard import build_dash_text

        snap = OwnerSnapshot(
            fetched_at=datetime.now(),
            period_label="сегодня",
            period_days=1,
            money=MoneyPeriod(),
            audience=AudiencePeriod(),
            funnel=FunnelPeriod(),
            payfast_today=PayfastConversionPeriod(
                taken=10, paid=4, failed=6, conversion_pct=40.0, days=1
            ),
            payfast_30d=PayfastConversionPeriod(
                taken=100, paid=38, failed=62, conversion_pct=38.0, days=30
            ),
        )

        with patch(
            "services.owner_dashboard.fetch_owner_snapshot",
            new=AsyncMock(return_value=snap),
        ), patch(
            "services.owner_dashboard.fetch_hot_wallet_runway",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.owner_dashboard.fetch_autopilot_savings",
            new=AsyncMock(return_value=None),
        ):
            text = await build_dash_text(None)
        self.assertIn("[BUY] Конверсия", text)
        self.assertIn("сегодня", text)
        self.assertIn("30 дней", text)
        self.assertIn("40%", text)
        self.assertIn("38%", text)


class SoftBanRequisitesTests(unittest.IsolatedAsyncioTestCase):
    def test_soft_message_is_neutral(self):
        msg = format_soft_ban_no_requisites_message()
        self.assertIn("Нет реквизитов", msg)
        self.assertNotIn("блок", msg.lower())
        self.assertNotIn("заблокир", msg.lower())

    async def test_soft_blocks_buy(self):
        with patch(
            "services.db.is_user_banned",
            new=AsyncMock(return_value=(True, "ops", "soft")),
        ):
            self.assertTrue(await soft_ban_blocks_buy_requisites(1))

    async def test_hard_does_not_count_as_soft_block(self):
        with patch(
            "services.db.is_user_banned",
            new=AsyncMock(return_value=(True, "ops", "hard")),
        ):
            self.assertFalse(await soft_ban_blocks_buy_requisites(1))

    async def test_not_banned(self):
        with patch(
            "services.db.is_user_banned",
            new=AsyncMock(return_value=(False, None, "hard")),
        ):
            self.assertFalse(await soft_ban_blocks_buy_requisites(1))


if __name__ == "__main__":
    unittest.main()
