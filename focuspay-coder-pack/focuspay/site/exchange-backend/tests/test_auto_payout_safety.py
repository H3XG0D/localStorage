"""Денежные инварианты автовыплат: резерв, снятие резерва, трактовка ответа signer."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from auto_withdraw_holds import hold_unified_withdrawal, release_withdrawal_holds


class FakeConn:
    """Пишет SQL в журнал, чтобы проверить, что именно ушло в базу."""

    def __init__(self, cashback: float = 0.0, referral: float = 0.0) -> None:
        self.sql: list[str] = []
        self._cashback = cashback
        self._referral = referral

    async def execute(self, sql, *args):
        self.sql.append(" ".join(sql.split()))
        return "UPDATE 1"

    async def fetchval(self, sql, *args):
        text = " ".join(sql.split())
        self.sql.append(text)
        if "user_referral_ledger" in text:
            return self._referral
        return None


class HoldAccountingTests(unittest.IsolatedAsyncioTestCase):
    async def test_partner_part_not_counted_without_campaign(self):
        """Без партнёрской кампании строка не вставляется — её нельзя считать резервом."""
        conn = FakeConn(cashback=100.0, referral=0.0)
        with patch(
            "user_cashback_db.get_cashback_balance_conn",
            new=AsyncMock(return_value=100.0),
        ), patch(
            "user_unified_balance.get_partner_campaign_conn",
            new=AsyncMock(return_value=None),
        ):
            held = await hold_unified_withdrawal(conn, 555, 42, 500.0)

        self.assertEqual(held, 100.0)
        self.assertFalse(any("partner_ledger" in s for s in conn.sql))

    async def test_full_hold_when_cashback_covers(self):
        conn = FakeConn(cashback=500.0)
        with patch(
            "user_cashback_db.get_cashback_balance_conn",
            new=AsyncMock(return_value=500.0),
        ), patch(
            "user_unified_balance.get_partner_campaign_conn",
            new=AsyncMock(return_value=None),
        ):
            held = await hold_unified_withdrawal(conn, 555, 42, 500.0)

        self.assertEqual(held, 500.0)
        self.assertTrue(any("user_cashback_ledger" in s for s in conn.sql))

    async def test_partner_hold_omits_partner_withdrawals_fk(self):
        """unified id нельзя писать в partner_ledger.withdrawal_id (FK другой таблицы)."""
        conn = FakeConn(cashback=0.0, referral=0.0)
        with patch(
            "user_cashback_db.get_cashback_balance_conn",
            new=AsyncMock(return_value=0.0),
        ), patch(
            "user_unified_balance.get_partner_campaign_conn",
            new=AsyncMock(return_value={"campaign_id": 3}),
        ):
            held = await hold_unified_withdrawal(conn, 555, 75, 7500.0)

        self.assertEqual(held, 7500.0)
        partner_sql = [s for s in conn.sql if "INSERT INTO partner_ledger" in s]
        self.assertEqual(len(partner_sql), 1)
        self.assertNotIn("withdrawal_id", partner_sql[0])

    async def test_release_neutralizes_rows_instead_of_deleting(self):
        conn = FakeConn()
        await release_withdrawal_holds(conn, 42)

        self.assertFalse(any("DELETE" in s.upper() for s in conn.sql))
        for table in ("user_cashback_ledger", "user_referral_ledger", "partner_ledger"):
            self.assertTrue(
                any(f"UPDATE {table}" in s for s in conn.sql),
                f"нет нейтрализации для {table}",
            )


class SignerResponseMappingTests(unittest.IsolatedAsyncioTestCase):
    """5xx/таймаут нельзя трактовать как отказ: монеты могли уже уйти."""

    async def _submit(self, code: int, data: dict):
        from signer_client import submit_signer_payout

        with patch(
            "signer_client.signer_request", new=AsyncMock(return_value=(code, data))
        ):
            return await submit_signer_payout({"request_id": "wd:1"})

    async def test_timeout_is_unknown_not_rejected(self):
        st, _ = await self._submit(503, {"error": "signer_unreachable"})
        self.assertEqual(st, "unknown")

    async def test_server_error_is_unknown(self):
        st, _ = await self._submit(500, {})
        self.assertEqual(st, "unknown")

    async def test_explicit_reject_is_rejected(self):
        st, _ = await self._submit(200, {"status": "rejected", "reason": "over_daily_cap"})
        self.assertEqual(st, "rejected")

    async def test_accepted_passes_txid(self):
        st, resp = await self._submit(200, {"status": "accepted", "txid": "deadbeef"})
        self.assertEqual(st, "accepted")
        self.assertEqual(resp["txid"], "deadbeef")

    async def test_duplicate_is_not_resent(self):
        st, _ = await self._submit(200, {"status": "duplicate", "txid": "abc"})
        self.assertEqual(st, "duplicate")


class RequeueTests(unittest.IsolatedAsyncioTestCase):
    async def test_give_up_releases_holds_and_returns_to_pending(self):
        import auto_payout_worker as w

        conn = MagicMock()
        conn.execute = AsyncMock(return_value="UPDATE 1")
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        release = AsyncMock()
        with patch("db.get_pool", new=AsyncMock(return_value=pool)), patch(
            "auto_payout_worker.get_pool", new=AsyncMock(return_value=pool)
        ), patch(
            "auto_withdraw_holds.release_withdrawal_holds", new=release
        ), patch(
            "auto_payout_worker.audit_payout_event", new=AsyncMock()
        ), patch(
            "auto_payout_worker._notify_ops", new=AsyncMock()
        ) as notify:
            await w._requeue_withdrawal(42, "signer_rejected:bad", give_up=True)

        release.assert_awaited_once()
        notify.assert_awaited_once()
        args = [a for c in conn.execute.await_args_list for a in c.args]
        self.assertIn("pending", args)

    async def test_retry_keeps_reserve(self):
        import auto_payout_worker as w

        conn = MagicMock()
        conn.execute = AsyncMock(return_value="UPDATE 1")
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        release = AsyncMock()
        with patch(
            "auto_payout_worker.get_pool", new=AsyncMock(return_value=pool)
        ), patch(
            "auto_withdraw_holds.release_withdrawal_holds", new=release
        ), patch(
            "auto_payout_worker.audit_payout_event", new=AsyncMock()
        ), patch(
            "auto_payout_worker._notify_ops", new=AsyncMock()
        ):
            await w._requeue_withdrawal(42, "rate_unavailable", give_up=False)

        release.assert_not_awaited()
        args = [a for c in conn.execute.await_args_list for a in c.args]
        self.assertIn("reserved", args)


class SettleNotifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_settle_notifies_user_and_ops(self):
        import auto_payout_worker as w

        paid_row = {
            "id": 75,
            "referrer_user_id": 1,
            "amount_rub": 7500,
            "method": "crypto",
            "crypto": "ltc",
            "admin_message_id": 599849,
        }
        conn = MagicMock()
        conn.execute = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx
        notify = AsyncMock()
        with patch(
            "auto_payout_worker.get_pool", new=AsyncMock(return_value=pool)
        ), patch(
            "auto_payout_worker.audit_payout_event", new=AsyncMock()
        ), patch(
            "auto_payout_worker._mark_request", new=AsyncMock()
        ), patch(
            "user_referral_withdraw.process_withdrawal_paid",
            new=AsyncMock(return_value=(paid_row, None)),
        ), patch(
            "user_referral_withdraw.notify_withdrawal_completed", new=notify
        ):
            await w._settle_withdrawal(75, "wd:75", "abc123")

        notify.assert_awaited_once_with(paid_row, tx_hash="abc123")


class ManualConfirmGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_confirm_refuses_autopilot_rows(self):
        from user_referral_withdraw import confirm_withdrawal_crypto_payout

        for status in ("reserved", "sending"):
            conn = MagicMock()
            conn.fetchrow = AsyncMock(
                return_value={"id": 1, "status": status, "method": "crypto"}
            )
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=conn)
            ctx.__aexit__ = AsyncMock(return_value=False)
            pool = MagicMock()
            pool.acquire.return_value = ctx
            paid = AsyncMock()
            with patch(
                "user_referral_withdraw.get_pool", new=AsyncMock(return_value=pool)
            ), patch(
                "user_referral_withdraw._bot_payout_utils",
                return_value=(lambda s: s, None),
            ), patch("user_referral_withdraw.process_withdrawal_paid", new=paid):
                ok, err, _ = await confirm_withdrawal_crypto_payout(1, "a" * 64)

            self.assertFalse(ok)
            self.assertEqual(err, "auto_in_progress")
            paid.assert_not_awaited()


class NewAddressRiskTests(unittest.IsolatedAsyncioTestCase):
    async def _evaluate(
        self,
        paid_buys: int,
        *,
        paid_withdraws: int = 0,
        paid_accruals: int = 0,
        review_status: str | None = None,
        address: str = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
    ):
        from auto_payout_risk import evaluate_withdraw_risk

        conn = MagicMock()

        async def _fetchval(sql, *args):
            if "account_review_status" in str(sql):
                return review_status
            return None

        conn.fetchval = AsyncMock(side_effect=_fetchval)
        conn.fetchrow = AsyncMock(return_value=None)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx
        with patch("auto_payout_risk.get_pool", new=AsyncMock(return_value=pool)), patch(
            "auto_payout_risk.auto_withdraw_enabled", return_value=True
        ), patch("auto_payout_risk.auto_payout_enabled", return_value=True), patch(
            "auto_payout_risk.auto_withdraw_max_rub", return_value=10_000.0
        ), patch("auto_settings.auto_no_shift_min_buy_paid", return_value=5), patch(
            "auto_payout_risk.buy_paid_count", new=AsyncMock(return_value=paid_buys)
        ), patch(
            "auto_payout_risk._paid_withdraw_count",
            new=AsyncMock(return_value=paid_withdraws),
        ), patch(
            "auto_payout_risk._paid_referral_or_partner_count",
            new=AsyncMock(return_value=paid_accruals),
        ), patch(
            "bot_status_bridge.is_user_banned", new=AsyncMock(return_value=(False, None, None))
        ), patch(
            "auto_payout_risk._first_payout_to_address", new=AsyncMock(return_value=True)
        ), patch(
            "casino_payout_rail.assert_crypto_withdraw_allowed", new=AsyncMock()
        ), patch(
            "casino_wagering.locked_by_wagering", new=AsyncMock(return_value=0)
        ), patch(
            "auto_payout_guard.signer_circuit_closed", new=AsyncMock(return_value=True)
        ), patch(
            "auto_payout_worker.daily_cap_room", new=AsyncMock(return_value=50_000.0)
        ):
            return await evaluate_withdraw_risk(
                user_id=1,
                amount_rub=3000,
                method="crypto",
                requisites=address,
                crypto="btc",
                network=None,
                source="balance",
            )

    async def test_regular_new_address_is_auto(self):
        outcome, reason = await self._evaluate(paid_buys=7)
        self.assertEqual((outcome, reason), ("auto", "ok"))

    async def test_newcomer_new_address_is_manual(self):
        outcome, reason = await self._evaluate(paid_buys=1)
        self.assertEqual((outcome, reason), ("manual", "new_address_not_regular"))

    async def test_partner_history_new_address_is_auto(self):
        outcome, reason = await self._evaluate(paid_buys=1, paid_withdraws=7)
        self.assertEqual((outcome, reason), ("auto", "ok"))

    async def test_partner_only_history_without_buys_is_auto(self):
        outcome, reason = await self._evaluate(paid_buys=0, paid_withdraws=5)
        self.assertEqual((outcome, reason), ("auto", "ok"))

    async def test_partner_accruals_without_prior_withdraws_is_auto(self):
        outcome, reason = await self._evaluate(paid_buys=0, paid_withdraws=0, paid_accruals=10)
        self.assertEqual((outcome, reason), ("auto", "ok"))

    async def test_pending_review_with_paid_withdraws_does_not_block_auto(self):
        outcome, reason = await self._evaluate(
            paid_buys=0, paid_withdraws=12, review_status="pending"
        )
        self.assertEqual((outcome, reason), ("auto", "ok"))

    async def test_pending_review_without_paid_history_blocks_auto(self):
        outcome, reason = await self._evaluate(
            paid_buys=0, paid_withdraws=0, paid_accruals=10, review_status="pending"
        )
        self.assertEqual((outcome, reason), ("manual", "account_review"))

    async def test_trailing_backslash_in_address_is_cleaned(self):
        outcome, reason = await self._evaluate(
            paid_buys=7,
            address="bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4\\",
        )
        self.assertEqual((outcome, reason), ("auto", "ok"))


class BuyPayfastWaitTests(unittest.IsolatedAsyncioTestCase):
    def _row(self, age_sec: float) -> dict:
        from datetime import datetime, timedelta, timezone

        return {
            "order_id": "777",
            "user_id": 1,
            "crypto": "btc",
            "crypto_amount": 0.001,
            "fiat_amount": 5000,
            "requisites": "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
            "updated_at": datetime.now(timezone.utc) - timedelta(seconds=age_sec),
        }

    async def _run(self, reason: str, age_sec: float = 60):
        import auto_payout_worker as w

        w._payfast_next_check.clear()
        fail = AsyncMock()
        submit = AsyncMock()
        with patch.object(w, "_buy_preflight", new=AsyncMock(return_value=(False, reason))), patch.object(
            w, "_fail_buy_to_operator", new=fail
        ), patch.object(w, "submit_signer_payout", new=submit), patch.object(
            w, "auto_payout_max_rub", return_value=10_000
        ):
            sent = await w._process_buy_order_row(self._row(age_sec), 50_000)
        return sent, fail, submit

    async def test_pending_payfast_waits(self):
        for reason in ("payfast_not_paid", "payfast_awaiting_trader", "payfast_check_pending"):
            sent, fail, submit = await self._run(reason)
            self.assertFalse(sent)
            fail.assert_not_awaited()
            submit.assert_not_awaited()

    async def test_wait_backoff_skips_next_tick(self):
        import auto_payout_worker as w

        await self._run("payfast_awaiting_trader")
        self.assertTrue(w._payfast_backoff_active("777"))

    async def test_wait_timeout_goes_to_operator(self):
        sent, fail, submit = await self._run("payfast_awaiting_trader", age_sec=3 * 3600)
        self.assertFalse(sent)
        fail.assert_awaited_once()
        self.assertTrue(fail.await_args.args[1].startswith("payfast_wait_timeout"))
        submit.assert_not_awaited()

    async def test_payfast_failure_goes_to_operator_at_once(self):
        sent, fail, submit = await self._run("payfast_status_canceled")
        fail.assert_awaited_once()
        submit.assert_not_awaited()

    async def test_shift_order_autosends_when_client_would_qualify(self):
        from auto_payout_worker import should_autosend_buy

        self.assertTrue(should_autosend_buy({"auto_served": False}, "auto"))
        self.assertFalse(should_autosend_buy({"auto_served": False}, "manual"))
        self.assertTrue(should_autosend_buy({"auto_served": True}, "manual"))

    async def test_dry_run_hands_buy_to_operator_without_sending(self):
        import auto_payout_worker as w

        w._payfast_next_check.clear()
        fail = AsyncMock()
        submit = AsyncMock()
        with patch.object(w, "_buy_preflight", new=AsyncMock(return_value=(True, "ok"))), patch.object(
            w, "_signer_is_dry_run", new=AsyncMock(return_value=True)
        ), patch.object(w, "_fail_buy_to_operator", new=fail), patch.object(
            w, "submit_signer_payout", new=submit
        ), patch.object(w, "auto_payout_max_rub", return_value=10_000):
            sent = await w._process_buy_order_row(self._row(60), 50_000)
        self.assertFalse(sent)
        submit.assert_not_awaited()
        fail.assert_awaited_once()
        self.assertEqual(fail.await_args.args[1], "dry_run")

    async def _signer_reject(self, reason: str, *, wait_min: int, rows=None):
        import auto_payout_worker as w
        import hot_wallet_topups as t

        w._payfast_next_check.clear()
        t._waiting.clear()
        conn = MagicMock()
        conn.execute = AsyncMock()
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction.return_value = tx
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx
        notify = AsyncMock()
        confirm = AsyncMock()
        submit = AsyncMock(return_value=("rejected", {"reason": reason}))
        with patch.object(w, "_buy_preflight", new=AsyncMock(return_value=(True, "ok"))), patch.object(
            w, "_signer_is_dry_run", new=AsyncMock(return_value=False)
        ), patch.object(w, "submit_signer_payout", new=submit), patch.object(
            w, "get_pool", new=AsyncMock(return_value=pool)
        ), patch.object(
            w, "audit_payout_event", new=AsyncMock()
        ), patch.object(w, "_coin_funds", new=AsyncMock(return_value=None)), patch.object(
            w, "_mark_auto_served", new=AsyncMock()
        ), patch.object(w, "_enqueue_payout_request", new=AsyncMock()), patch.object(
            w, "_mark_request", new=AsyncMock()
        ) as mark, patch.object(
            w, "_notify_ops", new=notify
        ), patch.object(w, "auto_payout_max_rub", return_value=10_000), patch(
            "hot_wallet_topups.payout_rows", new=AsyncMock(return_value=rows or [])
        ), patch(
            "hot_wallet_topups.auto_payout_wait_funds_max_min", return_value=wait_min
        ), patch(
            "payout_wallet_confirm.resolve_payout_address",
            new=AsyncMock(return_value="bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"),
        ), patch(
            "bot_status_bridge.confirm_buy_payout", new=confirm
        ):
            sent = await w._process_buy_order_row(self._row(60), 50_000)
        return sent, mark, notify, confirm, submit

    async def test_signer_reject_does_not_confirm_payout(self):
        sent, mark, notify, confirm, _ = await self._signer_reject("insufficient_funds", wait_min=0)
        self.assertTrue(sent)
        mark.assert_awaited()
        self.assertIn("failed", mark.await_args.args)
        notify.assert_awaited_once()
        self.assertIn("insufficient_funds", notify.await_args.args[0])
        confirm.assert_not_awaited()

    async def test_signer_short_of_funds_waits_for_topup(self):
        import auto_payout_worker as w

        sent, mark, notify, confirm, _ = await self._signer_reject("insufficient_funds", wait_min=120)
        self.assertIn("requeued", mark.await_args.args)
        notify.assert_not_awaited()
        confirm.assert_not_awaited()
        self.assertTrue(w._payfast_backoff_active("777"))

    async def test_other_signer_reject_goes_to_operator(self):
        sent, mark, notify, _, _ = await self._signer_reject("amount_over_cap", wait_min=120)
        self.assertIn("failed", mark.await_args.args)
        notify.assert_awaited_once()

    async def test_retry_after_reject_uses_new_request_id(self):
        rows = [{"request_id": "order:777", "kind": "buy_order", "status": "requeued", "txid": None}]
        *_, submit = await self._signer_reject("insufficient_funds", wait_min=120, rows=rows)
        self.assertEqual(submit.await_args.args[0]["request_id"], "order:777-r1")

    async def test_operator_manual_send_blocks_autopilot(self):
        rows = [{"request_id": "order:777", "kind": "manual_buy", "status": "queued", "txid": None}]
        sent, *_, submit = await self._signer_reject("insufficient_funds", wait_min=120, rows=rows)
        self.assertFalse(sent)
        submit.assert_not_awaited()


class FundsWaitTests(unittest.IsolatedAsyncioTestCase):
    """Нехватка подтверждённых монет: ждём пополнение, а не отдаём оператору сразу."""

    def _row(self):
        return {"order_id": "888", "user_id": 1, "crypto": "btc", "crypto_amount": 0.01,
                "fiat_amount": 5000, "requisites": "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"}

    async def _run(self, funds, wait_min=120):
        import auto_payout_worker as w
        import hot_wallet_topups as t

        w._payfast_next_check.clear()
        fail = AsyncMock()
        submit = AsyncMock()
        with patch.object(w, "_buy_preflight", new=AsyncMock(return_value=(True, "ok"))), patch.object(
            w, "_signer_is_dry_run", new=AsyncMock(return_value=False)
        ), patch.object(w, "_coin_funds", new=AsyncMock(return_value=funds)), patch.object(
            w, "_fail_buy_to_operator", new=fail
        ), patch.object(w, "submit_signer_payout", new=submit), patch.object(
            w, "auto_payout_max_rub", return_value=10_000
        ), patch("hot_wallet_topups.auto_payout_wait_funds_max_min", return_value=wait_min):
            sent = await w._process_buy_order_row(self._row(), 50_000)
        return sent, fail, submit, t

    async def asyncSetUp(self):
        import hot_wallet_topups as t

        t._waiting.clear()
        t._announced.clear()

    async def test_pending_topup_covers_payout_so_it_waits(self):
        sent, fail, submit, t = await self._run((0.004, 0.02))
        self.assertFalse(sent)
        fail.assert_not_awaited()
        submit.assert_not_awaited()
        self.assertEqual([w["order_id"] for w in t.waiting_snapshot()], ["888"])

    async def test_no_topup_in_flight_goes_to_operator(self):
        sent, fail, submit, t = await self._run((0.004, 0.001))
        fail.assert_awaited_once()
        self.assertEqual(fail.await_args.args[1], "insufficient_funds")
        self.assertEqual(t.waiting_snapshot(), [])

    async def test_wait_timeout_goes_to_operator(self):
        import time

        import hot_wallet_topups as t

        t._waiting["888"] = (time.monotonic() - 3 * 3600, "btc", 0.01)
        sent, fail, submit, _ = await self._run((0.004, 0.02))
        fail.assert_awaited_once()
        self.assertEqual(fail.await_args.args[1], "funds_wait_timeout")

    async def test_owner_is_told_once(self):
        await self._run((0.004, 0.02))
        import hot_wallet_topups as t

        self.assertIn("1 автовыплат", t.wait_notice(t.take_new_waiting()) or "")
        self.assertIsNone(t.wait_notice(t.take_new_waiting()))


def _pool_with(order: dict):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=order)
    pool = MagicMock()
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = acquire
    return pool


class BuyPreflightPayinTests(unittest.IsolatedAsyncioTestCase):
    async def test_requisite_order_skips_payfast_uuid(self):
        import os
        import sys
        from pathlib import Path

        from auto_payout_worker import _buy_preflight

        bot_root = Path(__file__).resolve().parents[3] / "bot" / "tg_bot_btc"
        os.environ["TG_BOT_PATH"] = str(bot_root)
        if str(bot_root) not in sys.path:
            sys.path.append(str(bot_root))
        order = {
            "order_id": "20182006",
            "status": "COMPLETED",
            "direction": "buy",
            "payout_tx_hash": None,
            "payin_requisite_id": 6,
            "crypto_amount": 0.00033,
            "fiat_amount": 2885,
        }
        verify = AsyncMock(side_effect=AssertionError("payfast"))
        with patch(
            "auto_payout_worker.get_pool", new=AsyncMock(return_value=_pool_with(order))
        ), patch(
            "payfast_payin_guard.verify_payfast_ready_for_payout", new=verify
        ), patch(
            "services.buy_payout_validate.validate_buy_payout_crypto",
            return_value=(True, None),
        ):
            ok, reason = await _buy_preflight("20182006")
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        verify.assert_not_called()

    async def test_reki_order_skips_payfast_uuid(self):
        import os
        import sys
        from pathlib import Path

        from auto_payout_worker import _buy_preflight

        bot_root = Path(__file__).resolve().parents[3] / "bot" / "tg_bot_btc"
        os.environ["TG_BOT_PATH"] = str(bot_root)
        if str(bot_root) not in sys.path:
            sys.path.append(str(bot_root))
        order = {
            "order_id": "20182007",
            "status": "COMPLETED",
            "direction": "buy",
            "payout_tx_hash": None,
            "payin_requisite_id": None,
            "payment_snapshot": {
                "reki_payfast_id": "d84a6631-28dc-4afd-aa52-533a5b5bdaa3",
            },
            "crypto_amount": 0.00033,
            "fiat_amount": 2885,
        }
        verify = AsyncMock(side_effect=AssertionError("payfast"))
        with patch(
            "auto_payout_worker.get_pool", new=AsyncMock(return_value=_pool_with(order))
        ), patch(
            "payfast_payin_guard.verify_payfast_ready_for_payout", new=verify
        ), patch(
            "services.buy_payout_validate.validate_buy_payout_crypto",
            return_value=(True, None),
        ):
            ok, reason = await _buy_preflight("20182007")
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        verify.assert_not_called()

    async def test_payfast_order_still_needs_uuid(self):
        from auto_payout_worker import _buy_preflight

        order = {
            "order_id": "1",
            "status": "COMPLETED",
            "direction": "buy",
            "payout_tx_hash": "",
            "payin_requisite_id": None,
        }
        with patch(
            "auto_payout_worker.get_pool", new=AsyncMock(return_value=_pool_with(order))
        ), patch(
            "payfast_payin_guard.verify_payfast_ready_for_payout",
            new=AsyncMock(return_value=(False, "payfast_uuid_missing", None)),
        ) as verify:
            ok, reason = await _buy_preflight("1")
        self.assertFalse(ok)
        self.assertEqual(reason, "payfast_uuid_missing")
        verify.assert_awaited()


if __name__ == "__main__":
    unittest.main()
