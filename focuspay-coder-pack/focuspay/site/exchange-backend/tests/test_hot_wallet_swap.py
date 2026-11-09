"""Отправка с горячего кошелька: доступ, адрес, swap_send, комиссия только после tx."""
from __future__ import annotations

import inspect
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

import hot_wallet_swap as swap
import project_wallet_payout as pwp
from finance_pnl import compute_pnl
from hot_wallet_swap import SwapConfirmIn, SwapPreviewIn, SwapQuote
from routers.operator import operator_hot_wallet_send, operator_hot_wallet_send_preview


LTC = "ltc1q" + "a" * 30
BTC = "bc1q" + "b" * 30
TRON = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"

QUOTE = SwapQuote(
    coin="ltc",
    address=LTC,
    crypto_amount=Decimal("1.50000000"),
    send_rate=8000.0,
    send_rub=12000.0,
    fee_crypto="usdt",
    fee_amount=Decimal("5.20000000"),
    fee_rate=90.0,
    fee_rub=468.0,
)


def _pool(shift_row):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=shift_row)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = ctx

    async def get_pool():
        return pool

    return get_pool


def _finance(grade: str):
    return {"id": 4, "operator_roles": ["finance"], "operator_role": "finance"}, {"finance": grade}


def _preview_body(**overrides):
    data = {
        "coin": "ltc",
        "address": LTC,
        "crypto_amount": "1.5",
        "fee_crypto": "usdt",
        "fee_amount": "5.2",
    }
    data.update(overrides)
    return SwapPreviewIn(**data)


class AccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_junior_finance_forbidden(self):
        op, grades = _finance("junior")
        with patch("permissions.load_operator_role_grades", new=AsyncMock(return_value=grades)):
            with self.assertRaises(HTTPException) as ctx:
                await operator_hot_wallet_send_preview(_preview_body(), op)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("старший", ctx.exception.detail)

    async def test_client_senior_forbidden(self):
        op = {"id": 5, "operator_roles": ["client"], "operator_role": "client"}
        with patch(
            "permissions.load_operator_role_grades",
            new=AsyncMock(return_value={"client": "senior"}),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await operator_hot_wallet_send_preview(_preview_body(), op)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_senior_off_shift_forbidden(self):
        op, grades = _finance("senior")
        with patch(
            "permissions.load_operator_role_grades",
            new=AsyncMock(return_value=grades),
        ), patch("routers.operator.get_pool", new=_pool(None)):
            body = SwapConfirmIn(
                coin="ltc",
                address=LTC,
                crypto_amount="1.5",
                fee_crypto="usdt",
                fee_amount="5.2",
                preview_token="preview-token",
                totp_code="123456",
            )
            with self.assertRaises(HTTPException) as ctx:
                await operator_hot_wallet_send(body, op)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("смену", str(ctx.exception.detail))


class AddressTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_network_rejected(self):
        with self.assertRaises(pwp.WalletPayoutError) as ctx:
            await swap.assert_destination("ltc", TRON)
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("LTC", ctx.exception.message)

    async def test_btc_address_rejected_for_ltc_preview(self):
        op, grades = _finance("senior")
        with patch(
            "permissions.load_operator_role_grades",
            new=AsyncMock(return_value=grades),
        ), patch("routers.operator.get_pool", new=_pool({"id": 9})):
            with self.assertRaises(HTTPException) as ctx:
                await operator_hot_wallet_send_preview(_preview_body(address=BTC), op)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_project_deposit_rejected(self):
        with patch("hot_wallet_swap.own_addresses", new=AsyncMock(return_value=[LTC])):
            with self.assertRaises(pwp.WalletPayoutError) as ctx:
                await swap.assert_destination("ltc", LTC)
        self.assertEqual(ctx.exception.code, "address_own")


class CapTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_cap_includes_swap_and_manual_buy(self):
        seen = {}

        class Conn:
            async def fetchval(self, sql, *args):
                seen["sql"] = sql
                seen["args"] = args
                return 12

        total = await pwp.operator_sent_today_rub(Conn(), 4)
        self.assertEqual(total, 12.0)
        self.assertIn("ANY", seen["sql"])
        self.assertIn("manual_buy", seen["args"][1])
        self.assertIn(swap.SWAP_SEND_KIND, seen["args"][1])
        self.assertIn(swap.SWAP_SEND_KIND, pwp.CAP_KINDS)


class LedgerTests(unittest.TestCase):
    def test_panel_insert_is_idempotent_and_pnl_sums_it(self):
        self.assertIn("ON CONFLICT (send_request_id)", swap.INSERT_PANEL_COMMISSION_SQL)
        self.assertIn("NULL, NULL, 0", swap.INSERT_PANEL_COMMISSION_SQL)
        src = inspect.getsource(compute_pnl)
        start = src.index("swap_commission_cost")
        chunk = src[start:start + 400]
        self.assertIn("SUM(amount_rub)", chunk)
        self.assertIn("swap_commission_entries", chunk)
        self.assertNotIn("chat_id", chunk)

    def test_swap_send_does_not_book_shift_recon(self):
        self.assertNotIn("record_shift_recon", inspect.getsource(swap))


class _SendConn:
    def __init__(self, row=None):
        self.row = row
        self.fees: list = []
        self.inserts: list = []

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def acquire(self):
        return self

    async def execute(self, sql, *args):
        if self.row is not None and "SET status = $2" in sql:
            self.row["status"] = args[1]
            if len(args) > 2 and args[2]:
                self.row["txid"] = args[2]
        if self.row is not None and "signer_unknown" in sql:
            self.row["reject_reason"] = "signer_unknown"

    async def fetchrow(self, sql, *args):
        if "FROM payout_requests" in sql:
            return dict(self.row) if self.row else None
        return None

    async def fetchval(self, sql, *args):
        if "INSERT INTO payout_requests" in sql:
            self.inserts.append(args)
            if self.row:
                return None
            self.row = {"request_id": args[0], "status": "queued", "txid": None, "kind": args[1]}
            return args[0]
        if "INSERT INTO swap_commission_entries" in sql:
            self.fees.append(args)
            return 1
        return None


def _confirm_body(request_id: str) -> SwapConfirmIn:
    token = swap.make_swap_token(operator_id=4, shift_id=9, request_id=request_id, quote=QUOTE)
    return SwapConfirmIn(
        coin="ltc",
        address=LTC,
        crypto_amount="1.5",
        fee_crypto="usdt",
        fee_amount="5.2",
        preview_token=token,
        totp_code="123456",
    )


class SendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        secret = patch.object(swap.settings, "secret_key", "test-secret")
        secret.start()
        self.addCleanup(secret.stop)

    async def _confirm(self, conn: _SendConn, signer_reply):
        submit = AsyncMock(return_value=signer_reply)

        async def get_pool():
            return conn

        with (
            patch("hot_wallet_swap.quote_swap", new=AsyncMock(return_value=QUOTE)),
            patch(
                "hot_wallet_swap.run_swap_checks",
                new=AsyncMock(return_value=([pwp.Check("balance", True, "")], {})),
            ),
            patch("hot_wallet_swap.consume_totp", new=AsyncMock()),
            patch("db.get_pool", new=get_pool),
            patch("signer_client.submit_signer_payout", new=submit),
            patch("auto_payout_audit_log.audit_payout_event", new=AsyncMock()),
            patch("hot_wallet_swap.notify_admin", new=AsyncMock()),
            patch("project_wallet_payout.mark_confirmed", new=AsyncMock()),
        ):
            try:
                result = await swap.confirm(operator_id=4, shift_id=9, body=_confirm_body("swap:4:abc"))
            except pwp.WalletPayoutError as exc:
                return exc, submit, conn
        return result, submit, conn

    async def test_accept_writes_swap_send_and_fee(self):
        result, submit, conn = await self._confirm(_SendConn(), ("accepted", {"txid": "ab" * 32}))
        self.assertEqual(result["txid"], "ab" * 32)
        self.assertFalse(result["already_sent"])
        self.assertEqual(submit.await_args.args[0]["kind"], "swap_send")
        self.assertEqual(submit.await_args.args[0]["request_id"], "swap:4:abc")
        self.assertIsNone(submit.await_args.args[0].get("user_id"))
        self.assertEqual(conn.inserts[0][1], "swap_send")
        self.assertEqual(conn.inserts[0][2], "9")
        self.assertEqual(conn.fees[0][1], "usdt")
        self.assertEqual(conn.fees[0][4], 468.0)
        self.assertEqual(conn.fees[0][6], "swap:4:abc")
        self.assertNotIn("record_shift_recon", inspect.getsource(swap.confirm))

    async def test_reject_does_not_record_fee(self):
        exc, submit, conn = await self._confirm(_SendConn(), ("rejected", {"reason": "insufficient_funds"}))
        self.assertIsInstance(exc, pwp.WalletPayoutError)
        self.assertEqual(exc.code, "rejected")
        self.assertEqual(conn.fees, [])
        self.assertEqual(submit.await_count, 1)
        self.assertEqual(conn.row["status"], "failed")

    async def test_unknown_does_not_record_fee_and_blocks_retry(self):
        conn = _SendConn()
        exc, submit, _conn = await self._confirm(conn, ("unknown", {}))
        self.assertEqual(exc.code, "signer_unknown")
        self.assertEqual(conn.fees, [])
        again, submit2, _ = await self._confirm(conn, ("accepted", {"txid": "cd" * 32}))
        self.assertIsInstance(again, pwp.WalletPayoutError)
        self.assertEqual(again.code, "already_sent")
        self.assertEqual(submit.await_count, 1)
        self.assertEqual(submit2.await_count, 0)
        self.assertEqual(conn.fees, [])

    async def test_second_confirm_does_not_send_again(self):
        conn = _SendConn()
        first, submit, _conn = await self._confirm(conn, ("accepted", {"txid": "ab" * 32}))
        self.assertEqual(first["txid"], "ab" * 32)
        second, submit2, _ = await self._confirm(conn, ("accepted", {"txid": "ee" * 32}))
        self.assertEqual(second["already_sent"], True)
        self.assertEqual(second["txid"], "ab" * 32)
        self.assertEqual(submit.await_count, 1)
        self.assertEqual(submit2.await_count, 0)
        self.assertEqual(len(conn.fees), 2)


if __name__ == "__main__":
    unittest.main()
