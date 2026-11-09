"""Withdrawal source (balance vs casino) and casino payout queue."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from permissions import PERM_CASINO_PAYOUT, permissions_for_operator_roles, require_permission

ROOT = Path(__file__).resolve().parents[1]


def _withdraw_mod():
    try:
        import user_referral_withdraw as mod
    except ModuleNotFoundError as exc:
        if exc.name == "asyncpg":
            raise unittest.SkipTest("asyncpg is not installed") from exc
        raise
    return mod


class WithdrawalSourceHelpersTests(unittest.TestCase):
    def test_normalize_default_and_casino(self):
        mod = _withdraw_mod()
        self.assertEqual(mod.normalize_withdrawal_source(None), mod.SOURCE_BALANCE)
        self.assertEqual(mod.normalize_withdrawal_source(""), mod.SOURCE_BALANCE)
        self.assertEqual(mod.normalize_withdrawal_source("CASINO"), mod.SOURCE_CASINO)
        with self.assertRaises(ValueError):
            mod.normalize_withdrawal_source("other")

    def test_ops_path_and_flag(self):
        mod = _withdraw_mod()
        self.assertTrue(mod.is_casino_withdrawal({"source": "casino"}))
        self.assertFalse(mod.is_casino_withdrawal({"source": "balance"}))
        self.assertFalse(mod.is_casino_withdrawal(None))
        self.assertEqual(mod.ops_path_for_withdrawal({"source": "casino"}), "/ops/casino-payouts")
        self.assertEqual(mod.ops_path_for_withdrawal({"source": "balance"}), "/ops/orders")

    def test_finance_default_lacks_casino_payout(self):
        self.assertNotIn(PERM_CASINO_PAYOUT, permissions_for_operator_roles(["finance"]))
        with self.assertRaises(HTTPException) as ctx:
            require_permission(
                {"id": 1, "permissions": permissions_for_operator_roles(["finance"])},
                PERM_CASINO_PAYOUT,
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_general_queue_sql_excludes_casino(self):
        src = (ROOT / "routers" / "operator.py").read_text()
        self.assertIn("COALESCE(w.source, 'balance') <> 'casino'", src)
        self.assertIn("is_casino_withdrawal", src)
        self.assertGreaterEqual(src.count("<> 'casino'"), 4)

    def test_casino_router_wired(self):
        main = (ROOT / "main.py").read_text()
        router = (ROOT / "routers" / "operator_casino_payouts.py").read_text()
        self.assertIn("operator_casino_payouts", main)
        self.assertIn("PERM_CASINO_PAYOUT", router)
        self.assertIn("/casino/payouts/{withdrawal_id}/reject", router)
        self.assertIn("process_withdrawal_rejected", router)

    def test_migration_and_user_api(self):
        migration = (ROOT / "migrations" / "add_withdrawal_source.sql").read_text()
        balance = (ROOT / "routers" / "user_balance.py").read_text()
        self.assertIn("source TEXT NOT NULL DEFAULT 'balance'", migration)
        self.assertIn("CHECK (source IN ('balance', 'casino'))", migration)
        self.assertIn("source: str | None = None", balance)
        self.assertIn("source=body.source", balance)
        self.assertIn("/balance/withdrawals", balance)
        self.assertIn("/balance/withdrawals/{withdrawal_id}/cancel", balance)
        self.assertIn("cancel_casino_withdrawal", balance)
        self.assertIn("SOURCE_CASINO", balance)
        self.assertIn("origin != SOURCE_CASINO", balance)
        cap = (ROOT / "migrations" / "add_casino_withdraw_pending_cap.sql").read_text()
        self.assertIn("DROP INDEX IF EXISTS idx_user_referral_wd_one_pending", cap)
        self.assertIn("idx_user_referral_wd_one_pending_balance", cap)
        self.assertIn('Query(None)', balance)


class CreateWithdrawalSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_insert_passes_casino_source(self):
        mod = _withdraw_mod()

        row = {
            "id": 9,
            "referrer_user_id": 1,
            "amount_rub": 5000,
            "method": "card",
            "source": "casino",
            "status": "pending",
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *args):
                return False

        conn.transaction = MagicMock(return_value=_Tx())
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("user_referral_withdraw.get_pool", return_value=pool),
            patch("user_referral_withdraw._lock_and_check_pending", new=AsyncMock()),
            patch("user_referral_withdraw._available_balance_locked", new=AsyncMock(return_value=30000.0)),
            patch("payin_requisite_rail.open_withdrawal_triangle", new=AsyncMock()) as triangle,
        ):
            out = await mod.create_withdrawal(
                referrer_user_id=1,
                amount_rub=20000,
                method="card",
                requisites="2200700123456789",
                source="casino",
            )
        triangle.assert_awaited()
        self.assertEqual(out["source"], "casino")
        sql = conn.fetchrow.await_args.args[0]
        self.assertIn("INSERT INTO user_referral_withdrawals", sql)
        self.assertIn("source", sql)
        self.assertEqual(conn.fetchrow.await_args.args[7], 100.0)
        self.assertEqual(conn.fetchrow.await_args.args[8], 19900.0)
        self.assertEqual(conn.fetchrow.await_args.args[-1], "casino")

    async def test_insert_defaults_to_balance(self):
        mod = _withdraw_mod()

        row = {
            "id": 10,
            "referrer_user_id": 1,
            "amount_rub": 5000,
            "method": "card",
            "source": "balance",
            "status": "pending",
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *args):
                return False

        conn.transaction = MagicMock(return_value=_Tx())
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("user_referral_withdraw.get_pool", return_value=pool),
            patch("user_referral_withdraw._lock_and_check_pending", new=AsyncMock()),
            patch("user_referral_withdraw._available_balance_locked", new=AsyncMock(return_value=30000.0)),
            patch("payin_requisite_rail.open_withdrawal_triangle", new=AsyncMock()),
        ):
            await mod.create_withdrawal(
                referrer_user_id=1,
                amount_rub=20000,
                method="card",
                requisites="2200700123456789",
            )
        self.assertEqual(conn.fetchrow.await_args.args[7], 100.0)
        self.assertEqual(conn.fetchrow.await_args.args[8], 19900.0)
        self.assertEqual(conn.fetchrow.await_args.args[-1], "balance")

    async def test_casino_card_20000_inserts(self):
        mod = _withdraw_mod()

        row = {
            "id": 11,
            "referrer_user_id": 1,
            "amount_rub": 20000,
            "method": "card",
            "source": "casino",
            "status": "pending",
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *args):
                return False

        conn.transaction = MagicMock(return_value=_Tx())
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("user_referral_withdraw.get_pool", return_value=pool),
            patch("user_referral_withdraw._lock_and_check_pending", new=AsyncMock()),
            patch("user_referral_withdraw._available_balance_locked", new=AsyncMock(return_value=30000.0)),
            patch("payin_requisite_rail.open_withdrawal_triangle", new=AsyncMock()),
        ):
            out = await mod.create_withdrawal(
                referrer_user_id=1,
                amount_rub=20000,
                method="card",
                requisites="2200700123456789",
                source="casino",
            )
        self.assertEqual(out["amount_rub"], 20000)
        self.assertEqual(conn.fetchrow.await_args.args[2], 20000)
        self.assertEqual(conn.fetchrow.await_args.args[7], 100.0)
        self.assertEqual(conn.fetchrow.await_args.args[8], 19900.0)

    async def test_casino_card_below_min_rejected(self):
        mod = _withdraw_mod()
        with self.assertRaises(ValueError) as ctx:
            await mod.create_withdrawal(
                referrer_user_id=1,
                amount_rub=19999,
                method="card",
                requisites="2200700123456789",
                source="casino",
            )
        self.assertEqual(str(ctx.exception), "Минимум для карты: 20 000 ₽")

    async def test_balance_card_below_500_rejected(self):
        mod = _withdraw_mod()
        with self.assertRaises(ValueError) as ctx:
            await mod.create_withdrawal(
                referrer_user_id=1,
                amount_rub=19999,
                method="card",
                requisites="2200700123456789",
            )
        self.assertEqual(str(ctx.exception), "Минимум для карты: 20 000 ₽")


class CreateCasinoCryptoFeeTests(unittest.IsolatedAsyncioTestCase):
    async def test_casino_btc_uses_usd_fee(self):
        mod = _withdraw_mod()
        row = {
            "id": 12,
            "referrer_user_id": 1,
            "amount_rub": 1000,
            "method": "crypto",
            "crypto": "btc",
            "source": "casino",
            "status": "pending",
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *args):
                return False

        conn.transaction = MagicMock(return_value=_Tx())
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("user_referral_withdraw.get_pool", return_value=pool),
            patch("user_referral_withdraw._lock_and_check_pending", new=AsyncMock()),
            patch("user_referral_withdraw._available_balance_locked", new=AsyncMock(return_value=10000.0)),
            patch("user_referral_withdraw.resolve_usdt_rub", new=AsyncMock(return_value=80.0)),
            patch("user_referral_withdraw.min_crypto_amount_rub", new=AsyncMock(return_value=10.0)),
            patch("casino_payout_rail.assert_crypto_withdraw_allowed", new=AsyncMock()),
        ):
            await mod.create_withdrawal(
                referrer_user_id=1,
                amount_rub=1000,
                method="crypto",
                requisites="bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
                crypto="btc",
                source="casino",
            )
        insert = next(
            call for call in conn.fetchrow.await_args_list
            if "INSERT INTO user_referral_withdrawals" in call.args[0]
        )
        self.assertEqual(insert.args[7], 200.0)
        self.assertEqual(insert.args[8], 800.0)

    async def test_balance_btc_uses_usd_fee(self):
        mod = _withdraw_mod()
        row = {
            "id": 13,
            "referrer_user_id": 1,
            "amount_rub": 1000,
            "method": "crypto",
            "crypto": "btc",
            "source": "balance",
            "status": "pending",
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *args):
                return False

        conn.transaction = MagicMock(return_value=_Tx())
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("user_referral_withdraw.get_pool", return_value=pool),
            patch("user_referral_withdraw._lock_and_check_pending", new=AsyncMock()),
            patch("user_referral_withdraw._available_balance_locked", new=AsyncMock(return_value=10000.0)),
            patch("user_referral_withdraw.resolve_usdt_rub", new=AsyncMock(return_value=80.0)),
            patch("user_referral_withdraw.min_crypto_amount_rub", new=AsyncMock(return_value=10.0)),
            patch("casino_payout_rail.assert_crypto_withdraw_allowed", new=AsyncMock()),
        ):
            await mod.create_withdrawal(
                referrer_user_id=1,
                amount_rub=1000,
                method="crypto",
                requisites="bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
                crypto="btc",
            )
        insert = next(
            call for call in conn.fetchrow.await_args_list
            if "INSERT INTO user_referral_withdrawals" in call.args[0]
        )
        self.assertEqual(insert.args[7], 200.0)
        self.assertEqual(insert.args[8], 800.0)


class CasinoCardMinConfigTests(unittest.TestCase):
    def test_defaults_split_casino_and_referral(self):
        from config import settings

        self.assertEqual(settings.casino_min_withdraw_card_rub, 20000)
        self.assertEqual(settings.user_referral_min_withdraw_card_rub, 20000)
        self.assertEqual(settings.casino_withdraw_fee_card_rub, 100.0)
        self.assertEqual(settings.casino_withdraw_fee_usd_btc, 2.5)
        self.assertEqual(settings.casino_withdraw_fee_usd_ltc, 2.5)
        self.assertEqual(settings.casino_withdraw_fee_usd_trx, 2.5)

    def test_helper_uses_casino_min(self):
        mod = _withdraw_mod()
        self.assertEqual(mod.min_card_withdraw_rub("casino"), 20000)
        self.assertEqual(mod.min_card_withdraw_rub(None), 20000)
        self.assertEqual(mod.min_card_withdraw_rub("balance"), 20000)


class CasinoWithdrawFeeTests(unittest.TestCase):
    def test_helper_uses_one_table(self):
        from crypto_network_fee import casino_withdraw_fee_rub, payout_from_fee, withdraw_fee_rub

        self.assertEqual(casino_withdraw_fee_rub("card", None, usdt_rub=80), 100.0)
        self.assertEqual(casino_withdraw_fee_rub("crypto", "btc", usdt_rub=80), 200.0)
        self.assertEqual(casino_withdraw_fee_rub("crypto", "ltc", usdt_rub=80), 200.0)
        self.assertEqual(casino_withdraw_fee_rub("crypto", "trx", usdt_rub=80), 200.0)
        self.assertAlmostEqual(casino_withdraw_fee_rub("crypto", "usdt", usdt_rub=80), 320.0)
        self.assertEqual(withdraw_fee_rub("card", None, usdt_rub=80, source="balance"), 100.0)
        self.assertEqual(withdraw_fee_rub("crypto", "btc", usdt_rub=80, source="balance"), 200.0)
        self.assertEqual(withdraw_fee_rub("crypto", "ltc", usdt_rub=80, source="balance"), 200.0)
        self.assertEqual(withdraw_fee_rub("crypto", "trx", usdt_rub=80, source="balance"), 200.0)
        self.assertEqual(payout_from_fee(500, 100), 400.0)

    def test_admin_message_card_shows_net(self):
        mod = _withdraw_mod()
        msg = mod.format_withdrawal_admin_message(
            {
                "id": 3,
                "referrer_user_id": 1,
                "method": "card",
                "amount_rub": 500.0,
                "network_fee_rub": 100.0,
                "payout_amount_rub": 400.0,
                "source": "casino",
                "requisites": "2200700123456789",
            },
            None,
        )
        self.assertIn("400", msg)
        self.assertIn("100", msg)
        self.assertIn("К отправке", msg)
        self.assertIn("с баланса", msg)

    def test_admin_message_balance_card_stays_plain_sum(self):
        mod = _withdraw_mod()
        msg = mod.format_withdrawal_admin_message(
            {
                "id": 4,
                "referrer_user_id": 1,
                "method": "card",
                "amount_rub": 5000.0,
                "network_fee_rub": 0,
                "payout_amount_rub": None,
                "source": "balance",
                "requisites": "2200700123456789",
            },
            None,
        )
        self.assertIn("5,000", msg)
        self.assertNotIn("К отправке", msg)


class RejectPendingTests(unittest.IsolatedAsyncioTestCase):
    async def test_reject_updates_pending_only(self):
        mod = _withdraw_mod()

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        conn.fetchrow = AsyncMock(
            return_value={"id": 3, "status": "rejected", "referrer_user_id": 1, "amount_rub": 250}
        )

        with patch("user_referral_withdraw.get_pool", return_value=_tx_pool(conn)):
            out = await mod.process_withdrawal_rejected(3)
        self.assertEqual(out["status"], "rejected")
        sql = conn.fetchrow.await_args.args[0]
        self.assertIn("status = 'rejected'", sql)
        self.assertIn("status = 'pending'", sql)


def _tx_pool(conn):
    class _Tx:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *args):
            return False

    conn.transaction = MagicMock(return_value=_Tx())
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


class WithdrawalPhaseTests(unittest.TestCase):
    def test_awaiting_processing_and_hide_operator(self):
        mod = _withdraw_mod()
        awaiting = mod.player_withdrawal_out(
            {
                "id": 1,
                "status": "pending",
                "operator_id": None,
                "source": "casino",
                "amount_rub": 500,
                "admin_message_id": 99,
            }
        )
        self.assertEqual(awaiting["phase"], "awaiting")
        self.assertTrue(awaiting["cancellable"])
        self.assertEqual(awaiting["status_label"], "В ожидании")
        self.assertNotIn("operator_id", awaiting)
        self.assertNotIn("admin_message_id", awaiting)

        processing = mod.player_withdrawal_out(
            {"id": 1, "status": "pending", "operator_id": 7, "source": "casino"}
        )
        self.assertEqual(processing["phase"], "processing")
        self.assertFalse(processing["cancellable"])
        self.assertIn("3 часов", processing["status_hint"])

        paid = mod.player_withdrawal_out({"id": 1, "status": "paid", "source": "casino"})
        self.assertEqual(paid["phase"], "paid")
        self.assertFalse(paid["cancellable"])

        balance = mod.player_withdrawal_out(
            {"id": 1, "status": "pending", "operator_id": None, "source": "balance"}
        )
        self.assertEqual(balance["phase"], "awaiting")
        self.assertFalse(balance["cancellable"])


class CancelCasinoWithdrawalTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_pending_unclaimed(self):
        mod = _withdraw_mod()
        pending = {
            "id": 5,
            "referrer_user_id": 1,
            "status": "pending",
            "operator_id": None,
            "source": "casino",
            "amount_rub": 500,
        }
        canceled = {**pending, "status": "canceled"}
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        conn.fetchrow = AsyncMock(side_effect=[pending, canceled])
        with patch("user_referral_withdraw.get_pool", return_value=_tx_pool(conn)):
            out = await mod.cancel_casino_withdrawal(1, 5)
        self.assertEqual(out["status"], "canceled")
        update_sql = conn.fetchrow.await_args_list[1].args[0]
        self.assertIn("status = 'canceled'", update_sql)
        self.assertIn("operator_id IS NULL", update_sql)

    async def test_cancel_after_claim_not_cancellable(self):
        mod = _withdraw_mod()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 5,
                "referrer_user_id": 1,
                "status": "pending",
                "operator_id": 3,
                "source": "casino",
            }
        )
        with patch("user_referral_withdraw.get_pool", return_value=_tx_pool(conn)):
            with self.assertRaises(mod.WithdrawalCancelError) as ctx:
                await mod.cancel_casino_withdrawal(1, 5)
        self.assertEqual(ctx.exception.code, "not_cancellable")

    async def test_cancel_other_user_not_found(self):
        mod = _withdraw_mod()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 5,
                "referrer_user_id": 99,
                "status": "pending",
                "operator_id": None,
                "source": "casino",
            }
        )
        with patch("user_referral_withdraw.get_pool", return_value=_tx_pool(conn)):
            with self.assertRaises(mod.WithdrawalCancelError) as ctx:
                await mod.cancel_casino_withdrawal(1, 5)
        self.assertEqual(ctx.exception.code, "not_found")

    async def test_cancel_balance_source_not_found(self):
        mod = _withdraw_mod()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 5,
                "referrer_user_id": 1,
                "status": "pending",
                "operator_id": None,
                "source": "balance",
            }
        )
        with patch("user_referral_withdraw.get_pool", return_value=_tx_pool(conn)):
            with self.assertRaises(mod.WithdrawalCancelError) as ctx:
                await mod.cancel_casino_withdrawal(1, 5)
        self.assertEqual(ctx.exception.code, "not_found")


class ListUserWithdrawalsFilterTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_filters_casino_and_reads_operator(self):
        mod = _withdraw_mod()
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": 5,
                    "amount_rub": 500,
                    "method": "card",
                    "requisites": "2200",
                    "crypto": None,
                    "network": None,
                    "status": "pending",
                    "network_fee_rub": 100,
                    "payout_amount_rub": 400,
                    "source": "casino",
                    "created_at": None,
                    "processed_at": None,
                    "payout_tx_hash": None,
                    "operator_id": None,
                }
            ]
        )
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch("user_referral_withdraw.get_pool", return_value=pool):
            rows = await mod.list_user_withdrawals(1, source="casino")
        self.assertEqual(rows[0]["phase"], "awaiting")
        self.assertTrue(rows[0]["cancellable"])
        sql = conn.fetch.await_args.args[0]
        self.assertIn("operator_id", sql)
        self.assertIn("COALESCE(source, 'balance') = $2", sql)
        self.assertEqual(conn.fetch.await_args.args[2], "casino")


class CasinoPendingCapTests(unittest.IsolatedAsyncioTestCase):
    def test_wait_message_rounds_up_minutes(self):
        mod = _withdraw_mod()
        now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        self.assertIsNone(mod.casino_create_wait_message(None, now=now))
        self.assertIsNone(mod.casino_create_wait_message(now - timedelta(minutes=6), now=now))
        self.assertEqual(
            mod.casino_create_wait_message(now - timedelta(minutes=1), now=now),
            "Следующую заявку можно создать через 4 мин.",
        )
        self.assertEqual(
            mod.casino_create_wait_message(now - timedelta(seconds=10), now=now),
            "Следующую заявку можно создать через 5 мин.",
        )

    async def test_casino_rejects_sixth_pending(self):
        mod = _withdraw_mod()
        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(return_value=5)
        with self.assertRaises(ValueError) as ctx:
            await mod._lock_and_check_pending(conn, 1, mod.SOURCE_CASINO)
        self.assertEqual(str(ctx.exception), mod.CASINO_PENDING_MAX_MSG)
        self.assertEqual(conn.fetchval.await_count, 1)

    async def test_casino_rejects_inside_five_minutes(self):
        mod = _withdraw_mod()
        now = datetime.now(timezone.utc)
        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[1, now - timedelta(minutes=1)])
        with self.assertRaises(ValueError) as ctx:
            await mod._lock_and_check_pending(conn, 1, mod.SOURCE_CASINO)
        self.assertIn("через", str(ctx.exception))

    async def test_casino_allows_after_interval(self):
        mod = _withdraw_mod()
        now = datetime.now(timezone.utc)
        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[2, now - timedelta(minutes=6)])
        await mod._lock_and_check_pending(conn, 1, mod.SOURCE_CASINO)
        self.assertEqual(conn.fetchval.await_count, 2)

    async def test_balance_still_one_pending(self):
        mod = _withdraw_mod()
        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        with patch("user_unified_balance.get_partner_campaign_conn", new=AsyncMock()) as partner:
            with self.assertRaises(ValueError) as ctx:
                await mod._lock_and_check_pending(conn, 1, mod.SOURCE_BALANCE)
        self.assertIn("уже есть заявка", str(ctx.exception))
        partner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
