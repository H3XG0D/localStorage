"""Ожидание пополнения, доверенные пополнения и возврат заявки в автопилот."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import hot_wallet_topups as t


def _row(kind="buy_order", status="failed", reason="insufficient_funds", txid=None, rid="order:1"):
    return {"request_id": rid, "kind": kind, "status": status, "reject_reason": reason, "txid": txid}


ORDER = {"order_id": "1", "status": "COMPLETED", "payout_tx_hash": None}


class RequestIdTests(unittest.TestCase):
    def test_first_attempt_uses_plain_order_id(self):
        self.assertEqual(t.buy_request_id("1", []), "order:1")

    def test_crash_before_send_reuses_queued_row(self):
        rows = [_row(status="queued", reason=None)]
        self.assertEqual(t.buy_request_id("1", rows), "order:1")

    def test_after_requeue_gets_suffix(self):
        rows = [_row(status="requeued")]
        self.assertEqual(t.buy_request_id("1", rows), "order:1-r1")
        rows.append(_row(status="requeued", rid="order:1-r1"))
        self.assertEqual(t.buy_request_id("1", rows), "order:1-r2")

    def test_any_live_or_failed_row_stops_autopilot(self):
        for status in ("sent", "confirmed", "failed"):
            self.assertIsNone(t.buy_request_id("1", [_row(status=status)]), status)
        self.assertIsNone(t.buy_request_id("1", [_row(status="requeued", txid="ab" * 32)]))

    def test_manual_send_stops_autopilot(self):
        self.assertIsNone(t.buy_request_id("1", [_row(kind="manual_buy", status="failed")]))


class PendingTests(unittest.TestCase):
    def test_pending_shown_until_trusted(self):
        row = {"spendable": 0.0002, "unconfirmed": 0.0007, "spendable_fast": 0.0009}
        with patch.object(t, "auto_payout_trusted_topups", return_value=False):
            self.assertEqual(t.pending_unconfirmed(row), 0.0007)
        with patch.object(t, "auto_payout_trusted_topups", return_value=True):
            self.assertEqual(t.pending_unconfirmed(row), 0.0)


class RequeueGuardTests(unittest.TestCase):
    def test_funds_failure_can_return(self):
        self.assertIsNone(t.requeue_block_reason(ORDER, [_row()]))
        self.assertIsNone(t.requeue_block_reason(ORDER, [_row(reason="signer_rejected:insufficient_funds")]))

    def test_other_failure_stays_with_operator(self):
        self.assertEqual(t.requeue_block_reason(ORDER, [_row(reason="dry_run")]), "not_funds_failure")

    def test_paid_order_never_returns(self):
        paid = {**ORDER, "payout_tx_hash": "ab" * 32}
        self.assertEqual(t.requeue_block_reason(paid, [_row()]), "already_paid")
        self.assertEqual(t.requeue_block_reason({**ORDER, "status": "PAID"}, [_row()]), "wrong_status")

    def test_operator_wallet_send_blocks_return(self):
        rows = [_row(), _row(kind="manual_buy", status="failed", reason="x", rid="order:1-r1")]
        self.assertEqual(t.requeue_block_reason(ORDER, rows), "manual_send")

    def test_sent_attempt_blocks_return(self):
        rows = [_row(), _row(status="sent", reason=None, rid="order:1-r1")]
        self.assertEqual(t.requeue_block_reason(ORDER, rows), "already_sent")


class SpendableTests(unittest.TestCase):
    def test_fast_balance_only_when_enabled(self):
        row = {"spendable": 0.001, "spendable_fast": 0.02}
        with patch.object(t, "auto_payout_trusted_topups", return_value=False):
            self.assertEqual(t.effective_spendable(row), 0.001)
        with patch.object(t, "auto_payout_trusted_topups", return_value=True):
            self.assertEqual(t.effective_spendable(row), 0.02)

    def test_old_signer_without_fast_field(self):
        with patch.object(t, "auto_payout_trusted_topups", return_value=True):
            self.assertEqual(t.effective_spendable({"spendable": 0.5}), 0.5)


class ResumeTests(unittest.TestCase):
    def test_btc_covered_by_unconfirmed_is_resumed_once(self):
        items = [
            {"order_id": "1", "coin": "btc", "amount_crypto": 0.01},
            {"order_id": "2", "coin": "ltc", "amount_crypto": 0.01},
            {"order_id": "3", "coin": "btc", "amount_crypto": 0.5},
        ]
        got = t.btc_failures_covered(items, 0.02, now=100.0, resumed_at={})
        self.assertEqual(got, ["1"])
        again = t.btc_failures_covered(items, 0.02, now=120.0, resumed_at={"1": 100.0})
        self.assertEqual(again, [])
        later = t.btc_failures_covered(items, 0.02, now=161.0, resumed_at={"1": 100.0})
        self.assertEqual(later, ["1"])


class TopupAlertTests(unittest.TestCase):
    def setUp(self):
        t._alerted_topups.clear()

    def test_conflicted_topup_alerts_once(self):
        items = [{"txid": "aa" * 32, "status": "conflicted"}, {"txid": "bb" * 32, "status": "pending"}]
        self.assertEqual(len(t.topup_alerts(items)), 1)
        self.assertEqual(t.topup_alerts(items), [])

    def test_dropped_topup_alerts(self):
        self.assertEqual(len(t.topup_alerts([{"txid": "cc" * 32, "status": "dropped"}])), 1)


if __name__ == "__main__":
    unittest.main()
