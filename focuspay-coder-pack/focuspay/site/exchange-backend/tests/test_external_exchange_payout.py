"""Тесты заявок на вывод внештатника."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from external_exchange_calc import calc_payout


class WithdrawFeeByCoinTests(unittest.TestCase):
    def test_usdt_three_others_two(self):
        from external_exchange_payout import min_payout_gross_usd, withdraw_fee_usd, withdraw_fees_map

        self.assertEqual(withdraw_fee_usd("usdt"), 3.0)
        self.assertEqual(withdraw_fee_usd("btc"), 2.0)
        self.assertEqual(withdraw_fee_usd("ltc"), 2.0)
        self.assertEqual(withdraw_fee_usd("trx"), 2.0)
        self.assertEqual(min_payout_gross_usd("usdt"), 3.01)
        self.assertEqual(min_payout_gross_usd("btc"), 2.01)
        fees = withdraw_fees_map()
        self.assertEqual(fees["usdt"], 3.0)
        self.assertEqual(fees["btc"], 2.0)


class MaybeCreatePayoutOnCreditTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_without_intent(self):
        from external_exchange_payout import maybe_create_payout_on_credit

        result = await maybe_create_payout_on_credit(
            AsyncMock(),
            {"id": 1, "payout_on_credit": False},
            confirmed_by="op:1",
        )
        self.assertEqual(result["credit_payout_status"], "skipped_no_intent")

    async def test_skips_when_amount_below_fee(self):
        from external_exchange_payout import maybe_create_payout_on_credit

        with patch(
            "external_exchange_payout._notify_credit_payout_skipped",
            new_callable=AsyncMock,
        ) as notify:
            result = await maybe_create_payout_on_credit(
                AsyncMock(),
                {
                    "id": 4,
                    "exchanger_id": 2,
                    "payout_on_credit": True,
                    "payout_wallet": "TXwallet123456",
                    "crypto": "usdt",
                    "principal_usdt": 2.5,
                },
                confirmed_by="op:1",
            )
        self.assertEqual(result["credit_payout_status"], "skipped_too_small")
        notify.assert_awaited_once()

    async def test_skips_when_pending_exists(self):
        from external_exchange_payout import maybe_create_payout_on_credit

        conn = AsyncMock()
        with patch(
            "external_exchange_payout.has_pending_payout",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "external_exchange_payout._notify_credit_payout_skipped",
            new_callable=AsyncMock,
        ) as notify:
            result = await maybe_create_payout_on_credit(
                conn,
                {
                    "id": 5,
                    "exchanger_id": 2,
                    "payout_on_credit": True,
                    "payout_wallet": "TXwallet123456",
                    "crypto": "btc",
                    "principal_usdt": 40.0,
                },
                confirmed_by="op:1",
            )
        self.assertEqual(result["credit_payout_status"], "skipped_pending")
        notify.assert_awaited_once()

    async def test_creates_payout_and_links_deal(self):
        from external_exchange_payout import maybe_create_payout_on_credit

        conn = AsyncMock()
        conn.execute = AsyncMock()
        payout = {
            "id": 99,
            "gross_usd": 40.0,
            "fee_usd": 2.0,
            "net_usd": 38.0,
            "crypto": "btc",
            "crypto_amount": 0.001,
        }
        with patch(
            "external_exchange_payout.has_pending_payout",
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            "external_exchange_payout.create_payout_request",
            new_callable=AsyncMock,
            return_value=payout,
        ) as create, patch(
            "external_exchange_payout._notify_credit_payout_created",
            new_callable=AsyncMock,
        ), patch(
            "external_exchange_payout._market_rates",
            new_callable=AsyncMock,
            return_value={"usdt": 90.0, "btc": 9000000.0},
        ):
            result = await maybe_create_payout_on_credit(
                conn,
                {
                    "id": 8,
                    "exchanger_id": 2,
                    "payout_on_credit": True,
                    "payout_wallet": "bc1qwalletxxxxxxxx",
                    "crypto": "btc",
                    "principal_usdt": 40.0,
                    "created_by": "ex:shop",
                },
                confirmed_by="payfast:webhook",
                exchanger_name="Shop",
            )
        self.assertEqual(result["credit_payout_status"], "created")
        self.assertEqual(result["payout_id"], 99)
        create.assert_awaited_once()
        self.assertEqual(create.await_args.kwargs["crypto"], "btc")
        self.assertEqual(create.await_args.kwargs["deal_id"], 8)
        conn.execute.assert_awaited()


class DealPublicOutSettlementTests(unittest.TestCase):
    def test_payout_fields(self):
        from external_deal_payin import deal_public_out

        out = deal_public_out(
            {
                "id": 3,
                "status": "awaiting_receipt",
                "amount_rub": 10000,
                "client_pays_rub": 11500,
                "principal_usdt": 120.0,
                "crypto": "btc",
                "markup_pct": 15,
                "markup_mode": "on_deal",
                "payout_on_credit": True,
                "payout_wallet": "bc1qwalletxxxxxxxx",
                "payout_id": None,
            }
        )
        self.assertTrue(out["payout_on_credit"])
        self.assertEqual(out["payout_wallet"], "bc1qwalletxxxxxxxx")
        self.assertEqual(out["payout_fee_usd"], 2.0)
        self.assertIsNone(out["payout_id"])


class DealCreateBodySettlementTests(unittest.TestCase):
    def test_crypto_requires_wallet(self):
        try:
            from pydantic import ValidationError
            from routers.exchanger import DealCreateBody
        except ModuleNotFoundError as e:
            self.skipTest(f"missing dependency: {e}")
        with self.assertRaises(ValidationError):
            DealCreateBody(amount_rub=1000, payout_on_credit=True, payout_wallet="short")

    def test_balance_clears_wallet(self):
        try:
            from routers.exchanger import DealCreateBody
        except ModuleNotFoundError as e:
            self.skipTest(f"missing dependency: {e}")
        body = DealCreateBody(amount_rub=1000, payout_on_credit=False, payout_wallet="TXwallet123456")
        self.assertFalse(body.payout_on_credit)
        self.assertIsNone(body.payout_wallet)

    def test_amount_crypto_only(self):
        try:
            from pydantic import ValidationError
            from routers.exchanger import DealCreateBody
        except ModuleNotFoundError as e:
            self.skipTest(f"missing dependency: {e}")
        body = DealCreateBody(amount_crypto=1.5243, crypto="ltc")
        self.assertEqual(body.amount_crypto, 1.5243)
        self.assertIsNone(body.amount_rub)
        with self.assertRaises(ValidationError):
            DealCreateBody(crypto="ltc")


class AvailableBalanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_available_minus_pending(self):
        from external_exchange_payout import available_balance_usd

        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[150.0, 50.0])
        available = await available_balance_usd(conn, 1)
        self.assertEqual(available, 100.0)


class AdminPendingPayoutApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_pending_payouts_returns_joined_rows(self):
        try:
            from routers.admin_external import list_pending_payouts
        except ModuleNotFoundError as e:
            self.skipTest(f"missing dependency: {e}")

        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": 10,
                    "exchanger_id": 3,
                    "gross_usd": 55.0,
                    "fee_usd": 3.0,
                    "net_usd": 52.0,
                    "crypto": "usdt",
                    "crypto_amount": 52.0,
                    "status": "pending",
                    "note": "Кошелёк: TX123",
                    "created_at": None,
                    "exchanger_name": "kanglo",
                    "exchanger_username": "inn_kanglo",
                }
            ]
        )
        conn.fetchval = AsyncMock(return_value=1)
        pool = MagicMock()
        acquire_ctx = AsyncMock()
        acquire_ctx.__aenter__.return_value = conn
        acquire_ctx.__aexit__.return_value = False
        pool.acquire.return_value = acquire_ctx

        with patch("routers.admin_external.get_pool", AsyncMock(return_value=pool)):
            result = await list_pending_payouts(limit=50, offset=0, admin={"id": 1})

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["id"], 10)
        self.assertEqual(result["items"][0]["exchanger_name"], "kanglo")
        self.assertEqual(result["items"][0]["exchanger_username"], "inn_kanglo")


class UpdatePendingPayoutFeeTests(unittest.IsolatedAsyncioTestCase):
    async def test_updates_fee_net_and_crypto(self):
        from external_exchange_payout import update_pending_payout_fee

        pending = {
            "id": 7,
            "exchanger_id": 2,
            "gross_usd": 100.0,
            "fee_usd": 3.0,
            "net_usd": 97.0,
            "crypto": "usdt",
            "crypto_amount": 97.0,
            "crypto_rate_usd": 1.0,
            "status": "pending",
            "note": "Кошелёк: abc",
        }
        updated = {
            **pending,
            "fee_usd": 5.0,
            "net_usd": 95.0,
            "crypto_amount": 95.0,
            "note": "Кошелёк: abc [fee $3.00→$5.00 by admin]",
        }

        conn = AsyncMock()
        tx = AsyncMock()
        tx.__aenter__.return_value = None
        tx.__aexit__.return_value = False
        conn.transaction = MagicMock(return_value=tx)
        conn.fetchrow = AsyncMock(side_effect=[pending, updated])

        result = await update_pending_payout_fee(
            conn,
            7,
            fee_usd=5.0,
            market_rub={"usdt": 90.0},
            updated_by="admin",
        )
        self.assertEqual(result["fee_usd"], 5.0)
        self.assertEqual(result["net_usd"], 95.0)
        self.assertEqual(result["crypto_amount"], 95.0)
        update_sql = conn.fetchrow.await_args_list[1].args[0]
        self.assertIn("fee_usd = $2", update_sql)
        self.assertEqual(conn.fetchrow.await_args_list[1].args[2], 5.0)
        self.assertEqual(conn.fetchrow.await_args_list[1].args[3], 95.0)

    async def test_rejects_fee_gte_gross(self):
        from fastapi import HTTPException

        from external_exchange_payout import update_pending_payout_fee

        pending = {
            "id": 7,
            "exchanger_id": 2,
            "gross_usd": 10.0,
            "fee_usd": 3.0,
            "net_usd": 7.0,
            "crypto": "usdt",
            "crypto_amount": 7.0,
            "crypto_rate_usd": 1.0,
            "status": "pending",
            "note": "",
        }
        conn = AsyncMock()
        tx = AsyncMock()
        tx.__aenter__.return_value = None
        tx.__aexit__.return_value = False
        conn.transaction = MagicMock(return_value=tx)
        conn.fetchrow = AsyncMock(return_value=pending)

        with self.assertRaises(HTTPException) as ctx:
            await update_pending_payout_fee(
                conn,
                7,
                fee_usd=10.0,
                market_rub={"usdt": 90.0},
                updated_by="admin",
            )
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
