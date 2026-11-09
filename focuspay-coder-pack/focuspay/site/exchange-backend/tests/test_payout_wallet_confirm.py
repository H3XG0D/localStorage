"""Подтверждение кошелька перед автовыплатой: без ответа монеты не уходят."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

if "asyncpg" not in sys.modules:
    _asyncpg = MagicMock()
    _asyncpg.UndefinedTableError = type("UndefinedTableError", (Exception,), {})
    sys.modules["asyncpg"] = _asyncpg

from fastapi import HTTPException

from payout_wallet_confirm import (
    WALLET_ASK_DELAY_SEC,
    apply_client_decision,
    compute_wallet_grace_state,
    evaluate_wallet_decision,
    resolve_payout_address,
    send_wallet_confirm_early,
    wallet_confirm_view,
)

OLD = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
NEW = "3J98t1WpEZ73CNmYviecrnyiWrnqRhWNLy"


def _order(**extra):
    base = {
        "order_id": "777",
        "user_id": 5,
        "direction": "buy",
        "status": "COMPLETED",
        "crypto": "btc",
        "payout_tx_hash": None,
        "requisites": OLD,
        "wallet_address": OLD,
        "fiat_amount": 5000,
        "crypto_amount": 0.001,
    }
    base.update(extra)
    return base


def _confirm(**extra):
    base = {"order_id": "777", "user_id": 5, "status": "pending", "address": OLD, "coin": "btc"}
    base.update(extra)
    return base


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_exc):
        return False


class _Conn:
    def __init__(self, order=None, confirm=None):
        self.order = order
        self.confirm = confirm
        self.statements: list[tuple[str, tuple]] = []

    def transaction(self):
        return _Acquire(self)

    async def fetchrow(self, sql, *args):
        text = " ".join(sql.split())
        self.statements.append((text, args))
        if "INSERT INTO payout_wallet_confirms" in text:
            if self.confirm:
                return None
            self.confirm = {
                "order_id": args[0],
                "user_id": args[1],
                "coin": args[2],
                "address": args[3],
                "status": "pending",
            }
            return {"order_id": args[0]}
        if "FROM orders" in text:
            return self.order
        if "FROM payout_wallet_confirms" in text:
            return self.confirm
        return None

    async def execute(self, sql, *args):
        self.statements.append((" ".join(sql.split()), args))
        return "UPDATE 1"


def _pool(conn):
    pool = MagicMock()
    pool.acquire.return_value = _Acquire(conn)
    return pool


def _worker_pool():
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
    return pool


class DecisionTests(unittest.TestCase):
    def test_bad_btc_is_rejected(self):
        decision = evaluate_wallet_decision(
            _order(),
            _confirm(status="awaiting_address"),
            user_id=5,
            action="replace",
            address="not-a-wallet",
        )
        self.assertEqual(decision["http"], 400)
        self.assertIn("Bitcoin", decision["detail"])

    def test_valid_replace_is_confirmed(self):
        decision = evaluate_wallet_decision(
            _order(),
            _confirm(status="awaiting_address"),
            user_id=5,
            action="replace",
            address=f"  {NEW}  хвост",
        )
        self.assertEqual(decision["http"], 200)
        self.assertEqual(decision["status"], "confirmed")
        self.assertEqual(decision["address"], NEW)
        self.assertTrue(decision["write_order"])

    def test_confirm_is_idempotent(self):
        decision = evaluate_wallet_decision(
            _order(),
            _confirm(status="confirmed"),
            user_id=5,
            action="confirm",
            address=None,
        )
        self.assertEqual(decision["status"], "confirmed")
        self.assertFalse(decision["write_order"])

    def test_paid_order_is_already_sent(self):
        decision = evaluate_wallet_decision(
            _order(payout_tx_hash="abc"),
            _confirm(),
            user_id=5,
            action="confirm",
            address=None,
        )
        self.assertEqual(decision["status"], "already_sent")


class ApplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_replace_writes_requisites_and_wallet(self):
        conn = _Conn(_order(), _confirm(status="awaiting_address"))
        with patch("payout_wallet_confirm.get_pool", new=AsyncMock(return_value=_pool(conn))):
            result = await apply_client_decision(
                order_id="777",
                user_id=5,
                action="replace",
                address=NEW,
            )
        self.assertEqual(result["address"], NEW)
        writes = [item for item in conn.statements if "UPDATE orders" in item[0]]
        self.assertEqual(len(writes), 1)
        sql, args = writes[0]
        self.assertIn("requisites", sql)
        self.assertIn("wallet_address", sql)
        self.assertEqual(args[1], NEW)
        self.assertEqual(args[2], NEW)

    async def test_bad_address_does_not_write(self):
        conn = _Conn(_order(), _confirm(status="awaiting_address"))
        with patch("payout_wallet_confirm.get_pool", new=AsyncMock(return_value=_pool(conn))):
            with self.assertRaises(HTTPException) as caught:
                await apply_client_decision(
                    order_id="777",
                    user_id=5,
                    action="replace",
                    address="bc1-nope",
                )
        self.assertEqual(caught.exception.status_code, 400)
        self.assertFalse(any("UPDATE orders" in item[0] for item in conn.statements))


class ResolveTests(unittest.IsolatedAsyncioTestCase):
    async def test_question_is_sent_once_then_wait(self):
        conn = _Conn()
        row = _order()
        ask = AsyncMock(return_value=(True, 42))
        ops = AsyncMock()
        with patch("payout_wallet_confirm.get_pool", new=AsyncMock(return_value=_pool(conn))), patch(
            "payout_wallet_confirm.deliver_ask", new=ask
        ), patch("payout_wallet_confirm._notify_ops_waiting", new=ops):
            first = await resolve_payout_address(
                row, coin="btc", address=OLD, fiat=5000, amount_crypto=0.001
            )
            second = await resolve_payout_address(
                row, coin="btc", address=OLD, fiat=5000, amount_crypto=0.001
            )
        self.assertIsNone(first)
        self.assertIsNone(second)
        ask.assert_awaited_once()
        ops.assert_awaited_once()
        self.assertFalse(ops.await_args.kwargs["delivered"] is False)

    async def test_confirmed_address_is_returned(self):
        conn = _Conn(confirm=_confirm(status="confirmed", address=NEW))
        ask = AsyncMock()
        with patch("payout_wallet_confirm.get_pool", new=AsyncMock(return_value=_pool(conn))), patch(
            "payout_wallet_confirm.deliver_ask", new=ask
        ):
            approved = await resolve_payout_address(
                _order(), coin="btc", address=OLD, fiat=5000, amount_crypto=0.001
            )
        self.assertEqual(approved, NEW)
        ask.assert_not_awaited()

    async def test_five_minute_grace_delays_question_until_elapsed_or_forced(self):
        now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        conn = _Conn()
        row = _order(updated_at=now - timedelta(seconds=120))
        ask = AsyncMock(return_value=(True, 42))
        ops = AsyncMock()
        with patch("payout_wallet_confirm.get_pool", new=AsyncMock(return_value=_pool(conn))), patch(
            "payout_wallet_confirm.deliver_ask", new=ask
        ), patch("payout_wallet_confirm._notify_ops_waiting", new=ops):
            during_grace = await resolve_payout_address(
                row, coin="btc", address=OLD, fiat=5000, amount_crypto=0.001, now=now
            )
            self.assertIsNone(during_grace)
            ask.assert_not_awaited()

            state = compute_wallet_grace_state(row, conn.confirm, now=now)
            self.assertEqual(state["stage"], "waiting_timer")
            self.assertEqual(state["seconds_left"], WALLET_ASK_DELAY_SEC - 120)
            self.assertTrue(state["can_send_early"])

            after_grace = await resolve_payout_address(
                row,
                coin="btc",
                address=OLD,
                fiat=5000,
                amount_crypto=0.001,
                now=now + timedelta(seconds=WALLET_ASK_DELAY_SEC),
            )
            self.assertIsNone(after_grace)
            ask.assert_awaited_once()

    async def test_send_wallet_confirm_early_bypasses_timer(self):
        now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        row = _order(updated_at=now)
        conn = _Conn(order=row)
        ask = AsyncMock(return_value=(True, 77))
        ops = AsyncMock()
        with patch("payout_wallet_confirm.get_pool", new=AsyncMock(return_value=_pool(conn))), patch(
            "payout_wallet_confirm.deliver_ask", new=ask
        ), patch("payout_wallet_confirm._notify_ops_waiting", new=ops):
            res = await send_wallet_confirm_early("777")
        self.assertTrue(res["ok"])
        self.assertFalse(res["already_sent"])
        ask.assert_awaited_once()
        ops.assert_awaited_once()


class WorkerGateTests(unittest.IsolatedAsyncioTestCase):
    def _row(self):
        return {
            "order_id": "777",
            "user_id": 5,
            "crypto": "btc",
            "crypto_amount": 0.001,
            "fiat_amount": 5000,
            "requisites": OLD,
            "updated_at": None,
        }

    async def test_without_confirm_signer_is_not_called(self):
        import auto_payout_worker as w

        submit = AsyncMock()
        with patch.object(w, "_buy_preflight", new=AsyncMock(return_value=(True, "ok"))), patch.object(
            w, "_signer_is_dry_run", new=AsyncMock(return_value=False)
        ), patch.object(w, "_coin_funds", new=AsyncMock(return_value=None)), patch.object(
            w, "auto_payout_max_rub", return_value=10_000
        ), patch(
            "payout_wallet_confirm.resolve_payout_address", new=AsyncMock(return_value=None)
        ), patch.object(w, "get_pool", new=AsyncMock(return_value=_worker_pool())), patch(
            "hot_wallet_topups.payout_rows", new=AsyncMock(return_value=[])
        ), patch.object(w, "submit_signer_payout", new=submit):
            sent = await w._process_buy_order_row(self._row(), 50_000)
        self.assertFalse(sent)
        submit.assert_not_awaited()

    async def test_confirmed_address_is_what_gets_sent(self):
        import auto_payout_worker as w

        submit = AsyncMock(return_value=("rejected", {"reason": "stop"}))
        with patch.object(w, "_buy_preflight", new=AsyncMock(return_value=(True, "ok"))), patch.object(
            w, "_signer_is_dry_run", new=AsyncMock(return_value=False)
        ), patch.object(w, "_coin_funds", new=AsyncMock(return_value=None)), patch.object(
            w, "auto_payout_max_rub", return_value=10_000
        ), patch(
            "payout_wallet_confirm.resolve_payout_address", new=AsyncMock(return_value=NEW)
        ), patch(
            "hot_wallet_topups.payout_rows", new=AsyncMock(return_value=[])
        ), patch.object(w, "get_pool", new=AsyncMock(return_value=_worker_pool())), patch.object(
            w, "_mark_auto_served", new=AsyncMock()
        ), patch.object(w, "_enqueue_payout_request", new=AsyncMock()) as enqueue, patch.object(
            w, "submit_signer_payout", new=submit
        ), patch.object(w, "audit_payout_event", new=AsyncMock()), patch.object(
            w, "_mark_request", new=AsyncMock()
        ), patch.object(w, "_notify_ops", new=AsyncMock()):
            sent = await w._process_buy_order_row(self._row(), 50_000)
        self.assertTrue(sent)
        self.assertEqual(submit.await_args.args[0]["address"], NEW)
        self.assertEqual(enqueue.await_args.kwargs["address"], NEW)


class WalletConfirmViewTests(unittest.TestCase):
    def test_open_status_is_visible(self):
        view = wallet_confirm_view({"status": "pending", "address": OLD, "coin": "btc"})
        self.assertEqual(view, {"status": "pending", "address": OLD, "coin": "BTC"})

    def test_confirmed_status_is_hidden(self):
        self.assertIsNone(wallet_confirm_view({"status": "confirmed", "address": OLD, "coin": "btc"}))
        self.assertIsNone(wallet_confirm_view(None))


if __name__ == "__main__":
    unittest.main()
