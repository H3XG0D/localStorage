"""Tests for manual buy payout transition."""
from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.buy_payout import (
    confirm_awaiting_check_buy_payout,
    confirm_buy_payout,
    confirm_manual_buy_payout,
    normalize_tx_hash,
)
from services.db import (
    transition_awaiting_check_buy_payout_to_paid_in_tx,
    transition_buy_payout_to_paid_in_tx,
    transition_manual_buy_payout_to_paid_in_tx,
    update_order_status,
)


class ConfirmManualBuyPayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_tx(self):
        ok, err, order = await confirm_manual_buy_payout(
            "OP123",
            tx_hash="abc",
            actor="test",
        )
        self.assertFalse(ok)
        self.assertEqual(err, "invalid_tx")
        self.assertIsNone(order)

    async def test_success_path(self):
        tx = "a" * 64
        order_out = {
            "order_id": "OP123",
            "status": "PAID",
            "crypto": "ltc",
            "user_id": 1,
        }

        mock_conn = MagicMock()
        mock_tx = MagicMock()
        mock_tx.__aenter__ = AsyncMock(return_value=None)
        mock_tx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire

        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value={"order_id": "OP123", "status": "OPERATOR_PENDING"}),
        ), patch(
            "services.db.get_pool",
            new=AsyncMock(return_value=mock_pool),
        ), patch(
            "services.db.transition_manual_buy_payout_to_paid_in_tx",
            new=AsyncMock(return_value=(True, None, order_out)),
        ), patch(
            "services.stale_payin_hold.close_open_payins_superseded_by_paid",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.buy_payout.notify_buyer_paid",
            new=AsyncMock(),
        ), patch(
            "services.order_ops_notify.notify_ops_order",
            new=AsyncMock(),
        ):
            pending_before = set(asyncio.all_tasks())
            ok, err, out = await confirm_manual_buy_payout(
                "OP123",
                tx_hash=tx,
                actor="telegram:1",
            )
            await asyncio.sleep(0)
            for task in asyncio.all_tasks() - pending_before:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(out["order_id"], "OP123")
        self.assertEqual(normalize_tx_hash(tx), tx)

    async def test_slow_notify_does_not_block_confirm(self):
        tx = "a" * 64
        order_out = {
            "order_id": "OP123",
            "status": "PAID",
            "crypto": "ltc",
            "user_id": 1,
        }
        started = asyncio.Event()

        async def slow_notify(*_a, **_k):
            started.set()
            await asyncio.sleep(5)

        mock_conn = MagicMock()
        mock_tx = MagicMock()
        mock_tx.__aenter__ = AsyncMock(return_value=None)
        mock_tx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction.return_value = mock_tx
        mock_pool = MagicMock()
        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire

        with patch(
            "services.db.get_order",
            new=AsyncMock(return_value={"order_id": "OP123", "status": "OPERATOR_PENDING"}),
        ), patch(
            "services.db.get_pool",
            new=AsyncMock(return_value=mock_pool),
        ), patch(
            "services.db.transition_manual_buy_payout_to_paid_in_tx",
            new=AsyncMock(return_value=(True, None, order_out)),
        ), patch(
            "services.stale_payin_hold.close_open_payins_superseded_by_paid",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.buy_payout.notify_buyer_paid",
            new=slow_notify,
        ), patch(
            "services.order_ops_notify.notify_ops_order",
            new=AsyncMock(),
        ):
            pending_before = set(asyncio.all_tasks())
            t0 = time.monotonic()
            ok, err, _out = await confirm_manual_buy_payout(
                "OP123",
                tx_hash=tx,
                actor="telegram:1",
            )
            elapsed = time.monotonic() - t0
            self.assertTrue(ok)
            self.assertIsNone(err)
            self.assertLess(elapsed, 1.0)
            await asyncio.wait_for(started.wait(), timeout=1)
            for task in asyncio.all_tasks() - pending_before:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


class OperatorCompletedAtRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_buy_payout_sets_sla_timestamp_without_overwrite(self):
        order = {
            "order_id": "OP100",
            "direction": "buy",
            "status": "COMPLETED",
            "crypto_amount": 1,
            "fiat_amount": 100,
            "rate": 100,
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=[order, None, order])
        conn.execute = AsyncMock()
        with patch(
            "services.db._compute_buy_network_fee_rub", new=AsyncMock(return_value=0)
        ), patch(
            "services.db._apply_paid_side_effects_in_tx", new=AsyncMock()
        ), patch(
            "services.buy_payout_validate.validate_buy_payout_crypto",
            return_value=(True, None),
        ):
            ok, err, _ = await transition_buy_payout_to_paid_in_tx(
                conn,
                "OP100",
                payout_tx_hash="a" * 64,
                payout_confirmed_by="operator:1",
                operator_id=1,
            )

        self.assertTrue(ok)
        self.assertIsNone(err)
        sql = conn.execute.await_args.args[0]
        self.assertIn("operator_completed_at = COALESCE(operator_completed_at, now())", sql)

    async def test_manual_buy_payout_sets_sla_timestamp_without_overwrite(self):
        order = {
            "order_id": "OP101",
            "direction": "buy",
            "status": "OPERATOR_PENDING",
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=[order, None, order])
        conn.execute = AsyncMock()
        with patch(
            "services.db._compute_buy_network_fee_rub", new=AsyncMock(return_value=0)
        ), patch(
            "services.db._apply_paid_side_effects_in_tx", new=AsyncMock()
        ):
            ok, err, _ = await transition_manual_buy_payout_to_paid_in_tx(
                conn,
                "OP101",
                payout_tx_hash="b" * 64,
                payout_confirmed_by="operator:1",
                operator_id=1,
            )

        self.assertTrue(ok)
        self.assertIsNone(err)
        sql = conn.execute.await_args.args[0]
        self.assertIn("operator_completed_at = COALESCE(operator_completed_at, now())", sql)

    async def test_generic_completion_updates_status_and_sla_atomically(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"status": "PENDING", "direction": "sell"})
        conn.execute = AsyncMock()
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=None)
        conn.transaction.return_value = tx
        pool = MagicMock()
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool.acquire.return_value = acquire

        with patch("services.db.get_pool", new=AsyncMock(return_value=pool)), patch(
            "services.buy_order_service.handle_order_paid_side_effects", new=AsyncMock()
        ), patch("services.bot_context.get_bot", return_value=MagicMock()):
            self.assertTrue(await update_order_status("OP102", "COMPLETED"))

        sql = conn.execute.await_args.args[0]
        self.assertIn("SET status = $1::varchar", sql)
        self.assertIn("WHEN $1::varchar IN ('COMPLETED', 'PAID')", sql)
        self.assertIn("COALESCE(operator_completed_at, now())", sql)
        self.assertEqual(conn.execute.await_args.args[1:], ("COMPLETED", "OP102"))


def _status_pool(conn):
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction.return_value = tx
    pool = MagicMock()
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = acquire
    return pool


class UpdateOrderStatusCancelTests(unittest.IsolatedAsyncioTestCase):
    async def test_operator_pending_cancel_survives_ledger_error(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "status": "OPERATOR_PENDING",
                "direction": "buy",
                "payin_requisite_id": None,
            }
        )
        conn.execute = AsyncMock()
        with patch("services.db.get_pool", new=AsyncMock(return_value=_status_pool(conn))), patch(
            "services.db.release_promo_bonus_for_order", new=AsyncMock()
        ), patch(
            "services.order_financial.apply_cancel_financial_effects",
            new=AsyncMock(side_effect=RuntimeError("ledger")),
        ), patch(
            "services.order_financial.apply_cancel_group_if_needed",
            new=AsyncMock(),
        ):
            self.assertTrue(await update_order_status("OP1", "CANCELED"))
        conn.execute.assert_awaited()
        self.assertIn("SET status = $1::varchar", conn.execute.await_args.args[0])
        self.assertEqual(conn.execute.await_args.args[1], "CANCELED")

    async def test_cancel_writes_reason_in_same_update(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "status": "OPERATOR_PENDING",
                "direction": "buy",
                "payin_requisite_id": None,
            }
        )
        conn.execute = AsyncMock()
        with patch("services.db.get_pool", new=AsyncMock(return_value=_status_pool(conn))), patch(
            "services.db.release_promo_bonus_for_order", new=AsyncMock()
        ), patch(
            "services.order_financial.apply_cancel_financial_effects",
            new=AsyncMock(),
        ), patch(
            "services.order_financial.apply_cancel_group_if_needed",
            new=AsyncMock(),
        ):
            self.assertTrue(
                await update_order_status(
                    "OP1",
                    "CANCELED",
                    cancel_reason="неактуально",
                    canceled_by=7,
                )
            )
        sql = conn.execute.await_args.args[0]
        self.assertIn("cancel_reason = COALESCE($3, cancel_reason)", sql)
        self.assertEqual(
            conn.execute.await_args.args[1:],
            ("CANCELED", "OP1", "неактуально", 7),
        )


class TransitionManualBuyIdempotentTests(unittest.IsolatedAsyncioTestCase):
    async def test_already_paid_same_hash_is_ok(self):
        tx = "b" * 64
        paid = {
            "order_id": "OP999",
            "direction": "buy",
            "status": "PAID",
            "payout_tx_hash": tx,
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=paid)
        ok, err, order = await transition_manual_buy_payout_to_paid_in_tx(
            conn,
            "OP999",
            payout_tx_hash=tx,
            payout_confirmed_by="operator:1",
            operator_id=1,
        )
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(order["order_id"], "OP999")
        conn.execute.assert_not_called()

    async def test_already_paid_different_hash_rejected(self):
        paid = {
            "order_id": "OP999",
            "direction": "buy",
            "status": "PAID",
            "payout_tx_hash": "c" * 64,
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=paid)
        ok, err, _order = await transition_manual_buy_payout_to_paid_in_tx(
            conn,
            "OP999",
            payout_tx_hash="d" * 64,
            payout_confirmed_by="operator:1",
            operator_id=1,
        )
        self.assertFalse(ok)
        self.assertEqual(err, "already_paid")


class ConfirmAwaitingCheckBuyPayoutTests(unittest.IsolatedAsyncioTestCase):
    def test_function_importable(self):
        from services import buy_payout as mod

        self.assertTrue(callable(getattr(mod, "confirm_awaiting_check_buy_payout", None)))

    async def test_invalid_tx(self):
        ok, err, order = await confirm_awaiting_check_buy_payout(
            "22745799",
            tx_hash="abc",
            actor="admin:1",
        )
        self.assertFalse(ok)
        self.assertEqual(err, "invalid_tx")
        self.assertIsNone(order)

    async def test_success_path(self):
        tx = "a" * 64
        order_out = {
            "order_id": "22745799",
            "status": "PAID",
            "crypto": "btc",
            "user_id": 1,
        }
        mock_conn = MagicMock()
        mock_tx = MagicMock()
        mock_tx.__aenter__ = AsyncMock(return_value=None)
        mock_tx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction.return_value = mock_tx
        mock_pool = MagicMock()
        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire

        with patch(
            "services.db.get_order",
            new=AsyncMock(
                return_value={"order_id": "22745799", "status": "AWAITING_CHECK"}
            ),
        ), patch(
            "services.db.get_pool",
            new=AsyncMock(return_value=mock_pool),
        ), patch(
            "services.db.transition_awaiting_check_buy_payout_to_paid_in_tx",
            new=AsyncMock(return_value=(True, None, order_out)),
        ), patch(
            "services.buy_payout.notify_buyer_paid",
            new=AsyncMock(),
        ), patch(
            "services.order_ops_notify.notify_ops_order",
            new=AsyncMock(),
        ):
            pending_before = set(asyncio.all_tasks())
            ok, err, out = await confirm_awaiting_check_buy_payout(
                "22745799",
                tx_hash=tx,
                actor="admin:1",
            )
            await asyncio.sleep(0)
            for task in asyncio.all_tasks() - pending_before:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(out["order_id"], "22745799")
        self.assertEqual(normalize_tx_hash(tx), tx)


class TransitionAwaitingCheckBuyPayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_status_completed(self):
        order = {
            "order_id": "OP200",
            "direction": "buy",
            "status": "COMPLETED",
            "crypto_amount": 1,
            "fiat_amount": 100,
            "rate": 100,
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=order)
        ok, err, _ = await transition_awaiting_check_buy_payout_to_paid_in_tx(
            conn,
            "OP200",
            payout_tx_hash="a" * 64,
            payout_confirmed_by="admin:1",
        )
        self.assertFalse(ok)
        self.assertEqual(err, "wrong_status")
        conn.execute.assert_not_called()

    async def test_writes_payout_hash_and_sla(self):
        order = {
            "order_id": "OP201",
            "direction": "buy",
            "status": "AWAITING_CHECK",
            "crypto_amount": 1,
            "fiat_amount": 100,
            "rate": 100,
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=[order, None, order])
        conn.execute = AsyncMock()
        with patch(
            "services.db._compute_buy_network_fee_rub", new=AsyncMock(return_value=0)
        ), patch(
            "services.db._apply_paid_side_effects_in_tx", new=AsyncMock()
        ), patch(
            "services.buy_payout_validate.validate_buy_payout_crypto",
            return_value=(True, None),
        ):
            ok, err, _ = await transition_awaiting_check_buy_payout_to_paid_in_tx(
                conn,
                "OP201",
                payout_tx_hash="e" * 64,
                payout_confirmed_by="admin:1",
                operator_id=1,
            )
        self.assertTrue(ok)
        self.assertIsNone(err)
        sql = conn.execute.await_args.args[0]
        self.assertIn("payout_tx_hash = $1", sql)
        self.assertIn("operator_completed_at = COALESCE(operator_completed_at, now())", sql)
        self.assertEqual(conn.execute.await_args.args[1], "e" * 64)

    async def test_already_paid_same_hash_is_ok(self):
        tx = "b" * 64
        paid = {
            "order_id": "OP202",
            "direction": "buy",
            "status": "PAID",
            "payout_tx_hash": tx,
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=paid)
        ok, err, order = await transition_awaiting_check_buy_payout_to_paid_in_tx(
            conn,
            "OP202",
            payout_tx_hash=tx,
            payout_confirmed_by="admin:1",
        )
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(order["order_id"], "OP202")
        conn.execute.assert_not_called()

    async def test_already_paid_different_hash_rejected(self):
        paid = {
            "order_id": "OP203",
            "direction": "buy",
            "status": "PAID",
            "payout_tx_hash": "c" * 64,
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=paid)
        ok, err, _order = await transition_awaiting_check_buy_payout_to_paid_in_tx(
            conn,
            "OP203",
            payout_tx_hash="d" * 64,
            payout_confirmed_by="admin:1",
        )
        self.assertFalse(ok)
        self.assertEqual(err, "already_paid")


class ConfirmBuyPayoutRekiTests(unittest.IsolatedAsyncioTestCase):
    async def test_reki_snapshot_skips_payfast(self):
        order = {
            "order_id": "O1",
            "status": "COMPLETED",
            "direction": "buy",
            "payout_tx_hash": "",
            "payment_snapshot": {
                "reki_payfast_id": "d84a6631-28dc-4afd-aa52-533a5b5bdaa3",
            },
            "crypto": "usdt",
        }
        verify = AsyncMock(side_effect=AssertionError("payfast"))
        conn = MagicMock()
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=acquire)
        with patch("services.db.get_order", new=AsyncMock(return_value=order)), patch(
            "services.payfast_payin_guard.verify_payfast_ready_for_payout", new=verify
        ), patch("services.db.get_pool", new=AsyncMock(return_value=pool)), patch(
            "services.db.transition_buy_payout_to_paid_in_tx",
            new=AsyncMock(return_value=(True, None, dict(order))),
        ), patch("services.buy_payout.schedule_paid_notifications"), patch(
            "services.partner_tracking.schedule_partner_exchange"
        ):
            ok, err, _out = await confirm_buy_payout(
                "O1", tx_hash="ab" * 32, actor="op"
            )
        self.assertTrue(ok)
        self.assertIsNone(err)
        verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
