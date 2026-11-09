"""P0: webhook Payfast ERROR не должен оставлять заявку оплачиваемой.

Инцидент: Payfast прислал status_check=1, мы перевели в COMPLETED и отправили
крипту, затем Payfast прислал ERROR. Деньги потеряны. Эти тесты фиксируют, что
ERROR-вебхук на COMPLETED откатывает заявку в CANCELED и зовёт ops-алерт, а на
PAID — только алерт (крипта уже ушла).
"""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def _client():
    from services.webhook_server import app

    return TestClient(app)


def _patches(order_status: str, update_ok: bool = True):
    """Общие патчи: проходим проверку IP/подписи, подменяем БД и ops-алерты."""
    order = {
        "order_id": "O1",
        "user_id": 555,
        "status": order_status,
        "direction": "buy",
        "crypto": "ltc",
        "fiat_amount": 9000,
        "crypto_amount": 2.25,
    }
    return order, [
        patch("services.webhook_server.verify_webhook_client_ip", return_value=True),
        patch("services.webhook_server.verify_incoming_webhook", return_value=True),
        patch(
            "services.webhook_server.get_order",
            new=AsyncMock(return_value=dict(order)),
        ),
        patch(
            "services.webhook_server.update_order_status",
            new=AsyncMock(return_value=update_ok),
        ),
        patch("services.webhook_server.notify_ops_payfast_reversal", new=MagicMock()),
        patch(
            "services.webhook_server.notify_ops_payfast_error_after_payout",
            new=MagicMock(),
        ),
        patch("services.webhook_server.notify_user", new=MagicMock()),
    ]


class WebhookPayfastErrorTests(unittest.TestCase):
    def test_completed_reverted_to_canceled_on_error(self):
        order, patches = _patches("COMPLETED")
        with patches[0], patches[1], patches[2], patches[3] as upd, patches[
            4
        ] as ops_rev, patches[5], patches[6]:
            r = _client().post(
                "/callback",
                json={"client_transaction_id": "O1", "status": "ERROR"},
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reason"], "completed_reverted_payfast_error")
        upd.assert_awaited_once_with("O1", "CANCELED")
        ops_rev.assert_called_once()

    def test_paid_only_alerts_no_status_change(self):
        order, patches = _patches("PAID")
        with patches[0], patches[1], patches[2], patches[3] as upd, patches[
            4
        ], patches[5] as ops_after, patches[6]:
            r = _client().post(
                "/callback",
                json={"client_transaction_id": "O1", "status": "ERROR"},
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reason"], "paid_payfast_error_logged")
        upd.assert_not_awaited()
        ops_after.assert_called_once()

    def test_pending_canceled_on_error(self):
        order, patches = _patches("PENDING")
        with patches[0], patches[1], patches[2], patches[3] as upd, patches[
            4
        ], patches[5], patches[6]:
            r = _client().post(
                "/callback",
                json={"client_transaction_id": "O1", "status": "FAILED"},
            )
        self.assertEqual(r.status_code, 200)
        upd.assert_awaited_once_with("O1", "CANCELED")

    def test_error_in_data_order_nested(self):
        order, patches = _patches("COMPLETED")
        with patches[0], patches[1], patches[2], patches[3] as upd, patches[
            4
        ] as ops_rev, patches[5], patches[6]:
            r = _client().post(
                "/callback",
                json={
                    "data_order": {"client_transaction_id": "O1", "status": "CANCELED"},
                },
            )
        self.assertEqual(r.status_code, 200)
        upd.assert_awaited_once_with("O1", "CANCELED")
        ops_rev.assert_called_once()


class WebhookAwaitingCheckTests(unittest.TestCase):
    """Инцидент: чек не долетел (AWAITING_CHECK), а Payfast прислал успех."""

    def _awaiting_order(self):
        return {
            "order_id": "O2",
            "user_id": 777,
            "status": "AWAITING_CHECK",
            "direction": "buy",
            "crypto": "ltc",
            "fiat_amount": 9000,
            "crypto_amount": 2.25,
        }

    def test_success_on_awaiting_check_auto_completed(self):
        order = self._awaiting_order()
        with patch(
            "services.webhook_server.verify_webhook_client_ip", return_value=True
        ), patch(
            "services.webhook_server.verify_incoming_webhook", return_value=True
        ), patch(
            "services.webhook_server.get_order", new=AsyncMock(return_value=dict(order))
        ), patch(
            "services.webhook_server.verify_payfast_ready_for_complete",
            new=AsyncMock(return_value=(True, None, {"amount": 9000})),
        ), patch(
            "services.payfast_buy_complete.complete_buy_from_payfast_settled",
            new=AsyncMock(return_value=(True, None)),
        ) as complete_mock, patch(
            "services.db.mark_ops_alert_once", new=AsyncMock(return_value=True)
        ), patch(
            "services.webhook_server.notify_ops_receipt_missing_on_success",
            new=MagicMock(),
        ) as ops_alert, patch(
            "services.webhook_server.notify_user", new=MagicMock()
        ):
            r = _client().post(
                "/callback",
                json={
                    "client_transaction_id": "O2",
                    "status": "SUCCSES",
                },
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reason"], "receipt_not_submitted_alerted")
        ops_alert.assert_called_once()
        complete_mock.assert_not_awaited()

    def test_success_on_awaiting_check_with_receipt_settles(self):
        order = self._awaiting_order()
        order["receipt_file"] = "r.pdf"
        order["required_receipt_type"] = 2
        with patch(
            "services.webhook_server.verify_webhook_client_ip", return_value=True
        ), patch(
            "services.webhook_server.verify_incoming_webhook", return_value=True
        ), patch(
            "services.webhook_server.get_order", new=AsyncMock(return_value=dict(order))
        ), patch(
            "services.webhook_server.verify_payfast_ready_for_complete",
            new=AsyncMock(return_value=(True, None, {"amount": 9000})),
        ), patch(
            "services.payfast_buy_complete.complete_buy_from_payfast_settled",
            new=AsyncMock(return_value=(True, None)),
        ) as complete_mock, patch(
            "services.webhook_server.notify_ops_receipt_missing_on_success",
            new=MagicMock(),
        ) as ops_alert, patch(
            "services.webhook_server.notify_user", new=MagicMock()
        ):
            r = _client().post(
                "/callback",
                json={
                    "client_transaction_id": "O2",
                    "status": "SUCCSES",
                },
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reason"], "awaiting_check_receipt_settled")
        complete_mock.assert_awaited_once()
        ops_alert.assert_not_called()

    def test_success_on_awaiting_check_with_video_settles(self):
        order = self._awaiting_order()
        order["receipt_file"] = "clip.mp4"
        order["required_receipt_type"] = 3
        with patch(
            "services.webhook_server.verify_webhook_client_ip", return_value=True
        ), patch(
            "services.webhook_server.verify_incoming_webhook", return_value=True
        ), patch(
            "services.webhook_server.get_order", new=AsyncMock(return_value=dict(order))
        ), patch(
            "services.webhook_server.verify_payfast_ready_for_complete",
            new=AsyncMock(return_value=(True, None, {"amount": 9000})),
        ), patch(
            "services.payfast_buy_complete.complete_buy_from_payfast_settled",
            new=AsyncMock(return_value=(True, None)),
        ) as complete_mock, patch(
            "services.webhook_server.notify_ops_receipt_missing_on_success",
            new=MagicMock(),
        ) as ops_alert, patch(
            "services.webhook_server.notify_user", new=MagicMock()
        ):
            r = _client().post(
                "/callback",
                json={
                    "client_transaction_id": "O2",
                    "status": "SUCCSES",
                },
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reason"], "awaiting_check_receipt_settled")
        complete_mock.assert_awaited_once()
        ops_alert.assert_not_called()

    def test_success_on_video_hold_with_old_pdf_does_not_settle(self):
        order = self._awaiting_order()
        order["receipt_file"] = "old.pdf"
        order["required_receipt_type"] = 3
        with patch(
            "services.webhook_server.verify_webhook_client_ip", return_value=True
        ), patch(
            "services.webhook_server.verify_incoming_webhook", return_value=True
        ), patch(
            "services.webhook_server.get_order", new=AsyncMock(return_value=dict(order))
        ), patch(
            "services.webhook_server.verify_payfast_ready_for_complete",
            new=AsyncMock(return_value=(True, None, {"amount": 9000})),
        ), patch(
            "services.payfast_buy_complete.complete_buy_from_payfast_settled",
            new=AsyncMock(return_value=(True, None)),
        ) as complete_mock, patch(
            "services.db.mark_ops_alert_once", new=AsyncMock(return_value=True)
        ), patch(
            "services.webhook_server.notify_ops_receipt_missing_on_success",
            new=MagicMock(),
        ) as ops_alert, patch(
            "services.webhook_server.notify_user", new=MagicMock()
        ):
            r = _client().post(
                "/callback",
                json={
                    "client_transaction_id": "O2",
                    "status": "SUCCSES",
                },
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reason"], "receipt_not_submitted_alerted")
        complete_mock.assert_not_awaited()
        ops_alert.assert_called_once()

    def test_success_on_awaiting_check_verify_fail_still_alerts(self):
        order = self._awaiting_order()
        with patch(
            "services.webhook_server.verify_webhook_client_ip", return_value=True
        ), patch(
            "services.webhook_server.verify_incoming_webhook", return_value=True
        ), patch(
            "services.webhook_server.get_order", new=AsyncMock(return_value=dict(order))
        ), patch(
            "services.webhook_server.update_order_status",
            new=AsyncMock(return_value=True),
        ) as upd, patch(
            "services.webhook_server.verify_payfast_ready_for_complete",
            new=AsyncMock(return_value=(False, "payfast_not_paid", None)),
        ), patch(
            "services.db.mark_ops_alert_once", new=AsyncMock(return_value=True)
        ), patch(
            "services.webhook_server.notify_ops_receipt_missing_on_success",
            new=MagicMock(),
        ) as ops_alert, patch(
            "services.webhook_server.notify_user", new=MagicMock()
        ):
            r = _client().post(
                "/callback",
                json={
                    "client_transaction_id": "O2",
                    "status": "SUCCSES",
                },
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reason"], "receipt_not_submitted_alerted")
        upd.assert_not_awaited()
        ops_alert.assert_called_once()

    def test_accepted_without_status_check_not_completed(self):
        order = self._awaiting_order()
        with patch(
            "services.webhook_server.verify_webhook_client_ip", return_value=True
        ), patch(
            "services.webhook_server.verify_incoming_webhook", return_value=True
        ), patch(
            "services.webhook_server.get_order", new=AsyncMock(return_value=dict(order))
        ), patch(
            "services.webhook_server.update_order_status",
            new=AsyncMock(return_value=True),
        ) as upd, patch(
            "services.webhook_server.notify_ops_receipt_missing_on_success",
            new=MagicMock(),
        ) as ops_alert, patch(
            "services.webhook_server.notify_user", new=MagicMock()
        ):
            r = _client().post(
                "/callback",
                json={
                    "client_transaction_id": "O2",
                    "status": "ACCEPTED",
                    "status_check": 1,
                    "status_pending": "ok",
                },
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["ok"], True)
        upd.assert_not_awaited()
        ops_alert.assert_not_called()


class WebhookDuplicateSuccessTests(unittest.TestCase):
    def test_repeated_success_webhook_sends_one_ops_notification(self):
        order = {
            "order_id": "O3",
            "user_id": 888,
            "status": "PENDING",
            "direction": "buy",
            "crypto": "btc",
            "fiat_amount": 4800,
            "crypto_amount": 0.0007323,
        }
        with patch(
            "services.webhook_server.verify_webhook_client_ip", return_value=True
        ), patch(
            "services.webhook_server.verify_incoming_webhook", return_value=True
        ), patch(
            "services.webhook_server.get_order",
            new=AsyncMock(return_value=dict(order)),
        ), patch(
            "services.webhook_server.verify_payfast_ready_for_complete",
            new=AsyncMock(return_value=(True, None, {"amount": 9000})),
        ), patch(
            "services.webhook_server.update_order_status",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.db.mark_ops_alert_once",
            new=AsyncMock(side_effect=[True, False]),
        ) as mark_alert, patch(
            "services.order_ops_notify.notify_ops_order_sync",
            new=MagicMock(),
        ) as notify_ops, patch(
            "services.webhook_server.notify_user", new=MagicMock()
        ):
            first = _client().post(
                "/callback",
                json={
                    "client_transaction_id": "O3",
                    "status": "SUCCSES",
                    "data_order": {
                        "client_transaction_id": "O3",
                        "status": "SUCCSES",
                        "amount": 4800,
                    },
                },
            )
            second = _client().post(
                "/callback",
                json={
                    "client_transaction_id": "O3",
                    "status": "SUCCSES",
                    "data_order": {
                        "client_transaction_id": "O3",
                        "status": "SUCCSES",
                        "amount": 4800,
                    },
                },
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(mark_alert.await_count, 2)
        notify_ops.assert_called_once()


class OperatorPayrollSignatureTests(unittest.TestCase):
    def test_opay_signature_roundtrip(self):
        from unittest.mock import patch as _p
        from services import config_rates

        with _p.object(config_rates, "CALLBACK_SECRET", "secret-x"):
            from services.callback_signatures import (
                sign_operator_payroll,
                verify_operator_payroll_signature,
            )

            sig = sign_operator_payroll(123)
            self.assertTrue(verify_operator_payroll_signature(123, sig))
            self.assertFalse(verify_operator_payroll_signature(124, sig))
            self.assertFalse(verify_operator_payroll_signature(123, "bad"))
            self.assertFalse(verify_operator_payroll_signature(123, ""))


if __name__ == "__main__":
    unittest.main()
