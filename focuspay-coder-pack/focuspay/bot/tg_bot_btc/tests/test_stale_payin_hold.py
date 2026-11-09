"""Зависший AWAITING_CHECK + receipt_ops_pending больше не крутится вечно."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from services.stale_payin_hold import (
    ACTION_COMPLETE,
    ACTION_EXPIRE,
    ACTION_HOLD_OPS,
    ACTION_HOLD_PF,
    ACTION_SKIP_SETTLED,
    ACTION_SUPERSEDE,
    crypto_amounts_match,
    decide_stale_payin_action,
    merchant_cancel_is_not_pending,
    payout_identity_matches,
    receipt_ops_pending_is_fresh,
    wallets_match,
)
from services.order_expirer import expire_orders_task

NOW = datetime(2026, 9, 8, 6, 30, tzinfo=timezone.utc)


class CryptoMatchTests(unittest.TestCase):
    def test_ltc_matches_truncated_manual_payout(self):
        self.assertTrue(
            crypto_amounts_match(
                2.5313194530774936,
                2.53131945,
                "ltc",
            )
        )

    def test_different_amounts_do_not_match(self):
        self.assertFalse(crypto_amounts_match(2.53, 2.54, "ltc"))

    def test_usdt_two_decimals(self):
        self.assertTrue(crypto_amounts_match(100.001, 100.00, "usdt"))

    def test_empty_wallets_do_not_match(self):
        self.assertFalse(wallets_match("", ""))
        self.assertTrue(wallets_match("LtcWallet1", "LtcWallet1"))
        self.assertFalse(wallets_match("LtcWallet1", "ltcwallet1"))

    def test_manual_paid_without_wallet_matches_payin(self):
        open_order = {
            "crypto": "ltc",
            "crypto_amount": 2.5313194530774936,
            "fiat_amount": 13613,
            "wallet_address": "LtcWallet1",
            "merchant_order_id": "pf-uuid",
        }
        paid = {
            "crypto": "ltc",
            "crypto_amount": 2.53131945,
            "fiat_amount": 13613,
            "wallet_address": "",
            "order_source": "manual_operator",
        }
        self.assertTrue(payout_identity_matches(open_order, paid))

    def test_empty_paid_wallet_without_manual_source_does_not_match(self):
        open_order = {
            "crypto": "usdt",
            "crypto_amount": 100,
            "fiat_amount": 9000,
            "wallet_address": "Txxx",
            "merchant_order_id": "pf-uuid",
        }
        paid = {
            "crypto": "usdt",
            "crypto_amount": 100,
            "fiat_amount": 9000,
            "wallet_address": "",
            "order_source": "payfast",
        }
        self.assertFalse(payout_identity_matches(open_order, paid))


class MerchantCancelErrorTests(unittest.TestCase):
    def test_payfast_not_pending_phrase(self):
        self.assertTrue(merchant_cancel_is_not_pending("Заявка не в ожидании"))
        self.assertFalse(merchant_cancel_is_not_pending("not cancellable"))
        self.assertFalse(merchant_cancel_is_not_pending(""))


class OpsPendingFreshnessTests(unittest.TestCase):
    def test_recent_submit_is_fresh(self):
        order = {
            "payment_snapshot": {
                "receipt_ops_pending": True,
                "receipt_ops_submitted_at": (NOW - timedelta(minutes=15)).isoformat(),
            }
        }
        self.assertTrue(
            receipt_ops_pending_is_fresh(order, now=NOW, max_minutes=120)
        )

    def test_sixteen_day_hold_is_stale(self):
        order = {
            "payment_snapshot": {
                "receipt_ops_pending": True,
                "receipt_ops_submitted_at": (NOW - timedelta(days=16)).isoformat(),
            }
        }
        self.assertFalse(
            receipt_ops_pending_is_fresh(order, now=NOW, max_minutes=120)
        )


class DecideStalePayinTests(unittest.TestCase):
    def test_sibling_paid_wins_even_if_ops_hold_is_fresh(self):
        self.assertEqual(
            decide_stale_payin_action(
                ops_pending=True,
                ops_pending_fresh=True,
                pf_ok=True,
                pf_err=None,
                has_sibling_paid=True,
                video_hold=False,
            ),
            ACTION_SUPERSEDE,
        )

    def test_fresh_ops_hold_without_payout_is_kept(self):
        self.assertEqual(
            decide_stale_payin_action(
                ops_pending=True,
                ops_pending_fresh=True,
                pf_ok=None,
                pf_err=None,
                has_sibling_paid=False,
                video_hold=False,
            ),
            ACTION_HOLD_OPS,
        )

    def test_stale_hold_settled_without_sibling_goes_to_payout(self):
        self.assertEqual(
            decide_stale_payin_action(
                ops_pending=True,
                ops_pending_fresh=False,
                pf_ok=True,
                pf_err=None,
                has_sibling_paid=False,
                video_hold=False,
            ),
            ACTION_COMPLETE,
        )

    def test_stale_hold_does_not_auto_complete_video(self):
        self.assertEqual(
            decide_stale_payin_action(
                ops_pending=True,
                ops_pending_fresh=False,
                pf_ok=True,
                pf_err=None,
                has_sibling_paid=False,
                video_hold=True,
            ),
            ACTION_SKIP_SETTLED,
        )

    def test_stale_hold_merchant_canceled_expires(self):
        self.assertEqual(
            decide_stale_payin_action(
                ops_pending=True,
                ops_pending_fresh=False,
                pf_ok=False,
                pf_err="payfast_status_canceled",
                has_sibling_paid=False,
                video_hold=False,
            ),
            ACTION_EXPIRE,
        )

    def test_payfast_review_still_held(self):
        self.assertEqual(
            decide_stale_payin_action(
                ops_pending=False,
                ops_pending_fresh=False,
                pf_ok=False,
                pf_err="payfast_check_pending",
                has_sibling_paid=False,
                video_hold=False,
            ),
            ACTION_HOLD_PF,
        )

    def test_paid_awaiting_trader_still_held(self):
        self.assertEqual(
            decide_stale_payin_action(
                ops_pending=False,
                ops_pending_fresh=False,
                pf_ok=False,
                pf_err="payfast_awaiting_trader",
                has_sibling_paid=False,
                video_hold=False,
            ),
            ACTION_HOLD_PF,
        )


def _zombie_ops_order(**overrides) -> dict:
    order = {
        "order_id": "13584070",
        "user_id": 8713438176,
        "direction": "buy",
        "status": "AWAITING_CHECK",
        "crypto": "ltc",
        "crypto_amount": 2.5313194530774936,
        "fiat_amount": 13613.0,
        "wallet_address": "LtcTestWallet1111111111111111111111111",
        "required_receipt_type": 2,
        "merchant_order_id": "payfast-uuid",
        "created_at": NOW - timedelta(days=16),
        "expires_at": NOW - timedelta(minutes=1),
        "payment_snapshot": {
            "receipt_ops_pending": True,
            "receipt_ops_submitted_at": (NOW - timedelta(days=16)).isoformat(),
        },
    }
    order.update(overrides)
    return order


class ExpirerZombieHoldTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self,
        order: dict,
        *,
        sibling=None,
        pf_result=(True, None, {"status": "SUCCSES"}),
        close_superseded=None,
        complete_settled=None,
    ):
        shutdown = asyncio.Event()
        passes = {"n": 0}

        async def expired_rows(limit=100):
            passes["n"] += 1
            if passes["n"] > 1:
                shutdown.set()
                return []
            return [{"order_id": order["order_id"], "user_id": order["user_id"]}]

        extend = AsyncMock()
        update_status = AsyncMock(return_value=True)
        close = close_superseded or AsyncMock(return_value=True)
        complete = complete_settled or AsyncMock(return_value=True)

        with patch(
            "services.order_expirer._send_payment_nudges", new=AsyncMock()
        ), patch(
            "services.order_expirer.release_orphan_balance_holds",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.order_expirer.get_expired_orders", new=expired_rows
        ), patch(
            "services.order_expirer.get_order", new=AsyncMock(return_value=order)
        ), patch(
            "services.order_expirer.update_order_status", new=update_status
        ), patch(
            "services.db.extend_order_expires_at", new=extend
        ), patch(
            "services.db.find_matching_paid_buy_payout",
            new=AsyncMock(return_value=sibling),
        ), patch(
            "services.stale_payin_hold.close_superseded_payin", new=close
        ), patch(
            "services.stale_payin_hold.complete_stale_ops_pending_if_settled",
            new=complete,
        ), patch(
            "services.payfast_payin_guard.verify_payfast_ready_for_payout",
            new=AsyncMock(return_value=pf_result),
        ), patch(
            "services.merchant_api_helpers.cancel_payin_for_order", new=AsyncMock()
        ), patch(
            "services.stale_payin_hold.sweep_superseded_completed_payins",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.order_expirer.CHECK_INTERVAL", 0.01
        ):
            await expire_orders_task(AsyncMock(), shutdown_event=shutdown)

        return extend, update_status, close, complete

    async def test_fresh_ops_pending_still_extended(self):
        order = _zombie_ops_order(
            payment_snapshot={
                "receipt_ops_pending": True,
                "receipt_ops_submitted_at": (
                    datetime.now(timezone.utc) - timedelta(minutes=10)
                ).isoformat(),
            }
        )
        extend, update_status, close, complete = await self._run(
            order, sibling=None, pf_result=(False, "payfast_not_paid", {})
        )
        close.assert_not_awaited()
        complete.assert_not_awaited()
        update_status.assert_not_awaited()
        extend.assert_awaited()

    async def test_stale_ops_pending_with_manual_payout_is_superseded(self):
        sibling = {
            "order_id": "OPBE46A1CA5FFC99B9",
            "status": "PAID",
            "crypto_amount": 2.53131945,
        }
        _extend, update_status, close, complete = await self._run(
            _zombie_ops_order(), sibling=sibling
        )
        close.assert_awaited_once()
        complete.assert_not_awaited()
        update_status.assert_not_awaited()

    async def test_stale_ops_pending_settled_without_sibling_completes(self):
        _extend, update_status, close, complete = await self._run(
            _zombie_ops_order(), sibling=None
        )
        complete.assert_awaited_once()
        close.assert_not_awaited()
        update_status.assert_not_awaited()

    async def test_sibling_lookup_error_does_not_auto_complete(self):
        async def boom(_order):
            raise TypeError("can't subtract offset-naive and offset-aware datetimes")

        order = _zombie_ops_order()
        shutdown = asyncio.Event()
        passes = {"n": 0}

        async def expired_rows(limit=100):
            passes["n"] += 1
            if passes["n"] > 1:
                shutdown.set()
                return []
            return [{"order_id": order["order_id"], "user_id": order["user_id"]}]

        extend = AsyncMock()
        complete = AsyncMock(return_value=True)
        close = AsyncMock(return_value=True)

        with patch(
            "services.order_expirer._send_payment_nudges", new=AsyncMock()
        ), patch(
            "services.order_expirer.release_orphan_balance_holds",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.order_expirer.get_expired_orders", new=expired_rows
        ), patch(
            "services.order_expirer.get_order", new=AsyncMock(return_value=order)
        ), patch(
            "services.order_expirer.update_order_status", new=AsyncMock(return_value=True)
        ), patch(
            "services.db.extend_order_expires_at", new=extend
        ), patch(
            "services.db.find_matching_paid_buy_payout",
            new=boom,
        ), patch(
            "services.stale_payin_hold.close_superseded_payin", new=close
        ), patch(
            "services.stale_payin_hold.complete_stale_ops_pending_if_settled",
            new=complete,
        ), patch(
            "services.stale_payin_hold.sweep_superseded_completed_payins",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.payfast_payin_guard.verify_payfast_ready_for_payout",
            new=AsyncMock(return_value=(True, None, {"status": "SUCCSES"})),
        ), patch(
            "services.merchant_api_helpers.cancel_payin_for_order", new=AsyncMock()
        ), patch(
            "services.order_expirer.CHECK_INTERVAL", 0.01
        ):
            await expire_orders_task(AsyncMock(), shutdown_event=shutdown)

        complete.assert_not_awaited()
        close.assert_not_awaited()
        extend.assert_awaited()

    async def test_stale_ops_pending_merchant_dead_expires(self):
        _extend, update_status, close, complete = await self._run(
            _zombie_ops_order(),
            sibling=None,
            pf_result=(False, "payfast_status_expired", {}),
        )
        close.assert_not_awaited()
        complete.assert_not_awaited()
        update_status.assert_awaited_once_with("13584070", "EXPIRED")


class ConfirmCancelFallbackTests(unittest.IsolatedAsyncioTestCase):
    def _update(self):
        update = MagicMock()
        update.effective_user.id = 123
        update.message.reply_text = AsyncMock()
        return update

    def _context(self):
        context = MagicMock()
        context.user_data = {"step": "confirm_cancel"}
        return context

    def _buy_order(self):
        return {
            "order_id": "13584070",
            "direction": "buy",
            "status": "AWAITING_CHECK",
            "merchant_order_id": "payfast-uuid",
        }

    async def test_not_pending_with_sibling_closes_locally(self):
        from handlers.exchange_flow import confirm_cancel_handler

        update = self._update()
        context = self._context()
        with patch("handlers.exchange_flow.rate_limit_ok", new=AsyncMock(return_value=True)), patch(
            "handlers.exchange_flow.get_active_order_by_user",
            new=AsyncMock(return_value=self._buy_order()),
        ), patch(
            "services.merchant_api_helpers.cancel_payin_for_order",
            new=AsyncMock(
                return_value={
                    "status": 400,
                    "ok": False,
                    "body": {"error": "Заявка не в ожидании"},
                }
            ),
        ), patch(
            "services.stale_payin_hold.resolve_failed_merchant_cancel",
            new=AsyncMock(return_value="closed_superseded"),
        ), patch(
            "handlers.exchange_flow.update_order_status",
            new=AsyncMock(),
        ) as update_status, patch(
            "services.db.clear_receipt_ops_pending",
            new=AsyncMock(),
        ), patch(
            "services.db.get_buyer_payfast_conversion",
            new=AsyncMock(return_value={"paid": 1, "failed": 0}),
        ), patch(
            "handlers.exchange_flow.menu_for",
            new=AsyncMock(return_value=None),
        ):
            await confirm_cancel_handler(update, context)

        update_status.assert_not_awaited()
        text = update.message.reply_text.await_args.args[0]
        self.assertIn("уже была отправлена", text)

    async def test_settled_without_sibling_refuses_cancel(self):
        from handlers.exchange_flow import confirm_cancel_handler

        update = self._update()
        context = self._context()
        with patch("handlers.exchange_flow.rate_limit_ok", new=AsyncMock(return_value=True)), patch(
            "handlers.exchange_flow.get_active_order_by_user",
            new=AsyncMock(return_value=self._buy_order()),
        ), patch(
            "services.merchant_api_helpers.cancel_payin_for_order",
            new=AsyncMock(
                return_value={
                    "status": 400,
                    "ok": False,
                    "body": {"error": "Заявка не в ожидании"},
                }
            ),
        ), patch(
            "services.stale_payin_hold.resolve_failed_merchant_cancel",
            new=AsyncMock(return_value="settled"),
        ), patch(
            "handlers.exchange_flow.update_order_status",
            new=AsyncMock(),
        ) as update_status, patch(
            "handlers.exchange_flow.menu_for",
            new=AsyncMock(return_value=None),
        ):
            await confirm_cancel_handler(update, context)

        update_status.assert_not_awaited()
        text = update.message.reply_text.await_args.args[0]
        self.assertIn("уже подтверждена", text)


class FindMatchingPaidQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_filters_same_user_buy_paid(self):
        from services.db import find_matching_paid_buy_payout

        captured = {}

        async def fetch(query, *args):
            captured["query"] = query
            captured["args"] = args
            return [
                {
                    "order_id": "OP1",
                    "wallet_address": "LtcTestWallet1111111111111111111111111",
                    "crypto_amount": 2.53131945,
                }
            ]

        conn = AsyncMock()
        conn.fetch = fetch
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        order = _zombie_ops_order()
        with patch("services.db.get_pool", new=AsyncMock(return_value=pool)):
            found = await find_matching_paid_buy_payout(order)

        self.assertEqual(found["order_id"], "OP1")
        self.assertIn("status = 'PAID'", captured["query"])
        self.assertEqual(captured["args"][0], 8713438176)


if __name__ == "__main__":
    unittest.main()
