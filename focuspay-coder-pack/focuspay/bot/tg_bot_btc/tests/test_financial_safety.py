"""Регрессионные тесты финансовой безопасности (без БД где возможно)."""
import hmac
import time
import unittest
from unittest.mock import patch

from services import config_rates
from services.service_profit import order_service_profit
from services.webhook_security import (
    WEBHOOK_COMPLETABLE_STATUSES,
    amount_matches_order,
    order_ready_for_merchant_complete,
    resolve_client_ip,
    sign_webhook_body,
    verify_incoming_webhook,
    verify_payfast_callback,
    verify_webhook_signature,
)
from services.callback_signatures import (
    sign_order,
    sign_withdrawal,
    verify_order_signature,
    verify_withdrawal_signature,
)


class WebhookAuthTests(unittest.TestCase):
    def test_hmac_body_signature(self):
        body = b'{"status":"ACCEPTED"}'
        ts = str(int(time.time()))
        with patch.object(config_rates, "WEBHOOK_SECRET", "secret"), patch.object(
            config_rates, "MERCHANT", {"secret_key": ""}
        ):
            sig, _ = sign_webhook_body(body, ts)
            self.assertTrue(verify_webhook_signature(body, sig, ts))
            self.assertFalse(verify_webhook_signature(body, "bad", ts))

    def test_rejects_expired_timestamp(self):
        body = b'{"status":"ACCEPTED"}'
        with patch.object(config_rates, "WEBHOOK_SECRET", "secret"), patch.object(
            config_rates, "MERCHANT", {"secret_key": ""}
        ):
            sig, ts = sign_webhook_body(body, "1")
            self.assertFalse(verify_webhook_signature(body, sig, ts))

    def test_payfast_callback_api_key(self):
        body = {
            "api_key": "key123",
            "id_merchant": 212,
            "client_transaction_id": "ord-1",
            "data_order": {"status": "PAID"},
        }
        with patch.object(
            config_rates,
            "MERCHANT",
            {"api_key": "key123", "merchant_id": "212"},
        ):
            self.assertTrue(verify_payfast_callback(body))
            self.assertFalse(verify_payfast_callback({**body, "api_key": "wrong"}))
            self.assertFalse(verify_payfast_callback({**body, "id_merchant": 999}))

    def test_payfast_callback_without_merchant_id(self):
        body = {"api_key": "key123", "id_merchant": 212, "data_order": {}}
        with patch.object(config_rates, "MERCHANT", {"api_key": "key123", "merchant_id": ""}):
            self.assertTrue(verify_payfast_callback(body))

    def test_verify_incoming_prefers_payfast_body(self):
        body_dict = {
            "api_key": "k",
            "id_merchant": 1,
            "data_order": {"client_transaction_id": "x", "status": "PAID"},
        }
        raw = b'{"api_key":"k"}'
        with patch.object(config_rates, "MERCHANT", {"api_key": "k", "merchant_id": "1"}):
            self.assertTrue(verify_incoming_webhook(raw, body_dict, None, None))


class WebhookAmountTests(unittest.TestCase):
    def test_amount_within_tolerance(self):
        ok, reason = amount_matches_order({"amount": 5001}, {"fiat_amount": 5000})
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_amount_mismatch(self):
        ok, reason = amount_matches_order({"amount": 5100}, {"fiat_amount": 5000})
        self.assertFalse(ok)
        self.assertIn("amount_mismatch", reason or "")

    def test_missing_amount_rejected(self):
        ok, reason = amount_matches_order({}, {"fiat_amount": 5000})
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_amount")

    def test_amount_rejects_non_finite_or_invalid_values(self):
        for amount in ("not-a-number", "NaN", "Infinity"):
            with self.subTest(amount=amount):
                ok, reason = amount_matches_order({"amount": amount}, {"fiat_amount": 5000})
                self.assertFalse(ok)
                self.assertEqual(reason, "invalid_amount")

    def test_decimal_amount_tolerance_boundary(self):
        ok, reason = amount_matches_order(
            {"amount": "5001.00"}, {"fiat_amount": "5000.00"}
        )
        self.assertTrue(ok)
        self.assertIsNone(reason)


class AdminSignatureTests(unittest.TestCase):
    def test_order_callback_hmac(self):
        with patch.object(config_rates, "CALLBACK_SECRET", "test-secret"):
            order_id = "ORD123"
            sig = sign_order(order_id)
            self.assertTrue(verify_order_signature(order_id, sig))
            self.assertFalse(verify_order_signature(order_id, "bad"))

    def test_rejects_legacy_16_char_signature(self):
        import hashlib

        with patch.object(config_rates, "CALLBACK_SECRET", "test-secret"):
            order_id = "ORD123"
            legacy = hmac.new(
                b"test-secret", order_id.encode(), hashlib.sha256
            ).hexdigest()[:16]
            self.assertFalse(verify_order_signature(order_id, legacy))


class BuyPayoutValidateTests(unittest.TestCase):
    def test_clamp_reduces_overpayment(self):
        from services.buy_payout_validate import clamp_buy_crypto_amount

        out = clamp_buy_crypto_amount(
            98.85,
            fiat_amount=6000,
            rate=91.044,
            crypto="USDT_TRC20",
        )
        self.assertAlmostEqual(out, 6000 / 91.044, places=2)
        self.assertLess(out, 98.85)

    def test_lock_crypto_keeps_entered_btc(self):
        from services.buy_payout_validate import clamp_buy_crypto_amount

        out = clamp_buy_crypto_amount(
            0.00092555,
            fiat_amount=7212,
            rate=7793098.17,
            crypto="btc",
            lock_crypto=True,
        )
        self.assertEqual(out, 0.00092555)

    def test_blocks_overpayment(self):
        from services.buy_payout_validate import validate_buy_payout_crypto

        order = {
            "crypto": "USDT_TRC20",
            "fiat_amount": 6000,
            "crypto_amount": 98.85,
            "rate": 91.044,
            "cashback_applied_rub": 0,
        }
        ok, reason = validate_buy_payout_crypto(order)
        self.assertFalse(ok)
        self.assertEqual(reason, "crypto_exceeds_paid")

    def test_allows_proportional_crypto(self):
        from services.buy_payout_validate import validate_buy_payout_crypto

        order = {
            "crypto": "USDT_TRC20",
            "fiat_amount": 6000,
            "crypto_amount": 54.95,
            "rate": 91.044,
            "cashback_applied_rub": 0,
        }
        ok, _ = validate_buy_payout_crypto(order)
        self.assertTrue(ok)

    def test_payout_tolerance_zero_blocks_small_overpay(self):
        # На этапе выплаты толеранс 0: даже +1% сверх ожидаемого блокируется.
        from services.buy_payout_validate import (
            expected_crypto_for_paid_rub,
            validate_buy_payout_crypto,
        )

        exp = expected_crypto_for_paid_rub(
            fiat_amount=6000, rate=91.044, crypto="USDT_TRC20"
        )
        order = {
            "crypto": "USDT_TRC20",
            "fiat_amount": 6000,
            "crypto_amount": exp * 1.01,  # +1% — раньше прошло бы (допуск 2%)
            "rate": 91.044,
            "cashback_applied_rub": 0,
        }
        ok, reason = validate_buy_payout_crypto(order)
        self.assertFalse(ok)
        self.assertEqual(reason, "crypto_exceeds_paid")

    def test_payout_exact_expected_allowed(self):
        from services.buy_payout_validate import (
            expected_crypto_for_paid_rub,
            validate_buy_payout_crypto,
        )

        exp = expected_crypto_for_paid_rub(
            fiat_amount=6000, rate=91.044, crypto="USDT_TRC20"
        )
        order = {
            "crypto": "USDT_TRC20",
            "fiat_amount": 6000,
            "crypto_amount": exp,
            "rate": 91.044,
            "cashback_applied_rub": 0,
        }
        ok, _ = validate_buy_payout_crypto(order)
        self.assertTrue(ok)


class ProfitModelTests(unittest.TestCase):
    def test_buy_merchant_fee_on_payin_not_base(self):
        # Сделка 12k, крипта на 10k: маржа 2k, мерч 12% от 12k = 1.44k, чистая 560
        full = order_service_profit(
            "buy",
            "usdt",
            12000,
            crypto_amount=10000 / 100,
            rate=100 * 1.2,
        )
        self.assertAlmostEqual(full, 560.0, places=0)

    def test_cashback_reduces_buy_profit(self):
        # payin 11k + кешбэк 1k = сделка 12k; мерч 12% от 11k
        full = order_service_profit("buy", "usdt", 12000)
        with_cb = order_service_profit(
            "buy", "usdt", 11000, cashback_applied_rub=1000
        )
        self.assertLess(with_cb, full)
        # маржа 2k − мерч 12% от payin 11k − списанный кешбэк 1k → не ниже 0
        self.assertAlmostEqual(with_cb, 0.0, places=0)


class PayableStatusTests(unittest.TestCase):
    def test_buy_created_not_webhook_completable(self):
        ok, reason = order_ready_for_merchant_complete(
            {"direction": "buy", "status": "CREATED"}
        )
        self.assertFalse(ok)
        self.assertIn("buy_awaiting_payment_proof", reason or "")

    def test_buy_pending_completable(self):
        ok, _ = order_ready_for_merchant_complete(
            {"direction": "buy", "status": "PENDING"}
        )
        self.assertTrue(ok)
        self.assertIn("PENDING", WEBHOOK_COMPLETABLE_STATUSES)

    def test_buy_awaiting_check_not_completable(self):
        # Инцидент: чек не долетел до мерчанта, заявка ещё AWAITING_CHECK —
        # завершать НЕЛЬЗЯ (строгий режим: COMPLETED только из PENDING).
        ok, reason = order_ready_for_merchant_complete(
            {"direction": "buy", "status": "AWAITING_CHECK"}
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "receipt_not_submitted")
        self.assertNotIn("AWAITING_CHECK", WEBHOOK_COMPLETABLE_STATUSES)

    def test_awaiting_check_to_completed_transition_blocked(self):
        from services.order_transitions import allowed_status_transition

        self.assertFalse(
            allowed_status_transition("AWAITING_CHECK", "COMPLETED", direction="buy")
        )
        self.assertTrue(
            allowed_status_transition("AWAITING_CHECK", "PENDING", direction="buy")
        )
        self.assertTrue(
            allowed_status_transition("PENDING", "COMPLETED", direction="buy")
        )

    def test_payin_rail_allows_awaiting_check_to_completed(self):
        from services.order_transitions import allowed_status_transition

        self.assertTrue(
            allowed_status_transition(
                "AWAITING_CHECK",
                "COMPLETED",
                direction="buy",
                payin_rail=True,
            )
        )
        self.assertFalse(
            allowed_status_transition(
                "AWAITING_CHECK",
                "COMPLETED",
                direction="buy",
                payin_rail=False,
            )
        )

    def test_web_sell_can_leave_operator_pending_on_client_confirm(self):
        from services.order_transitions import allowed_status_transition

        self.assertTrue(
            allowed_status_transition("OPERATOR_PENDING", "PENDING", direction="sell")
        )


class WebhookClientIpTests(unittest.TestCase):
    def setUp(self):
        self.proxy_patch = patch.object(
            config_rates, "WEBHOOK_TRUSTED_PROXIES", "127.0.0.1,::1", create=True
        )
        self.proxy_patch.start()
        self.addCleanup(self.proxy_patch.stop)

    def test_real_ip_priority(self):
        self.assertEqual(
            resolve_client_ip(
                "127.0.0.1",
                cf_connecting_ip="203.0.113.5",
                real_ip="198.51.100.1",
                forwarded_for="203.0.113.1, 127.0.0.1",
            ),
            "203.0.113.5",
        )

    def test_real_ip_fallback(self):
        self.assertEqual(
            resolve_client_ip(
                "127.0.0.1",
                real_ip="198.51.100.1",
                forwarded_for="203.0.113.1",
            ),
            "198.51.100.1",
        )

    def test_forwarded_for(self):
        self.assertEqual(
            resolve_client_ip("127.0.0.1", forwarded_for="203.0.113.1, 127.0.0.1"),
            "203.0.113.1",
        )

    def test_untrusted_peer_cannot_spoof_forwarded_headers(self):
        self.assertEqual(
            resolve_client_ip(
                "198.51.100.25",
                cf_connecting_ip="203.0.113.5",
                real_ip="203.0.113.6",
                forwarded_for="203.0.113.7",
            ),
            "198.51.100.25",
        )

    def test_payment_success_detection(self):
        from services.webhook_security import is_payment_success_payload

        self.assertTrue(is_payment_success_payload("SUCCSES", None, None))
        self.assertTrue(is_payment_success_payload("PAID", None, None, status_file=0))
        # non-buy: legacy — голый PAID без проверки status_file.
        self.assertTrue(is_payment_success_payload("PAID", None, None, status_file=1))
        self.assertFalse(is_payment_success_payload(None, "ok", 1))
        self.assertFalse(is_payment_success_payload("ACCEPTED", "ok", 1))
        self.assertFalse(is_payment_success_payload(None, "ok", None))
        self.assertFalse(is_payment_success_payload("ACCEPTED", "ok", None))
        self.assertFalse(is_payment_success_payload("FAILED", None, None))
        self.assertFalse(is_payment_success_payload("ERROR", "ok", 1))
        # BUY: только SUCCSES трейдера. PAID+status_file=0 — не апрув.
        self.assertFalse(is_payment_success_payload("PAID", None, None, "buy"))
        self.assertTrue(is_payment_success_payload("SUCCSES", None, None, "buy"))
        self.assertFalse(
            is_payment_success_payload("PAID", None, None, "buy", status_file=0)
        )
        self.assertFalse(
            is_payment_success_payload("PAID", None, 1, "buy", status_file=1)
        )
        self.assertFalse(is_payment_success_payload("ACCEPTED", "ok", 1, "buy"))
        self.assertFalse(is_payment_success_payload("CANCELED", None, 1))


class BuyPayoutTests(unittest.TestCase):
    def test_normalize_tx_hash(self):
        from services.buy_payout import normalize_tx_hash, build_explorer_url

        self.assertEqual(
            normalize_tx_hash("a1b2c3d4e5f67890"),
            "a1b2c3d4e5f67890",
        )
        self.assertIsNone(normalize_tx_hash("short"))
        url = build_explorer_url("ltc", "abc12345678901")
        self.assertIn("litecoin", url)
        btc_url = build_explorer_url("btc", "deadbeef12345678")
        self.assertEqual(btc_url, "https://mempool.space/tx/deadbeef12345678")


class WalletValidationTests(unittest.TestCase):
    def test_rejects_short_btc(self):
        from services.wallet_validation import validate_buy_wallet

        with self.assertRaises(ValueError):
            validate_buy_wallet("btc", "mainnet", "bc1short")

    def test_accepts_btc_mainnet(self):
        from services.wallet_validation import validate_buy_wallet

        validate_buy_wallet(
            "btc",
            "mainnet",
            "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
        )


class ExpireGraceConfigTests(unittest.TestCase):
    def test_grace_default_positive(self):
        from services import config_rates

        self.assertGreaterEqual(config_rates.EXPIRE_GRACE_SECONDS, 0)


class WithdrawalSignatureTests(unittest.TestCase):
    def test_refwd_sig(self):
        with patch.object(config_rates, "CALLBACK_SECRET", "s"):
            sig = sign_withdrawal(42)
            self.assertTrue(verify_withdrawal_signature(42, sig))

    def test_extwd_sig(self):
        from services.callback_signatures import (
            sign_external_payout,
            verify_external_payout_signature,
        )

        with patch.object(config_rates, "CALLBACK_SECRET", "s"):
            sig = sign_external_payout(9)
            self.assertTrue(verify_external_payout_signature(9, sig))
            self.assertFalse(verify_external_payout_signature(10, sig))


class TextSanitizeTests(unittest.TestCase):
    def test_review_strips_html(self):
        from services.text_sanitize import sanitize_review_text

        self.assertEqual(
            sanitize_review_text("<b>ok</b><script>x</script>"),
            "okx",
        )

    def test_receipt_sig(self):
        from services.webhook_security import sign_receipt_access, verify_receipt_access

        with patch.object(config_rates, "RECEIPT_SECRET", "rsec"):
            sig = sign_receipt_access("abc.pdf")
            self.assertTrue(verify_receipt_access("abc.pdf", sig))
            self.assertFalse(verify_receipt_access("abc.pdf", "bad"))
            self.assertFalse(verify_receipt_access("abc.pdf", "rsec"))


class CashbackSpendableTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_withdrawal_reduces_spendable(self):
        from unittest.mock import AsyncMock

        from services.user_cashback_db import _cashback_spendable

        conn = AsyncMock()
        with patch(
            "services.user_cashback_db.get_cashback_balance_conn",
            AsyncMock(return_value=10000.0),
        ):
            with patch(
                "services.user_unified_balance.unified_available",
                AsyncMock(return_value=0.0),
            ):
                spendable = await _cashback_spendable(conn, 42)
        self.assertEqual(spendable, 0.0)


if __name__ == "__main__":
    unittest.main()
