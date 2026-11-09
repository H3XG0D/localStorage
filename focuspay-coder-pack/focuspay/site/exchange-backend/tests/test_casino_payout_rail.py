"""Fiat casino deposits must leave via card before crypto withdraw unlocks."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import unittest

import casino_payout_rail as rail


NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


class RailConn:
    def __init__(self):
        self.credits: list[dict] = []
        self.withdrawals: list[dict] = []

    def add_credit(self, *, telegram_id, amount, rail_kind, credited_at=None):
        self.credits.append({
            "telegram_id": telegram_id,
            "amount_rub": Decimal(str(amount)),
            "rail": rail_kind,
            "credited_at": credited_at or NOW,
        })

    def add_withdraw(self, *, user_id, amount, method="card", status="paid", created_at=None):
        self.withdrawals.append({
            "referrer_user_id": user_id,
            "amount_rub": Decimal(str(amount)),
            "method": method,
            "status": status,
            "created_at": created_at or (NOW + timedelta(hours=1)),
        })

    async def fetchrow(self, query, *args):
        if "FROM casino_deposit_credits" in query:
            uid = args[0]
            fiat = [row for row in self.credits if row["telegram_id"] == uid and row["rail"] == "fiat"]
            if not fiat:
                return {"fiat_in": Decimal("0"), "first_at": None}
            total = sum((row["amount_rub"] for row in fiat), Decimal("0"))
            return {"fiat_in": total, "first_at": min(row["credited_at"] for row in fiat)}
        raise AssertionError(f"Unexpected fetchrow: {query}")

    async def fetchval(self, query, *args):
        if "FROM user_referral_withdrawals" in query:
            uid, first_at = args
            total = Decimal("0")
            for row in self.withdrawals:
                if row["referrer_user_id"] != uid:
                    continue
                if row["method"] != "card" or row["status"] not in ("pending", "paid"):
                    continue
                if row["created_at"] < first_at:
                    continue
                total += row["amount_rub"]
            return total
        raise AssertionError(f"Unexpected fetchval: {query}")


class PayoutRailPureTests(unittest.TestCase):
    def test_sub_token_maps_to_rail(self):
        self.assertEqual(rail.rail_from_sub_token("SBPRUB"), "fiat")
        self.assertEqual(rail.rail_from_sub_token("cardrub"), "fiat")
        self.assertEqual(rail.rail_from_sub_token("USDT"), "crypto")
        self.assertEqual(rail.rail_from_sub_token(None), "crypto")
        self.assertEqual(rail.rail_from_sub_token(""), "crypto")

    def test_remaining_never_negative(self):
        self.assertEqual(rail.remaining_from_totals(Decimal("1000"), Decimal("1500")), Decimal("0.00"))

    def test_crypto_allowed_epsilon(self):
        self.assertTrue(rail.crypto_allowed_for_remaining(Decimal("0.01")))
        self.assertFalse(rail.crypto_allowed_for_remaining(Decimal("0.02")))

    def test_blocked_message_uses_remaining(self):
        self.assertEqual(
            rail.crypto_withdraw_blocked_message(Decimal("1000")),
            "Сначала выведите 1,000.00 ₽ на карту",
        )


class PayoutRailProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_credits_allows_crypto(self):
        progress = await rail.payout_rail_progress(RailConn(), 42)
        self.assertEqual(progress["remaining_rub"], Decimal("0.00"))
        self.assertTrue(progress["crypto_allowed"])

    async def test_fiat_deposit_blocks_crypto_until_card_out(self):
        conn = RailConn()
        conn.add_credit(telegram_id=7, amount="1000", rail_kind="fiat")
        progress = await rail.payout_rail_progress(conn, 7)
        self.assertEqual(progress["fiat_deposited_rub"], Decimal("1000.00"))
        self.assertEqual(progress["remaining_rub"], Decimal("1000.00"))
        self.assertFalse(progress["crypto_allowed"])

        conn.add_withdraw(user_id=7, amount="1000", status="paid")
        progress = await rail.payout_rail_progress(conn, 7)
        self.assertEqual(progress["remaining_rub"], Decimal("0.00"))
        self.assertTrue(progress["crypto_allowed"])

    async def test_pending_card_counts_as_out(self):
        conn = RailConn()
        conn.add_credit(telegram_id=7, amount="1000", rail_kind="fiat")
        conn.add_withdraw(user_id=7, amount="1000", status="pending")
        progress = await rail.payout_rail_progress(conn, 7)
        self.assertEqual(progress["remaining_rub"], Decimal("0.00"))
        self.assertTrue(progress["crypto_allowed"])

    async def test_rejected_card_does_not_count(self):
        conn = RailConn()
        conn.add_credit(telegram_id=7, amount="1000", rail_kind="fiat")
        conn.add_withdraw(user_id=7, amount="1000", status="rejected")
        progress = await rail.payout_rail_progress(conn, 7)
        self.assertEqual(progress["remaining_rub"], Decimal("1000.00"))
        self.assertFalse(progress["crypto_allowed"])

    async def test_legacy_and_crypto_rails_create_no_debt(self):
        conn = RailConn()
        conn.add_credit(telegram_id=7, amount="5000", rail_kind="legacy")
        conn.add_credit(telegram_id=7, amount="500", rail_kind="crypto")
        progress = await rail.payout_rail_progress(conn, 7)
        self.assertTrue(progress["crypto_allowed"])
        self.assertEqual(progress["fiat_deposited_rub"], Decimal("0.00"))

    async def test_mixed_fiat_and_crypto_requires_fiat_card_out(self):
        conn = RailConn()
        conn.add_credit(telegram_id=7, amount="1000", rail_kind="fiat")
        conn.add_credit(telegram_id=7, amount="500", rail_kind="crypto")
        progress = await rail.payout_rail_progress(conn, 7)
        self.assertEqual(progress["remaining_rub"], Decimal("1000.00"))
        self.assertFalse(progress["crypto_allowed"])

    async def test_second_fiat_after_unlock_closes_crypto_again(self):
        conn = RailConn()
        conn.add_credit(telegram_id=7, amount="1000", rail_kind="fiat", credited_at=NOW)
        conn.add_withdraw(user_id=7, amount="1000", created_at=NOW + timedelta(hours=1))
        progress = await rail.payout_rail_progress(conn, 7)
        self.assertTrue(progress["crypto_allowed"])
        conn.add_credit(telegram_id=7, amount="500", rail_kind="fiat", credited_at=NOW + timedelta(days=1))
        progress = await rail.payout_rail_progress(conn, 7)
        self.assertEqual(progress["remaining_rub"], Decimal("500.00"))
        self.assertFalse(progress["crypto_allowed"])

    async def test_card_withdraw_before_first_fiat_does_not_count(self):
        conn = RailConn()
        conn.add_withdraw(user_id=7, amount="1000", created_at=NOW - timedelta(days=2))
        conn.add_credit(telegram_id=7, amount="1000", rail_kind="fiat", credited_at=NOW)
        progress = await rail.payout_rail_progress(conn, 7)
        self.assertEqual(progress["remaining_rub"], Decimal("1000.00"))
        self.assertFalse(progress["crypto_allowed"])

    async def test_assert_crypto_raises_with_remaining(self):
        conn = RailConn()
        conn.add_credit(telegram_id=7, amount="250", rail_kind="fiat")
        with self.assertRaises(ValueError) as raised:
            await rail.assert_crypto_withdraw_allowed(conn, 7)
        self.assertIn("250.00", str(raised.exception))
        self.assertIn("карту", str(raised.exception))

    def test_serialize_strings_and_numbers(self):
        progress = {
            "fiat_deposited_rub": Decimal("1000.00"),
            "card_withdrawn_rub": Decimal("250.50"),
            "remaining_rub": Decimal("749.50"),
            "crypto_allowed": False,
        }
        self.assertEqual(rail.serialize_payout_rail(progress)["remaining_rub"], "749.50")
        self.assertEqual(rail.serialize_payout_rail_numbers(progress)["remaining_rub"], 749.5)


class CreateWithdrawalRailTests(unittest.IsolatedAsyncioTestCase):
    async def test_crypto_rejected_when_rail_blocks(self):
        try:
            from user_referral_withdraw import create_withdrawal
        except ModuleNotFoundError:
            self.skipTest("asyncpg is not installed")

        with (
            patch(
                "user_referral_withdraw.resolve_usdt_rub",
                new=AsyncMock(return_value=90.0),
            ),
            patch(
                "user_referral_withdraw.min_crypto_amount_rub",
                new=AsyncMock(return_value=10.0),
            ),
            patch(
                "casino_payout_rail.assert_crypto_withdraw_allowed",
                new=AsyncMock(side_effect=ValueError("Сначала выведите 1,000.00 ₽ на карту")),
            ),
            patch("user_referral_withdraw.get_pool") as get_pool,
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
                    requisites="bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
                    crypto="btc",
                )
            self.assertIn("Сначала выведите", str(raised.exception))
            self.assertFalse(
                any(
                    "INSERT INTO user_referral_withdrawals" in call.args[0]
                    for call in conn.fetchrow.await_args_list
                )
            )
