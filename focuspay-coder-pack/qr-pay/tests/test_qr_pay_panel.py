"""Вкладка /qrpay: что видит владелец и что делают кнопки."""
from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

from services import qr_pay_panel as panel


def run(coro):
    return asyncio.run(coro)


STATS = {
    "paid": 3,
    "in_flight": 1,
    "failed": 2,
    "refunded": 0,
    "paid_rub": 3090.0,
}


def render(
    availability_state,
    *,
    enabled=True,
    configured=True,
    threshold=10.0,
    allowlist=(),
):
    with patch(
        "services.qr_pay_status.availability", AsyncMock(return_value=availability_state)
    ), patch("services.qr_pay_panel.qr_pay_enabled", return_value=enabled), patch(
        "services.qr_pay_panel.qr_pay_min_merchant_usdt", return_value=threshold
    ), patch(
        "services.qr_pay_panel.qr_pay_low_balance_allowlist", return_value=allowlist
    ), patch("services.finance666_client.configured", return_value=configured), patch(
        "services.qr_pay_panel._usage_stats", AsyncMock(return_value=STATS)
    ):
        return run(panel.build_panel_text())


class PanelTextTests(unittest.TestCase):
    def test_low_balance_states_qr_is_temporarily_off(self):
        text, state = render(
            {"available": False, "reason": "low_balance", "balance": 5.0, "threshold": 10.0}
        )
        self.assertIn("временно куары недоступны", text)
        self.assertIn("5.00 USDT", text)
        self.assertIn("Порог", text)
        self.assertTrue(state["enabled"])

    def test_healthy_balance_reports_working(self):
        text, _ = render(
            {"available": True, "reason": None, "balance": 250.0, "threshold": 10.0}
        )
        self.assertIn("работает", text)
        self.assertIn("250.00 USDT", text)

    def test_disabled_flag_shown_even_with_money(self):
        text, state = render(
            {"available": False, "reason": "disabled", "balance": 250.0},
            enabled=False,
        )
        self.assertIn("выключена", text)
        self.assertFalse(state["enabled"])

    def test_missing_key_is_called_out(self):
        text, _ = render(
            {"available": False, "reason": "no_key", "balance": None},
            configured=False,
        )
        self.assertIn("FINANCE666_API_KEY", text)

    def test_unknown_balance_does_not_claim_a_number(self):
        text, _ = render({"available": True, "reason": None, "balance": None})
        self.assertIn("Баланс недоступен", text)

    def test_daily_stats_included(self):
        text, _ = render({"available": True, "reason": None, "balance": 250.0})
        self.assertIn("За 24 часа", text)
        self.assertIn("3 090.00", text)


class AllowlistLineTests(unittest.TestCase):
    def test_exception_account_is_named(self):
        text, _ = render(
            {
                "available": False,
                "reason": "low_balance",
                "balance": 5.0,
                "threshold": 10.0,
            },
            allowlist=("alwaeszs",),
        )
        self.assertIn("@alwaeszs", text)
        self.assertIn("временно куары недоступны", text)
        self.assertIn("кроме исключений", text)

    def test_no_exceptions_stated_explicitly(self):
        text, _ = render(
            {"available": True, "reason": None, "balance": 250.0, "threshold": 10.0}
        )
        self.assertIn("Исключения из порога: нет", text)


class PanelActionTests(unittest.TestCase):
    def test_toggle_writes_opposite_flag(self):
        save = AsyncMock()
        with patch("services.qr_pay_panel.save_settings", save), patch(
            "services.qr_pay_panel.qr_pay_enabled", return_value=False
        ):
            run(panel.apply_panel_action("qrpay:toggle"))
        save.assert_awaited_once_with({"qr_pay_enabled": True})

    def test_markup_step_saved(self):
        save = AsyncMock()
        with patch("services.qr_pay_panel.save_settings", save):
            notice = run(panel.apply_panel_action("qrpay:markup:5.0"))
        save.assert_awaited_once_with({"qr_pay_markup_pct": 5.0})
        self.assertIn("5%", notice)

    def test_refresh_drops_balance_cache(self):
        with patch("services.qr_pay_status.invalidate") as invalidate:
            run(panel.apply_panel_action("qrpay:refresh"))
        invalidate.assert_called_once()

    def test_unknown_action_is_ignored(self):
        with patch("services.qr_pay_panel.save_settings", AsyncMock()) as save:
            self.assertIsNone(run(panel.apply_panel_action("qrpay:wat")))
        save.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
