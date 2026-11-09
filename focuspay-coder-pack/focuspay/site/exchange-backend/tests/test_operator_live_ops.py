"""Живая очередь /ops/orders: чужие открытые, видео, проверка аккаунта, баланс."""
from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from permissions import attach_operator_permissions_sync
from routers.operator import (
    AccountReviewRequest,
    AdjustBalanceRequest,
    CancelOrderRequest,
    _assert_live_order_access,
    _can_send_receipt_to_payfast,
    _fill_payout_rails,
    _has_live_requisites,
    _order_out,
    adjust_client_balance,
    cancel_order_by_operator,
    get_operator_orders,
    request_order_video,
    review_client_account,
    send_order_receipt_to_payfast,
)


def _conn():
    """asyncpg transaction() — обычный async context manager, не корутина."""
    conn = AsyncMock()
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=conn)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    return conn


def _pool(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = ctx

    async def _get_pool():
        return pool

    return _get_pool


def _open_order(**extra):
    row = {
        "order_id": "O1",
        "direction": "buy",
        "status": "PENDING",
        "crypto": "usdt",
        "fiat_amount": 1000,
        "crypto_amount": 10,
        "operator_id": 2,
        "operator_username": "alice",
        "operator_display_name": "Alice",
        "user_id": 555,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    row.update(extra)
    return row


class LiveRequisitesFlagTests(unittest.TestCase):
    def test_pending_with_bill(self):
        self.assertTrue(
            _has_live_requisites(
                {
                    "status": "PENDING",
                    "payment_snapshot": {"bill": {"bank": "Sber", "fio": "Ivan"}},
                }
            )
        )

    def test_created_with_merchant_uuid(self):
        self.assertTrue(
            _has_live_requisites(
                {"status": "CREATED", "merchant_order_id": "pf-1"}
            )
        )

    def test_awaiting_check_with_payin_requisite(self):
        self.assertTrue(
            _has_live_requisites(
                {"status": "AWAITING_CHECK", "payin_requisite_id": 9}
            )
        )

    def test_paid_with_bill_is_not_live(self):
        self.assertFalse(
            _has_live_requisites(
                {
                    "status": "PAID",
                    "payment_snapshot": {"bill": {"bank": "Sber"}},
                }
            )
        )

    def test_order_out_exposes_flag(self):
        out = _order_out(
            _open_order(
                payment_snapshot={"merchant_uuid": "abc", "bill": {"bank": "Tinkoff"}}
            )
        )
        self.assertTrue(out["live_requisites"])
        self.assertEqual(out["required_receipt_type"], None)
        self.assertFalse(out["can_send_receipt_to_payfast"])
        self.assertEqual(out["payfast_id"], "abc")
        self.assertFalse(out["receipt_ops_pending"])

    def test_can_send_receipt_for_held_pdf(self):
        row = _open_order(
            status="AWAITING_CHECK",
            receipt_file="r.pdf",
            required_receipt_type=2,
            payment_snapshot={"receipt_ops_pending": True, "merchant_uuid": "pf-1"},
        )
        self.assertTrue(_can_send_receipt_to_payfast(row))
        out = _order_out(row)
        self.assertTrue(out["can_send_receipt_to_payfast"])
        self.assertTrue(out["receipt_ops_pending"])
        self.assertEqual(out["payfast_id"], "pf-1")

    def test_can_send_receipt_hidden_for_video_and_payin(self):
        self.assertFalse(
            _can_send_receipt_to_payfast(
                _open_order(
                    status="AWAITING_CHECK",
                    receipt_file="clip.mp4",
                    required_receipt_type=3,
                )
            )
        )
        self.assertFalse(
            _can_send_receipt_to_payfast(
                _open_order(
                    status="AWAITING_CHECK",
                    receipt_file="r.pdf",
                    payin_requisite_id=9,
                )
            )
        )

    def test_can_send_receipt_hidden_without_ops_pending(self):
        self.assertFalse(
            _can_send_receipt_to_payfast(
                _open_order(
                    status="AWAITING_CHECK",
                    receipt_file="r.pdf",
                    required_receipt_type=2,
                    payment_snapshot={"merchant_uuid": "pf-1"},
                )
            )
        )


class LiveOrderAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_unassigned_allowed(self):
        conn = _conn()
        await _assert_live_order_access(conn, {"id": 1}, {"operator_id": None})
        conn.fetchrow.assert_not_called()

    async def test_colleague_on_shift_allowed(self):
        conn = _conn()
        conn.fetchrow = AsyncMock(return_value={"ok": 1})
        await _assert_live_order_access(conn, {"id": 1}, {"operator_id": 9})

    async def test_foreign_without_shift_denied(self):
        conn = _conn()
        conn.fetchrow = AsyncMock(
            side_effect=[None, {"display_name": "Bob", "username": "bob"}]
        )
        with self.assertRaises(HTTPException) as ctx:
            await _assert_live_order_access(conn, {"id": 1}, {"operator_id": 9})
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Bob", str(ctx.exception.detail))


class OpenQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_orders_include_other_operators_open(self):
        other = _open_order(order_id="OTH1", operator_id=9, status="PENDING")
        conn = _conn()
        conn.fetch = AsyncMock(side_effect=[[], [], [other], [], [], [], [], []])
        get_pool = _pool(conn)

        with patch("routers.operator.get_pool", new=get_pool), patch(
            "routers.operator._queue_stats",
            new=AsyncMock(return_value={"queue_count": 0}),
        ), patch(
            "routers.operator._withdrawal_market_rates",
            new=AsyncMock(return_value={}),
        ):
            result = await get_operator_orders(op={"id": 1, "username": "viewer"})

        self.assertEqual(len(result["orders"]), 1)
        self.assertEqual(result["orders"][0]["order_id"], "OTH1")
        self.assertFalse(result["orders"][0]["assigned_to_me"])
        self.assertEqual(result["orders"][0]["assigned_operator"]["display_name"], "Alice")

    def test_source_does_not_filter_open_list_by_owner(self):
        source = Path(__file__).resolve().parent.parent / "routers" / "operator.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn(
            "WHERE o.status NOT IN ('PAID', 'CANCELED', 'EXPIRED', 'FAILED')",
            text,
        )
        self.assertIn('"""incoming — без оператора; orders — все открытые на смене', text)


class VideoRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_sets_type_3(self):
        order = _open_order(status="PENDING", operator_id=1)
        updated = _open_order(
            status="AWAITING_CHECK",
            operator_id=1,
            required_receipt_type=3,
        )
        conn = _conn()
        conn.fetchrow = AsyncMock(side_effect=[order, updated])
        get_pool = _pool(conn)

        with patch("routers.operator.get_pool", new=get_pool), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch(
            "routers.operator._assert_live_order_access", new=AsyncMock()
        ), patch(
            "bot_status_bridge.request_client_video",
            new=AsyncMock(return_value=(True, "ok")),
        ) as video:
            result = await request_order_video("O1", op={"id": 1, "username": "op"})

        video.assert_awaited_once_with("O1", source="operator")
        self.assertEqual(result["order"]["required_receipt_type"], 3)
        self.assertEqual(result["order"]["status"], "AWAITING_CHECK")
        self.assertEqual(result["result"], "ok")

    async def test_video_rejects_paid(self):
        conn = _conn()
        conn.fetchrow = AsyncMock(return_value=_open_order(status="PAID", operator_id=1))
        get_pool = _pool(conn)
        with patch("routers.operator.get_pool", new=get_pool), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch(
            "routers.operator._assert_live_order_access", new=AsyncMock()
        ):
            with self.assertRaises(HTTPException) as ctx:
                await request_order_video("O1", op={"id": 1, "username": "op"})
        self.assertEqual(ctx.exception.status_code, 400)


class SendReceiptToPayfastTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_held_pdf(self):
        order = _open_order(
            status="AWAITING_CHECK",
            operator_id=1,
            receipt_file="r.pdf",
            required_receipt_type=2,
            payment_snapshot={"merchant_uuid": "pf-1", "receipt_ops_pending": True},
        )
        sent = {**order, "status": "PENDING", "payment_snapshot": {"receipt_ops_pending": False}}
        conn = _conn()
        conn.fetchrow = AsyncMock(side_effect=[order, sent])
        get_pool = _pool(conn)

        with patch("routers.operator.get_pool", new=get_pool), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch(
            "routers.operator._assert_live_order_access", new=AsyncMock()
        ), patch(
            "bot_status_bridge.send_receipt_to_payfast",
            new=AsyncMock(return_value=(True, None)),
        ) as send:
            result = await send_order_receipt_to_payfast(
                "O1", op={"id": 1, "username": "op"}
            )

        send.assert_awaited_once_with("O1", operator_id=1)
        self.assertEqual(result["result"], "sent")
        self.assertEqual(result["order"]["status"], "PENDING")
        self.assertFalse(result["order"]["can_send_receipt_to_payfast"])

    async def test_rejects_without_receipt(self):
        conn = _conn()
        conn.fetchrow = AsyncMock(
            return_value=_open_order(status="AWAITING_CHECK", operator_id=1)
        )
        get_pool = _pool(conn)
        with patch("routers.operator.get_pool", new=get_pool), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch(
            "routers.operator._assert_live_order_access", new=AsyncMock()
        ):
            with self.assertRaises(HTTPException) as ctx:
                await send_order_receipt_to_payfast("O1", op={"id": 1, "username": "op"})
        self.assertEqual(ctx.exception.status_code, 400)


class AccountReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_approve_pending(self):
        conn = _conn()
        conn.fetchrow = AsyncMock(
            return_value={
                "user_id": 555,
                "account_review_status": "pending",
                "is_banned": False,
            }
        )
        conn.execute = AsyncMock(return_value="UPDATE 1")
        get_pool = _pool(conn)

        with patch("routers.operator.get_pool", new=get_pool), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ):
            result = await review_client_account(
                555,
                AccountReviewRequest(action="approve"),
                op={"id": 7, "username": "op"},
            )

        self.assertEqual(result["account_review_status"], "approved")
        self.assertEqual(result["result"], "ok")
        conn.execute.assert_awaited()
        args = conn.execute.await_args.args
        self.assertIn("account_review_status", args[0])
        self.assertEqual(args[2], "approved")


class BalanceAdjustTests(unittest.IsolatedAsyncioTestCase):
    async def test_credit_accrual(self):
        conn = _conn()
        conn.fetchval = AsyncMock(return_value=1)
        conn.execute = AsyncMock(return_value="INSERT 0 1")
        get_pool = _pool(conn)
        op = attach_operator_permissions_sync(
            {"id": 1, "username": "fin", "operator_roles": ["finance"]}
        )

        with patch("routers.operator.get_pool", new=get_pool), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch(
            "permissions.enrich_operator_permissions",
            new=AsyncMock(return_value=op),
        ), patch(
            "user_unified_balance.unified_available",
            new=AsyncMock(return_value=10.0),
        ), patch(
            "user_unified_balance.get_unified_balance_stats",
            new=AsyncMock(
                return_value={
                    "available_rub": 25.0,
                    "balance_rub": 25.0,
                    "cashback_rub": 25.0,
                    "referral_rub": 0.0,
                }
            ),
        ):
            result = await adjust_client_balance(
                555,
                AdjustBalanceRequest(amount_rub=15, reason="компенсация"),
                op=op,
            )

        self.assertEqual(result["available_rub"], 25.0)
        insert = conn.execute.await_args.args
        self.assertEqual(insert[2], "accrual")
        self.assertEqual(insert[3], 15.0)
        self.assertTrue(str(insert[4]).startswith("ops:fin:"))

    async def test_debit_spend(self):
        conn = _conn()
        conn.fetchval = AsyncMock(return_value=1)
        conn.execute = AsyncMock(return_value="INSERT 0 1")
        get_pool = _pool(conn)
        op = attach_operator_permissions_sync(
            {
                "id": 2,
                "username": "sen",
                "operator_roles": ["client"],
                "role_grades": {"client": "senior"},
            }
        )

        with patch("routers.operator.get_pool", new=get_pool), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch(
            "permissions.enrich_operator_permissions",
            new=AsyncMock(return_value=op),
        ), patch(
            "user_unified_balance.unified_available",
            new=AsyncMock(return_value=40.0),
        ), patch(
            "user_unified_balance.get_unified_balance_stats",
            new=AsyncMock(
                return_value={
                    "available_rub": 25.0,
                    "balance_rub": 25.0,
                    "cashback_rub": 25.0,
                    "referral_rub": 0.0,
                }
            ),
        ):
            result = await adjust_client_balance(
                555,
                AdjustBalanceRequest(amount_rub=-15, reason="корректировка"),
                op=op,
            )

        self.assertEqual(result["type"], "spend")
        insert = conn.execute.await_args.args
        self.assertEqual(insert[2], "spend")
        self.assertEqual(insert[3], -15.0)

    async def test_debit_without_funds(self):
        conn = _conn()
        conn.fetchval = AsyncMock(return_value=1)
        get_pool = _pool(conn)
        op = attach_operator_permissions_sync(
            {"id": 1, "username": "fin", "operator_roles": ["finance"]}
        )

        with patch("routers.operator.get_pool", new=get_pool), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch(
            "permissions.enrich_operator_permissions",
            new=AsyncMock(return_value=op),
        ), patch(
            "user_unified_balance.unified_available",
            new=AsyncMock(return_value=5.0),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await adjust_client_balance(
                    555,
                    AdjustBalanceRequest(amount_rub=-10, reason="списание"),
                    op=op,
                )
        self.assertEqual(ctx.exception.status_code, 400)
        conn.execute.assert_not_called()

    async def test_client_without_senior_denied(self):
        op = attach_operator_permissions_sync(
            {"id": 3, "username": "cli", "operator_roles": ["client"]}
        )
        with patch(
            "permissions.enrich_operator_permissions",
            new=AsyncMock(return_value=op),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await adjust_client_balance(
                    555,
                    AdjustBalanceRequest(amount_rub=10, reason="начисление"),
                    op=op,
                )
        self.assertEqual(ctx.exception.status_code, 403)


class OperatorCancelTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, row, *, bot_set=None, cancel_pf=None, reason="неактуально"):
        updated = {**row, "status": "CANCELED"}
        conn = _conn()
        conn.fetchrow = AsyncMock(side_effect=[row, updated])
        conn.execute = AsyncMock()
        bot = bot_set if bot_set is not None else AsyncMock(return_value=True)
        pf = cancel_pf if cancel_pf is not None else AsyncMock()
        notify = AsyncMock()
        with patch("routers.operator.get_pool", new=_pool(conn)), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch(
            "bot_status_bridge.update_order_status", new=bot
        ), patch(
            "telegram_notify.send_user_message", new=notify
        ), patch(
            "merchant_api_helpers.cancel_payin_for_order", new=pf
        ):
            out = await cancel_order_by_operator(
                row["order_id"],
                CancelOrderRequest(reason=reason),
                op={"id": 1, "username": "op"},
            )
        return out, conn, bot, notify, pf

    async def test_operator_pending_buy_cancels_without_payfast(self):
        row = _open_order(
            order_id="16587456",
            status="OPERATOR_PENDING",
            operator_id=1,
            direction="buy",
        )
        out, conn, bot, notify, pf = await self._call(
            row, reason="Если актуально — пересоздайте заявку или напишите оператору @focus_operator"
        )
        self.assertEqual(out["order"]["status"], "CANCELED")
        conn.execute.assert_not_called()
        pf.assert_not_called()
        bot.assert_awaited_once_with(
            "16587456",
            "CANCELED",
            cancel_reason="Если актуально — пересоздайте заявку или напишите оператору @focus_operator",
            canceled_by=1,
        )
        notify.assert_awaited()
        text = notify.await_args.args[1]
        self.assertIn("пересоздайте", text)
        self.assertIn("@focus_operator", text)

    async def test_payfast_buy_still_cancels_merchant(self):
        row = _open_order(
            status="OPERATOR_PENDING",
            operator_id=1,
            merchant_order_id="pf-uuid-1",
            payment_snapshot={"merchant_uuid": "pf-uuid-1"},
        )
        _, _, bot, _, pf = await self._call(row)
        pf.assert_awaited_once()
        bot.assert_awaited_once()

    async def test_payin_rail_skips_payfast(self):
        row = _open_order(status="PENDING", operator_id=1, payin_requisite_id=9)
        _, _, _, _, pf = await self._call(row)
        pf.assert_not_called()

    async def test_bridge_error_returns_string_detail(self):
        row = _open_order(status="OPERATOR_PENDING", operator_id=1)
        with self.assertRaises(HTTPException) as ctx:
            await self._call(row, bot_set=AsyncMock(side_effect=RuntimeError("ledger boom")))
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIsInstance(ctx.exception.detail, str)
        self.assertIn("Не удалось отменить", ctx.exception.detail)

    async def test_rejected_transition_is_409(self):
        row = _open_order(status="OPERATOR_PENDING", operator_id=1)
        with self.assertRaises(HTTPException) as ctx:
            await self._call(row, bot_set=AsyncMock(return_value=False))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "Недопустимый переход статуса")


class UndefinedTableError(Exception):
    """asyncpg uses this name; operator.py matches on the type name."""


class FillPayoutRailsTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_table_does_not_raise(self):
        conn = _conn()
        conn.fetch = AsyncMock(side_effect=UndefinedTableError("missing"))
        sell = _open_order(order_id="S1", direction="sell")
        await _fill_payout_rails(conn, [sell])
        self.assertNotIn("payout_alloc_status", sell)

    async def test_other_db_errors_still_raise(self):
        conn = _conn()
        conn.fetch = AsyncMock(side_effect=RuntimeError("db down"))
        with self.assertRaises(RuntimeError):
            await _fill_payout_rails(conn, [_open_order(order_id="S1", direction="sell")])

    async def test_open_queue_survives_missing_rail_table(self):
        sell = _open_order(order_id="S1", direction="sell", operator_id=1, status="PENDING")
        conn = _conn()
        conn.fetch = AsyncMock(
            side_effect=[[], [], [sell], [], [], [], [], [], UndefinedTableError("missing")]
        )
        get_pool = _pool(conn)
        with patch("routers.operator.get_pool", new=get_pool), patch(
            "routers.operator._queue_stats",
            new=AsyncMock(return_value={"queue_count": 0}),
        ), patch(
            "routers.operator._withdrawal_market_rates",
            new=AsyncMock(return_value={}),
        ):
            result = await get_operator_orders(op={"id": 1, "username": "viewer"})
        self.assertEqual(result["orders"][0]["order_id"], "S1")
        self.assertEqual(result["orders"][0]["payout_rail"]["stage"], "awaiting_crypto")


class OperatorPendingCancelCopyTests(unittest.TestCase):
    def test_ops_orders_prefills_operator_pending_reason(self):
        ui = (
            Path(__file__).resolve().parents[3]
            / "focussite/frontend/src/panel/operator/OperatorOrders.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("OPERATOR_PENDING_CANCEL_REASON", ui)
        self.assertIn(
            "Если актуально — пересоздайте заявку или напишите оператору @focus_operator",
            ui,
        )


if __name__ == "__main__":
    unittest.main()
