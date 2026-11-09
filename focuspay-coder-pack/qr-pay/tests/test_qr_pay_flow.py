"""Сценарий оплаты по QR: допуск кода, подтверждение, применение итога."""
from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

from services import qr_pay_flow as flow
from services.finance666_client import Finance666Error, parse_payment
from services.qr_pay_wallet import QrPayError


def run(coro):
    return asyncio.run(coro)


def payment(group, code, *, is_final=True, **extra):
    data = {
        "transaction_id": "tx-1",
        "merchant_transaction_id": "qr-1",
        "status": {"group": group, "code": code, "is_final": is_final},
        "updated_at": "2026-08-23T12:00:00Z",
        "amount_in_currency": 1000.0,
        "payee_name": "ЖКХ Москва",
    }
    data.update(extra)
    return parse_payment(data)


CHECKED = payment("PROCESSING", "CHECKED", is_final=False, expires_at="2026-08-23T12:00:30Z")

# Отличает «строку не передали» от «платежа нет в базе».
_DEFAULT_ROW = object()


class StartCheckTests(unittest.TestCase):
    def setUp(self):
        self.configured = patch("services.finance666_client.configured", return_value=True)
        self.availability = patch(
            "services.qr_pay_status.availability",
            AsyncMock(return_value={"available": True, "reason": None, "balance": 100.0}),
        )
        self.configured.start()
        self.availability.start()
        self.addCleanup(self.configured.stop)
        self.addCleanup(self.availability.stop)

    def test_non_sbp_code_never_reaches_api(self):
        with patch("services.finance666_client.qr_check", AsyncMock()) as qr_check:
            with self.assertRaises(QrPayError) as ctx:
                run(flow.start_check(user_id=1, qr_code="https://evil.example/pay"))
        qr_check.assert_not_awaited()
        self.assertIn("не QR-код СБП", str(ctx.exception))

    def test_disabled_feature_rejects_before_api(self):
        unavailable = {"available": False, "reason": "disabled", "balance": None}
        with patch(
            "services.qr_pay_status.availability", AsyncMock(return_value=unavailable)
        ), patch("services.finance666_client.qr_check", AsyncMock()) as qr_check:
            with self.assertRaises(QrPayError):
                run(flow.start_check(user_id=1, qr_code="https://qr.nspk.ru/AD1"))
        qr_check.assert_not_awaited()

    def test_low_platform_balance_shows_temporary_notice(self):
        low = {
            "available": False,
            "reason": "low_balance",
            "balance": 5.0,
            "threshold": 10.0,
        }
        with patch(
            "services.qr_pay_status.availability", AsyncMock(return_value=low)
        ), patch("services.finance666_client.qr_check", AsyncMock()) as qr_check:
            with self.assertRaises(QrPayError) as ctx:
                run(flow.start_check(user_id=1, qr_code="https://qr.nspk.ru/AD1"))
        qr_check.assert_not_awaited()
        self.assertIn("недоступна", str(ctx.exception))

    def test_not_payable_status_rejected(self):
        declined = payment("DECLINED", "QR_EXPIRED")
        with patch("services.finance666_client.qr_check", AsyncMock(return_value=declined)), patch(
            "services.qr_pay_wallet.record_check", AsyncMock()
        ) as record:
            with self.assertRaises(QrPayError):
                run(flow.start_check(user_id=1, qr_code="https://qr.nspk.ru/AD1"))
        record.assert_not_awaited()

    def test_platform_without_funds_warns_ops_and_rejects(self):
        poor = payment(
            "PROCESSING", "CHECKED", is_final=False, is_balance_sufficient=False
        )
        with patch("services.finance666_client.qr_check", AsyncMock(return_value=poor)), patch(
            "services.qr_pay_flow.ops_notify"
        ) as ops, patch("services.qr_pay_wallet.record_check", AsyncMock()) as record:
            with self.assertRaises(QrPayError):
                run(flow.start_check(user_id=1, qr_code="https://qr.nspk.ru/AD1"))
        ops.assert_called_once()
        record.assert_not_awaited()

    def test_api_failure_does_not_leak_details(self):
        with patch(
            "services.finance666_client.qr_check",
            AsyncMock(side_effect=Finance666Error("boom api_key leaked")),
        ):
            with self.assertRaises(QrPayError) as ctx:
                run(flow.start_check(user_id=1, qr_code="https://qr.nspk.ru/AD1"))
        self.assertNotIn("api_key", str(ctx.exception))

    def test_account_is_passed_to_the_availability_gate(self):
        """Исключение из порога работает по аккаунту, значит он должен доехать до гейта."""
        gate = AsyncMock(return_value={"available": False, "reason": "low_balance", "balance": 5.0, "threshold": 10.0})
        with patch("services.qr_pay_status.availability", gate):
            with self.assertRaises(QrPayError):
                run(
                    flow.start_check(
                        user_id=77, username="alwaeszs", qr_code="https://qr.nspk.ru/AD1"
                    )
                )
        gate.assert_awaited_once_with(user_id=77, username="alwaeszs")

    def test_checked_code_returns_amount_with_markup(self):
        row = {
            "merchant_transaction_id": "qr-1",
            "payee_name": "ЖКХ Москва",
            "amount_rub": 1000.0,
            "charged_rub": 1030.0,
            "markup_pct": 3.0,
            "expires_at": None,
        }
        with patch("services.finance666_client.qr_check", AsyncMock(return_value=CHECKED)), patch(
            "services.qr_pay_wallet.record_check", AsyncMock(return_value=row)
        ):
            result = run(flow.start_check(user_id=1, qr_code="https://qr.nspk.ru/AD1"))
        self.assertEqual(result["charged_rub"], 1030.0)
        self.assertEqual(result["payment_id"], "qr-1")


class ConfirmPayTests(unittest.TestCase):
    RESERVED = {
        "merchant_transaction_id": "qr-1",
        "provider_transaction_id": "tx-1",
        "user_id": 500,
        "charged_rub": 1030.0,
        "local_status": "RESERVED",
    }

    def _confirm(self, *, pay_result=None, pay_error=None, reserved=None):
        reserve = AsyncMock(return_value=reserved if reserved is not None else self.RESERVED)
        qr_pay = AsyncMock(return_value=pay_result, side_effect=pay_error)
        self.release = AsyncMock(return_value=None)
        self.outcome = AsyncMock(return_value=None)
        with patch("services.qr_pay_wallet.reserve", reserve), patch(
            "services.finance666_client.qr_pay", qr_pay
        ), patch("services.qr_pay_wallet.release", self.release), patch(
            "services.qr_pay_flow.apply_outcome", self.outcome
        ), patch("services.qr_pay_flow.ops_notify"):
            return run(flow.confirm_pay(user_id=500, payment_id="qr-1"))

    def test_success_reports_paid(self):
        result = self._confirm(pay_result=payment("SUCCEEDED", "SUCCESS"))
        self.assertEqual(result["state"], "paid")
        self.release.assert_not_awaited()

    def test_declined_keeps_money_and_raises(self):
        with self.assertRaises(QrPayError):
            self._confirm(pay_result=payment("DECLINED", "PAYEE_REJECTED"))
        self.outcome.assert_awaited()

    def test_processing_leaves_reserve_in_place(self):
        result = self._confirm(
            pay_result=payment("PROCESSING", "PAYMENT_IN_PROGRESS", is_final=False)
        )
        self.assertEqual(result["state"], "processing")
        self.release.assert_not_awaited()

    def test_network_failure_keeps_reserve_for_webhook(self):
        result = self._confirm(pay_error=Finance666Error("timeout"))
        self.assertEqual(result["state"], "processing")
        self.release.assert_not_awaited()
        self.outcome.assert_not_awaited()

    def test_platform_out_of_funds_releases_reserve(self):
        with self.assertRaises(QrPayError):
            self._confirm(pay_result=payment("DECLINED", "MERCHANT_INSUFFICIENT_FUNDS"))
        self.release.assert_awaited_once_with("qr-1")

    def test_missing_provider_id_releases_reserve(self):
        broken = dict(self.RESERVED, provider_transaction_id=None)
        with self.assertRaises(QrPayError):
            self._confirm(pay_result=payment("SUCCEEDED", "SUCCESS"), reserved=broken)
        self.release.assert_awaited_once_with("qr-1")


class ApplyOutcomeTests(unittest.TestCase):
    ROW = {
        "merchant_transaction_id": "qr-1",
        "user_id": 500,
        "charged_rub": 1030.0,
        "amount_rub": 1000.0,
        "payee_name": "ЖКХ Москва",
        "local_status": "RESERVED",
    }

    def _apply(self, payment_obj, *, applied=True, row=_DEFAULT_ROW):
        self.settle = AsyncMock(return_value=dict(self.ROW, local_status="SETTLED"))
        self.release = AsyncMock(return_value=dict(self.ROW, local_status="RELEASED"))
        self.refund = AsyncMock(return_value=dict(self.ROW, local_status="REFUNDED"))
        self.user_notify = MagicMock()
        self.ops = MagicMock()
        with patch(
            "services.qr_pay_wallet.apply_provider_status",
            AsyncMock(return_value=(self.ROW if row is _DEFAULT_ROW else row, applied)),
        ), patch("services.qr_pay_wallet.settle", self.settle), patch(
            "services.qr_pay_wallet.release", self.release
        ), patch("services.qr_pay_wallet.refund", self.refund), patch(
            "services.qr_pay_flow._user_notify", self.user_notify
        ), patch("services.qr_pay_flow.ops_notify", self.ops):
            return run(flow.apply_outcome("qr-1", payment_obj))

    def test_success_settles_and_notifies_client(self):
        self._apply(payment("SUCCEEDED", "SUCCESS"))
        self.settle.assert_awaited_once_with("qr-1")
        self.user_notify.assert_called_once()

    def test_refund_returns_money_and_warns_ops(self):
        self._apply(payment("REFUNDED", "REFUND"))
        self.refund.assert_awaited_once_with("qr-1")
        self.ops.assert_called_once()
        self.user_notify.assert_called_once()

    def test_failure_releases_reserve(self):
        self._apply(payment("FAILED", "PROVIDER_ERROR"))
        self.release.assert_awaited_once_with("qr-1")
        self.ops.assert_called_once()

    def test_declined_releases_without_ops_alert(self):
        self._apply(payment("DECLINED", "PAYEE_REJECTED"))
        self.release.assert_awaited_once_with("qr-1")
        self.ops.assert_not_called()

    def test_unknown_final_group_keeps_reserve_and_asks_ops(self):
        self._apply(payment("WAT", "MYSTERY"))
        self.settle.assert_not_awaited()
        self.release.assert_not_awaited()
        self.refund.assert_not_awaited()
        self.ops.assert_called_once()

    def test_stale_status_changes_nothing(self):
        self._apply(payment("SUCCEEDED", "SUCCESS"), applied=False)
        self.settle.assert_not_awaited()
        self.user_notify.assert_not_called()

    def test_unknown_payment_is_ignored(self):
        self.assertIsNone(self._apply(payment("SUCCEEDED", "SUCCESS"), row=None, applied=False))


if __name__ == "__main__":
    unittest.main()
