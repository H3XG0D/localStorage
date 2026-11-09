"""Crypto withdraw is hidden until casino fiat has left via card."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import unittest

from services import casino_payout_rail as rail


class PayoutRailBotPureTests(unittest.TestCase):
    def test_sub_token_and_remaining(self):
        self.assertEqual(rail.rail_from_sub_token("SBPRUB"), "fiat")
        self.assertEqual(rail.rail_from_sub_token("USDT"), "crypto")
        self.assertFalse(rail.crypto_allowed_for_remaining(Decimal("1000")))
        self.assertTrue(rail.crypto_allowed_for_remaining(Decimal("0")))
        self.assertIn("карту", rail.crypto_withdraw_blocked_message(Decimal("1000")))


class WithdrawMethodMarkupTests(unittest.TestCase):
    def test_markup_hides_crypto_when_locked(self):
        try:
            from handlers.user_referral import _payout_rail_from_stats, withdraw_method_markup
        except ModuleNotFoundError:
            self.skipTest("telegram is not installed")
        locked = withdraw_method_markup(False)
        labels = [btn.text for row in locked.inline_keyboard for btn in row]
        self.assertEqual(labels, ["💳 Карта / СБП"])
        open_kb = withdraw_method_markup(True)
        labels = [btn.text for row in open_kb.inline_keyboard for btn in row]
        self.assertIn("🪙 Крипта", labels)
        allowed, remaining = _payout_rail_from_stats(
            {"payout_rail": {"crypto_allowed": False, "remaining_rub": 1000}}
        )
        self.assertFalse(allowed)
        self.assertEqual(remaining, 1000.0)
        allowed, remaining = _payout_rail_from_stats(
            {"payout_rail": {"crypto_allowed": True, "remaining_rub": 1000}}
        )
        self.assertTrue(allowed)


class CreateWithdrawalBotRailTests(unittest.IsolatedAsyncioTestCase):
    async def test_crypto_rejected_when_rail_blocks(self):
        try:
            from services.user_referral_withdraw import create_withdrawal
        except ModuleNotFoundError:
            self.skipTest("asyncpg is not installed")

        with (
            patch(
                "services.user_referral_withdraw.resolve_usdt_rub",
                new=AsyncMock(return_value=90.0),
            ),
            patch(
                "services.user_referral_withdraw.min_crypto_amount_rub",
                new=AsyncMock(return_value=10.0),
            ),
            patch(
                "services.casino_payout_rail.assert_crypto_withdraw_allowed",
                new=AsyncMock(side_effect=ValueError("Сначала выведите 1,000.00 ₽ на карту")),
            ),
            patch("services.user_referral_withdraw.get_pool") as get_pool,
        ):
            conn = AsyncMock()
            conn.fetchval.return_value = None
            conn.fetchrow.return_value = None

            class _Tx:
                async def __aenter__(self):
                    return conn

                async def __aexit__(self, *args):
                    return False

            conn.transaction = MagicMock(return_value=_Tx())
            pool = MagicMock()
            pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
            pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            get_pool.return_value = pool
            with self.assertRaises(ValueError) as raised:
                await create_withdrawal(
                    referrer_user_id=1,
                    amount_rub=1000,
                    method="crypto",
                    requisites="bc1qtestaddress000",
                    crypto="btc",
                )
            self.assertIn("Сначала выведите", str(raised.exception))
            self.assertFalse(
                any(
                    "INSERT INTO user_referral_withdrawals" in call.args[0]
                    for call in conn.fetchrow.await_args_list
                )
            )
