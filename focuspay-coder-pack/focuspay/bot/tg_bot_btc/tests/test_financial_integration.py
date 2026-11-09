"""Интеграционные тесты финансовых инвариантов (mock БД, без live PostgreSQL)."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.financial_guards import buy_pay_allowed_status, is_admin_group_chat
from services import config_rates
from services.user_cashback_commission import accrue_user_cashback
from services.user_referral_commission import accrue_user_referral_commission
from services.user_cashback_db import hold_cashback_for_order


class AdminPayRulesTests(unittest.TestCase):
    def test_buy_pay_only_from_completed(self):
        self.assertTrue(buy_pay_allowed_status("COMPLETED"))
        for status in ("CREATED", "PENDING", "AWAITING_CHECK", "PAID", "CANCELED"):
            self.assertFalse(buy_pay_allowed_status(status))

    def test_admin_group_chat_required(self):
        with patch.object(config_rates, "TELEGRAM_REPORTS_GROUP_ID", -100):
            self.assertTrue(is_admin_group_chat(-100))
            self.assertFalse(is_admin_group_chat(-200))
            self.assertFalse(is_admin_group_chat(None))

        with patch.object(config_rates, "TELEGRAM_REPORTS_GROUP_ID", 0):
            self.assertFalse(is_admin_group_chat(0))


class DoublePaidAccrualTests(unittest.IsolatedAsyncioTestCase):
    async def test_cashback_accrual_skips_duplicate(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {
            "order_id": "O1",
            "user_id": 1,
            "status": "PAID",
            "direction": "buy",
            "crypto": "usdt",
            "fiat_amount": 10000,
            "crypto_amount": 100,
            "rate": 100,
            "cashback_applied_rub": 0,
            "card_fee_pct": 0.12,
        }
        conn.fetchval.return_value = 1

        result = await accrue_user_cashback("O1", conn=conn)
        self.assertFalse(result)
        conn.execute.assert_not_called()

    async def test_referral_accrual_skips_duplicate(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            {
                "order_id": "O1",
                "user_id": 2,
                "status": "PAID",
                "direction": "buy",
                "crypto": "usdt",
                "fiat_amount": 10000,
                "crypto_amount": 100,
                "rate": 100,
                "cashback_applied_rub": 0,
                "card_fee_pct": 0.12,
            },
        ]
        conn.fetchval.return_value = 1

        result = await accrue_user_referral_commission("O1", conn=conn)
        self.assertFalse(result)
        conn.execute.assert_not_called()


class CashbackHoldConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_hold_sees_reduced_balance(self):
        ledger_sum = 1000.0

        async def fetchval(query, *args):
            nonlocal ledger_sum
            q = " ".join(query.split())
            if "partner_ledger" in q or "partner_withdrawals" in q:
                return 0.0
            if "SUM(amount_rub)" in query:
                return ledger_sum
            return None

        conn = AsyncMock()
        conn.fetchval.side_effect = fetchval
        conn.fetchrow = AsyncMock(return_value=None)

        async def execute(query, user_id, amount, order_id, note):
            nonlocal ledger_sum
            if "hold" in query and amount < 0:
                ledger_sum += amount

        conn.execute.side_effect = execute

        first = await hold_cashback_for_order(conn, 42, "order-a", 800)
        second = await hold_cashback_for_order(conn, 42, "order-b", 800)

        self.assertAlmostEqual(first, 800)
        self.assertAlmostEqual(second, 200)

    async def test_duplicate_hold_returns_zero(self):
        # Повторный hold по той же заявке ничего не резервирует (идемпотентность).
        async def fetchval(query, *args):
            q = " ".join(query.split())
            # Признак "резерв уже есть" для этой заявки.
            if "UNION ALL" in q and "order_id = $1" in q:
                return 1
            if "partner_ledger" in q or "partner_withdrawals" in q:
                return 0.0
            if "SUM(amount_rub)" in query:
                return 1000.0
            return None

        conn = AsyncMock()
        conn.fetchval.side_effect = fetchval
        conn.fetchrow = AsyncMock(return_value=None)
        conn.execute = AsyncMock()

        held = await hold_cashback_for_order(conn, 42, "dup-order", 500)
        self.assertEqual(held, 0.0)
        conn.execute.assert_not_called()


class WithdrawalOverdrawTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_withdrawal_rejects_over_available(self):
        from services.user_referral_withdraw import create_withdrawal

        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = None
        mock_conn.fetchrow.return_value = None

        class _Tx:
            async def __aenter__(self):
                return mock_conn

            async def __aexit__(self, *args):
                return False

        mock_conn.transaction = MagicMock(return_value=_Tx())

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("services.user_referral_withdraw.get_pool", return_value=mock_pool):
            with patch(
                "services.user_referral_withdraw._available_balance_locked",
                new=AsyncMock(return_value=100.0),
            ):
                with self.assertRaises(ValueError) as ctx:
                    await create_withdrawal(
                        referrer_user_id=1,
                        amount_rub=25000,
                        method="card",
                        requisites="4111111111111111",
                    )
                self.assertIn("Недостаточно средств", str(ctx.exception))


class ConfigValidationTests(unittest.TestCase):
    def test_validate_bot_config_ok_when_configured(self):
        with patch.object(config_rates, "TELEGRAM_ADMIN_IDS", [123]):
            with patch("services.config_rates._env") as mock_env:
                mock_env.side_effect = lambda key, default="": {
                    "TELEGRAM_BOT_TOKEN": "tok",
                    "DATABASE_DSN": "postgresql://u:p@localhost/db",
                    "CALLBACK_SECRET": "secret",
                }.get(key, default)
                config_rates.validate_bot_config()

    def test_validate_bot_config_exits_when_missing(self):
        with patch.object(config_rates, "TELEGRAM_ADMIN_IDS", []):
            with patch("services.config_rates._env", return_value=""):
                with patch("sys.exit") as mock_exit:
                    config_rates.validate_bot_config()
                    mock_exit.assert_called_once_with(1)


class PartnerAuthQueryTests(unittest.TestCase):
    def test_partner_lookup_sql_requires_telegram_user_id(self):
        import inspect
        from services import partner_db

        source = inspect.getsource(partner_db.get_partner_by_telegram)
        self.assertIn("pa.telegram_user_id = $1", source)
        self.assertNotIn("LOWER(pa.username)", source)


class PayinModeSecurityTests(unittest.TestCase):
    def test_blocks_forged_operator_mode(self):
        from services.payin_resolver import resolve_payin_mode

        plan = {
            "mode": "single",
            "parts": [5000],
            "pay_now": 5000,
            "remainder_rub": 0,
            "has_bill": True,
        }
        with self.assertRaises(ValueError):
            resolve_payin_mode(plan, "operator")

    def test_allows_operator_when_no_bill(self):
        from services.payin_resolver import allowed_payin_modes, resolve_payin_mode

        plan = {
            "mode": "operator",
            "parts": [],
            "pay_now": 8000,
            "remainder_rub": 0,
            "has_bill": False,
        }
        self.assertIn("operator", allowed_payin_modes(plan))
        self.assertEqual(resolve_payin_mode(plan, "operator"), "operator")


class OrderTransitionTests(unittest.TestCase):
    def test_blocks_expired_to_completed(self):
        from services.order_transitions import allowed_status_transition

        self.assertFalse(allowed_status_transition("EXPIRED", "COMPLETED"))

    def test_allows_completed_to_paid(self):
        from services.order_transitions import allowed_status_transition

        self.assertTrue(allowed_status_transition("COMPLETED", "PAID"))

    def test_sell_created_to_paid_only_for_sell(self):
        from services.order_transitions import allowed_status_transition

        self.assertTrue(
            allowed_status_transition("CREATED", "PAID", direction="sell")
        )
        self.assertFalse(
            allowed_status_transition("CREATED", "PAID", direction="buy")
        )

    def test_blocks_created_to_completed(self):
        from services.order_transitions import allowed_status_transition

        self.assertFalse(
            allowed_status_transition("CREATED", "COMPLETED", direction="buy")
        )

    def test_sell_pay_requires_pending(self):
        from services.order_transitions import sell_pay_allowed_status

        self.assertFalse(sell_pay_allowed_status("CREATED"))
        self.assertTrue(sell_pay_allowed_status("PENDING"))

    def test_sell_pending_to_paid(self):
        from services.order_transitions import allowed_status_transition

        self.assertTrue(
            allowed_status_transition("PENDING", "PAID", direction="sell")
        )
        self.assertFalse(
            allowed_status_transition("PENDING", "PAID", direction="buy")
        )
        self.assertTrue(
            allowed_status_transition("AWAITING_CHECK", "PAID", direction="sell")
        )


class ReceiptValidationTests(unittest.TestCase):
    def test_pdf_magic(self):
        from pathlib import Path
        from services.receipt_validation import is_valid_pdf_file, is_valid_video_file
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(b"%PDF-1.4 fake")
            path = Path(fh.name)
        try:
            self.assertTrue(is_valid_pdf_file(path))
            self.assertFalse(is_valid_video_file(path))
        finally:
            path.unlink(missing_ok=True)


class CallbackSignatureTests(unittest.TestCase):
    def test_32_char_signatures_verify(self):
        with patch.object(config_rates, "CALLBACK_SECRET", "test-secret"):
            order_id = "ORD-1"
            from services.callback_signatures import (
                sign_order,
                verify_order_signature,
            )

            self.assertTrue(verify_order_signature(order_id, sign_order(order_id)))
            self.assertEqual(len(sign_order(order_id)), 32)

    def test_legacy_16_char_signatures_rejected(self):
        import hashlib
        import hmac

        with patch.object(config_rates, "CALLBACK_SECRET", "test-secret"):
            order_id = "ORD-1"
            legacy = hmac.new(
                b"test-secret", order_id.encode(), hashlib.sha256
            ).hexdigest()[:16]
            from services.callback_signatures import verify_order_signature

            self.assertFalse(verify_order_signature(order_id, legacy))


if __name__ == "__main__":
    unittest.main()
