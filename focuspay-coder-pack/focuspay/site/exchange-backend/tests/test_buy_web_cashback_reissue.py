"""Сайт перевыставляет PayFast, если сумму снизил только кешбэк.

Инцидент 322160816967: probe ушёл на 5057, клиенту показали 4977 после
кешбэка 80.15, ваучера не было. Раньше перевыпуск был только при disc_applied.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from auto_service_gate import NoShiftDecision
from payin_discovery import PayinDiscoveryResult
from payin_resolver import PayinPlan


def _pool():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)
    conn.fetchrow = AsyncMock(return_value={"order_id": "322160816967"})

    class _Tx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    conn.transaction = MagicMock(return_value=_Tx())
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


class BuyWebCashbackReissueTests(unittest.IsolatedAsyncioTestCase):
    async def test_cashback_without_voucher_reissues_payin(self):
        from buy_order_web import create_buy_web

        probe = {
            "uuid_system": "old-uuid",
            "bill": {"bank": "Т-Банк", "reciver": "2200700900480830"},
            "_merchant_id": "payfast",
            "_merchant_attempts": [],
        }
        reissued = {
            "uuid_system": "new-uuid",
            "bill": {"bank": "Т-Банк", "reciver": "2200700900480830"},
            "_merchant_id": "payfast",
            "_merchant_attempts": [],
        }
        discovery = PayinDiscoveryResult(
            plan=PayinPlan(mode="single", has_bill=True, parts=[5057], pay_now=5057),
            probe_response=probe,
            probe_order_id="322160816967",
        )
        create_payin = AsyncMock(return_value=reissued)
        cancel = AsyncMock()
        create_order = AsyncMock()

        with (
            patch("bot_status_bridge.is_user_banned", new=AsyncMock(return_value=(False, None, None))),
            patch(
                "auto_service_gate.resolve_no_shift_access",
                new=AsyncMock(return_value=NoShiftDecision(kind="allow_shift", reason="shift")),
            ),
            patch("buy_order_web.try_create_payin_rail_buy", new=AsyncMock(return_value=None)),
            patch("buy_order_web.discover_payin_plan", new=AsyncMock(return_value=discovery)),
            patch("buy_order_web.get_pool", new=AsyncMock(return_value=_pool())),
            patch("buy_order_web.should_use_cashback", new=AsyncMock(return_value=True)),
            patch("buy_order_web.get_active_discounts", new=AsyncMock(return_value=[])),
            patch(
                "buy_order_web.apply_cashback_with_conn",
                new=AsyncMock(return_value=(4976.85, 0.00056969, 80.15)),
            ),
            patch("buy_order_web.hold_cashback_for_order", new=AsyncMock(return_value=80.15)),
            patch("buy_crypto_amount.clamp_buy_crypto_amount", new=lambda amount, **_k: amount),
            patch("buy_order_web.cancel_payin", new=cancel),
            patch("buy_order_web.create_payin_order", new=create_payin),
            patch("buy_order_web._create_buy_order_in_tx", new=create_order),
        ):
            result = await create_buy_web(
                user_id=528707709,
                crypto_sym="BTC",
                crypto_amount=0.00056969,
                fiat_amount=5057,
                rate=8875332.067,
                requisites="bc1qexample",
                sub_token="CARDRUB",
                plan_mode=None,
                client_ip=None,
            )

        cancel.assert_awaited_once_with("old-uuid")
        create_payin.assert_awaited_once()
        self.assertEqual(create_payin.await_args.kwargs["fiat_amount"], 4977)
        self.assertEqual(create_payin.await_args.kwargs["sub_token"], "CARDRUB")
        self.assertEqual(create_order.await_args.kwargs["fiat_amount"], 4977.0)
        self.assertEqual(create_order.await_args.kwargs["cashback_applied_rub"], 80.15)
        self.assertEqual(create_order.await_args.kwargs["exchange_discount_applied_rub"], 0)
        snap = create_order.await_args.kwargs["payment_snapshot"]
        self.assertEqual(snap["fiat_amount"], 4977)
        self.assertEqual(snap["merchant_uuid"], "new-uuid")
        self.assertEqual(result["bill"]["reciver"], "2200700900480830")
        self.assertEqual(result["cashback_applied"], 80.15)
        self.assertEqual(result["exchange_discount_applied"], 0)
