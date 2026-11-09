"""Тесты автоподтверждения внештатных сделок после Payfast."""
from decimal import Decimal
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class ExternalDealAutoConfirmTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_auto_credit_disabled(self):
        from external_deal_payin import try_auto_confirm_external_deal_on_payfast

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "status": "pending",
                "receipt_submitted_at": "2026-01-01T00:00:00",
                "required_receipt_type": 2,
                "is_trusted_client": False,
                "auto_credit_on_payfast": True,
                "exchanger_name": "Test",
                "account_username": "ex1",
            }
        )
        result = await try_auto_confirm_external_deal_on_payfast(conn, 1)
        self.assertTrue(result.get("skipped"))
        self.assertEqual(result.get("reason"), "auto_credit_disabled")

    async def test_idempotent_already_confirmed(self):
        from external_deal_payin import try_auto_confirm_external_deal_on_payfast

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 2,
                "status": "confirmed",
                "receipt_submitted_at": "2026-01-01T00:00:00",
                "required_receipt_type": 2,
                "is_trusted_client": True,
                "auto_credit_on_payfast": True,
                "exchanger_name": "Test",
                "account_username": "ex1",
            }
        )
        result = await try_auto_confirm_external_deal_on_payfast(conn, 2)
        self.assertTrue(result.get("skipped"))
        self.assertEqual(result.get("reason"), "already_confirmed")

    @patch("external_exchange_service.confirm_external_deal", new_callable=AsyncMock)
    @patch(
        "payfast_payin_guard.verify_payfast_ready_for_complete",
        new_callable=AsyncMock,
        return_value=(True, None),
    )
    async def test_callback_mismatch_never_confirms(self, _verify, mock_confirm):
        from external_deal_payin import try_auto_confirm_external_deal_on_payfast

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 4, "status": "pending", "receipt_submitted_at": "2026-01-01T00:00:00",
                "required_receipt_type": 2, "is_trusted_client": True,
                "auto_credit_on_payfast": True, "merchant_order_id": "uuid-good",
                "client_transaction_id": "client-good",
                "payment_snapshot": {"merchant_uuid": "uuid-good", "fiat_amount": 1000},
            }
        )
        result = await try_auto_confirm_external_deal_on_payfast(
            conn, 4, webhook_body={"uuid": "uuid-bad", "client_transaction_id": "client-good", "amount": 1000}
        )
        self.assertEqual(result["reason"], "payfast_uuid_mismatch")
        mock_confirm.assert_not_awaited()
        self.assertIn("callback_mismatch", conn.execute.await_args.args)

    async def test_confirmed_provider_failure_records_review_without_changing_status(self):
        from external_deal_payin import try_auto_confirm_external_deal_on_payfast

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={
            "id": 5, "status": "confirmed", "receipt_submitted_at": "x",
            "required_receipt_type": 2, "is_trusted_client": True,
            "auto_credit_on_payfast": True, "merchant_order_id": "uuid-5",
        })
        result = await try_auto_confirm_external_deal_on_payfast(conn, 5, webhook_body={"status": "ERROR"})
        self.assertEqual(result["reason"], "already_confirmed")
        self.assertIn("post_completion_provider_error", conn.execute.await_args.args)

    @patch(
        "payfast_payin_guard.verify_payfast_ready_for_complete",
        new_callable=AsyncMock,
        return_value=(False, "payfast_api_error"),
    )
    async def test_retryable_provider_error_before_confirmation_does_not_create_review(self, _verify):
        from external_deal_payin import try_auto_confirm_external_deal_on_payfast

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={
            "id": 6, "status": "pending", "receipt_submitted_at": "x",
            "required_receipt_type": 2, "is_trusted_client": True,
            "auto_credit_on_payfast": True, "merchant_order_id": "uuid-6",
            "payment_snapshot": {"merchant_uuid": "uuid-6", "fiat_amount": 1000},
        })
        result = await try_auto_confirm_external_deal_on_payfast(conn, 6)
        self.assertEqual(result["reason"], "payfast_api_error")
        conn.execute.assert_not_awaited()

    @patch("external_exchange_service.confirm_external_deal", new_callable=AsyncMock)
    @patch(
        "payfast_payin_guard.verify_payfast_ready_for_complete",
        new_callable=AsyncMock,
        return_value=(True, None),
    )
    async def test_confirms_when_flags_and_payfast_ready(
        self, _verify, mock_confirm
    ):
        from external_deal_payin import try_auto_confirm_external_deal_on_payfast

        mock_confirm.return_value = {
            "id": 3,
            "status": "confirmed",
            "principal_usdt": 10.0,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 3,
                "status": "pending",
                "receipt_submitted_at": "2026-01-01T00:00:00",
                "required_receipt_type": 2,
                "is_trusted_client": True,
                "auto_credit_on_payfast": True,
                "exchanger_name": "Kanglo",
                "account_username": "kanglo",
                "merchant_order_id": "uuid-3",
                "payment_snapshot": {"merchant_uuid": "uuid-3"},
            }
        )
        result = await try_auto_confirm_external_deal_on_payfast(conn, 3)
        self.assertTrue(result.get("confirmed"))
        mock_confirm.assert_awaited_once()
        call = mock_confirm.await_args
        self.assertEqual(call.args[1], 3)
        confirmed_by = call.kwargs.get("confirmed_by")
        if confirmed_by is None and len(call.args) > 2:
            confirmed_by = call.args[2]
        self.assertEqual(confirmed_by, "payfast:webhook")


class PayfastIdentityTests(unittest.TestCase):
    def test_authoritative_amount_mismatch_fails_closed(self):
        from payfast_payin_guard import payfast_identity_mismatch

        reason = payfast_identity_mismatch(
            {"payment_snapshot": {"merchant_uuid": "uuid-1", "fiat_amount": 1000}, "client_transaction_id": "client-1"},
            {"uuid_system": "uuid-1", "client_transaction_id": "client-1", "amount": 1001},
        )
        self.assertEqual(reason, "payfast_amount_mismatch")

    def test_nested_callback_identity_mismatch_fails_closed(self):
        from payfast_payin_guard import payfast_identity_mismatch

        reason = payfast_identity_mismatch(
            {"payment_snapshot": {"merchant_uuid": "uuid-1", "fiat_amount": 1000}, "client_transaction_id": "client-1"},
            {"uuid": "uuid-1", "amount": 1000, "data_order": {"amount": 1001}},
        )
        self.assertEqual(reason, "payfast_amount_mismatch")


    def test_canonical_merchant_client_id_mismatch_fails_closed(self):
        from payfast_payin_guard import payfast_identity_mismatch

        reason = payfast_identity_mismatch(
            {
                "merchant_order_id": "canonical-1",
                "client_transaction_id": "canonical-1",
                "payment_snapshot": {"merchant_uuid": "uuid-1", "fiat_amount": 1000},
            },
            {"uuid_system": "uuid-1", "client_transaction_id": "other-id", "amount": 1000},
        )
        self.assertEqual(reason, "payfast_client_transaction_id_mismatch")

    def test_historical_merchant_order_id_remains_guard_canonical(self):
        from external_deal_payin import deal_merchant_ctx
        from payfast_payin_guard import payfast_identity_mismatch

        ctx = deal_merchant_ctx(
            {
                "id": 1,
                "merchant_order_id": "legacy-probe-id",
                "client_transaction_id": "partner-id",
                "payment_snapshot": {"merchant_uuid": "uuid-1", "fiat_amount": 1000},
            }
        )
        self.assertEqual(ctx["client_transaction_id"], "legacy-probe-id")
        self.assertIsNone(
            payfast_identity_mismatch(
                ctx, {"uuid_system": "uuid-1", "client_transaction_id": "legacy-probe-id", "amount": 1000}
            )
        )


class ConfirmExternalLedgerTests(unittest.IsolatedAsyncioTestCase):
    async def test_principal_credit_ignores_duplicate_delivery(self):
        from external_exchange_service import _credit_ledger

        conn = AsyncMock()

        await _credit_ledger(
            conn,
            exchanger_id=17,
            deal_id=321,
            principal_usdt=Decimal("25.50"),
        )

        query = conn.execute.await_args.args[0]
        self.assertIn("ON CONFLICT (deal_id) WHERE type = 'principal'", query)
        self.assertIn("DO NOTHING", query)
        self.assertEqual(conn.execute.await_args.args[1:], (17, Decimal("25.50"), 321))


class ConfirmExternalDealIdempotentTests(unittest.IsolatedAsyncioTestCase):
    @patch("external_exchange_service._credit_ledger", new_callable=AsyncMock)
    async def test_confirm_idempotent_on_confirmed(self, mock_credit):
        from external_exchange_service import confirm_external_deal

        deal_row = MagicMock()
        deal_row.__getitem__ = lambda self, k: {
            "id": 9,
            "status": "confirmed",
            "exchanger_id": 1,
            "principal_usdt": 25.0,
            "operator_id": None,
            "operator_earnings_rub": 0,
        }[k]
        deal_row.get = lambda k, default=None: {
            "operator_id": None,
            "operator_earnings_rub": 0,
        }.get(k, default)

        ex_row = MagicMock()
        ex_row.__getitem__ = lambda self, k: {"name": "Ex"}[k]

        conn = AsyncMock()
        conn.transaction = MagicMock()
        conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
        conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)
        conn.fetchrow = AsyncMock(side_effect=[deal_row, ex_row])

        result = await confirm_external_deal(conn, 9, confirmed_by="payfast:webhook")
        self.assertTrue(result.get("already_confirmed"))
        mock_credit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
