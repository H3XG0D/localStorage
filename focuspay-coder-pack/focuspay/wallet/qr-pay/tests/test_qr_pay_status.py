"""Доступность оплаты по QR по балансу платформы и порогу."""
from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

from services import qr_pay_status as status
from services.finance666_client import Finance666Error


def run(coro):
    return asyncio.run(coro)


def balance_reply(available):
    return {
        "success": True,
        "available_balance": available,
        "hold_balance": 0.0,
        "currency": "USDT",
    }


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        status.invalidate()
        self.addCleanup(status.invalidate)
        self.enabled = patch("services.qr_pay_status.qr_pay_enabled", return_value=True)
        self.threshold = patch(
            "services.qr_pay_status.qr_pay_min_merchant_usdt", return_value=10.0
        )
        self.configured = patch("services.finance666_client.configured", return_value=True)
        for p in (self.enabled, self.threshold, self.configured):
            p.start()
            self.addCleanup(p.stop)

    def test_balance_below_threshold_blocks_payments(self):
        with patch(
            "services.finance666_client.merchant_balance",
            AsyncMock(return_value=balance_reply(5.0)),
        ):
            state = run(status.availability(force=True))
        self.assertFalse(state["available"])
        self.assertEqual(state["reason"], "low_balance")
        self.assertEqual(state["balance"], 5.0)

    def test_balance_at_threshold_is_allowed(self):
        with patch(
            "services.finance666_client.merchant_balance",
            AsyncMock(return_value=balance_reply(10.0)),
        ):
            state = run(status.availability(force=True))
        self.assertTrue(state["available"])

    def test_disabled_flag_blocks_without_network(self):
        with patch("services.qr_pay_status.qr_pay_enabled", return_value=False), patch(
            "services.finance666_client.merchant_balance", AsyncMock()
        ) as call:
            state = run(status.availability())
        self.assertFalse(state["available"])
        self.assertEqual(state["reason"], "disabled")
        call.assert_not_awaited()

    def test_missing_key_blocks(self):
        with patch("services.finance666_client.configured", return_value=False):
            state = run(status.availability())
        self.assertFalse(state["available"])
        self.assertEqual(state["reason"], "no_key")

    def test_unreachable_platform_does_not_block(self):
        """Баланс неизвестен — решение оставляем платформе на check."""
        with patch(
            "services.finance666_client.merchant_balance",
            AsyncMock(side_effect=Finance666Error("timeout")),
        ):
            state = run(status.availability(force=True))
        self.assertTrue(state["available"])
        self.assertIsNone(state["balance"])

    def test_balance_is_cached_between_calls(self):
        call = AsyncMock(return_value=balance_reply(50.0))
        with patch("services.finance666_client.merchant_balance", call):
            run(status.availability(force=True))
            run(status.availability())
            run(status.availability())
        self.assertEqual(call.await_count, 1)
        self.assertEqual(status.cached_balance(), 50.0)

    def test_invalidate_forces_refetch(self):
        call = AsyncMock(return_value=balance_reply(50.0))
        with patch("services.finance666_client.merchant_balance", call):
            run(status.availability(force=True))
            status.invalidate()
            run(status.availability())
        self.assertEqual(call.await_count, 2)


class LowBalanceAllowlistTests(unittest.TestCase):
    """Пока пул ниже порога, платить может только тестовый аккаунт."""

    def setUp(self):
        status.invalidate()
        self.addCleanup(status.invalidate)
        patches = (
            patch("services.qr_pay_status.qr_pay_enabled", return_value=True),
            patch("services.qr_pay_status.qr_pay_min_merchant_usdt", return_value=10.0),
            patch("services.finance666_client.configured", return_value=True),
            patch(
                "services.qr_pay_status.qr_pay_low_balance_allowlist",
                return_value=("alwaeszs",),
            ),
            patch(
                "services.finance666_client.merchant_balance",
                AsyncMock(return_value=balance_reply(5.0)),
            ),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_allowlisted_username_passes_low_balance(self):
        state = run(status.availability(force=True, user_id=7, username="alwaeszs"))
        self.assertTrue(state["available"])
        self.assertEqual(state["reason"], "low_balance_allowlisted")

    def test_at_sign_and_case_are_ignored(self):
        state = run(status.availability(force=True, user_id=7, username="@AlwaesZS"))
        self.assertTrue(state["available"])

    def test_everyone_else_is_still_blocked(self):
        state = run(status.availability(force=True, user_id=8, username="someoneelse"))
        self.assertFalse(state["available"])
        self.assertEqual(state["reason"], "low_balance")

    def test_anonymous_request_is_blocked(self):
        state = run(status.availability(force=True))
        self.assertFalse(state["available"])

    def test_numeric_id_entry_also_matches(self):
        with patch(
            "services.qr_pay_status.qr_pay_low_balance_allowlist", return_value=("12345",)
        ):
            allowed = run(status.availability(force=True, user_id=12345, username=None))
            denied = run(status.availability(force=True, user_id=999, username=None))
        self.assertTrue(allowed["available"])
        self.assertFalse(denied["available"])

    def test_button_visible_only_for_allowlisted_account(self):
        run(status.availability(force=True, user_id=7, username="alwaeszs"))
        self.assertTrue(status.looks_available(7, "alwaeszs"))
        self.assertFalse(status.looks_available(8, "someoneelse"))

    def test_disabled_flag_beats_allowlist(self):
        with patch("services.qr_pay_status.qr_pay_enabled", return_value=False):
            state = run(status.availability(user_id=7, username="alwaeszs"))
        self.assertFalse(state["available"])
        self.assertEqual(state["reason"], "disabled")


class AllowlistParsingTests(unittest.TestCase):
    def test_comma_string_is_normalized(self):
        from services.runtime_settings import qr_pay_low_balance_allowlist

        with patch(
            "services.runtime_settings.get_settings_sync",
            return_value={"qr_pay_low_balance_allowlist": " @Alwaeszs , 12345 ;@Bob "},
        ):
            self.assertEqual(
                qr_pay_low_balance_allowlist(), ("alwaeszs", "12345", "bob")
            )

    def test_empty_setting_means_no_exceptions(self):
        from services.runtime_settings import qr_pay_low_balance_allowlist

        with patch(
            "services.runtime_settings.get_settings_sync",
            return_value={"qr_pay_low_balance_allowlist": ""},
        ):
            self.assertEqual(qr_pay_low_balance_allowlist(), ())


class KeyboardHintTests(unittest.TestCase):
    def setUp(self):
        status.invalidate()
        self.addCleanup(status.invalidate)

    def test_button_hidden_when_last_balance_was_low(self):
        with patch("services.qr_pay_status.qr_pay_enabled", return_value=True), patch(
            "services.finance666_client.configured", return_value=True
        ), patch(
            "services.qr_pay_status.qr_pay_min_merchant_usdt", return_value=10.0
        ), patch(
            "services.finance666_client.merchant_balance",
            AsyncMock(return_value=balance_reply(5.0)),
        ):
            run(status.availability(force=True))
            self.assertFalse(status.looks_available())

    def test_button_shown_before_first_balance_check(self):
        with patch("services.qr_pay_status.qr_pay_enabled", return_value=True), patch(
            "services.finance666_client.configured", return_value=True
        ):
            self.assertTrue(status.looks_available())

    def test_button_hidden_when_disabled(self):
        with patch("services.qr_pay_status.qr_pay_enabled", return_value=False):
            self.assertFalse(status.looks_available())


if __name__ == "__main__":
    unittest.main()
