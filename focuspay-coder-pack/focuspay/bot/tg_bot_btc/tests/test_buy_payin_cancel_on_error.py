"""Регрессия: при ошибке реквизитов BUY созданный счёт мерчанта отменяется.

Инцидент: клиент подтверждал условия и вводил кошелёк, но мерчант отвечал без
валидных реквизитов (или ошибкой). Раньше висящий payin не отменялся, а общий
обработчик показывал «Ошибка. Начните сначала». Тесты фиксируют, что при
NO_BILL / PAYMENT_PROVIDER_ERROR счёт отменяется, а исходная ошибка пробрасывается.

Второй инцидент: скидка балансом холдится до INSERT заявки; 75s timeout
(CancelledError) раньше не снимал hold — баланс «пропадал».
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _pool_with_conn():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)  # нет активной BUY-заявки

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


class BuyPayinCancelOnErrorTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, api_response):
        from services.buy_order_service import create_buy_part_order

        cancel = AsyncMock()
        create_payin = AsyncMock(return_value=api_response)

        with (
            patch("services.buy_order_service.get_pool", new=AsyncMock(return_value=_pool_with_conn())),
            patch("services.buy_order_service.should_use_cashback", new=AsyncMock(return_value=False)),
            patch("services.buy_order_service.user_has_active_buy_order", new=AsyncMock(return_value=False)),
            patch("services.buy_order_service.clamp_buy_crypto_amount", new=lambda c, **k: c),
            patch(
                "services.buy_order_service._ensure_bill_via_poll",
                new=AsyncMock(side_effect=lambda r: r),
            ),
        ):
            with self.assertRaises(ValueError) as ctx:
                await create_buy_part_order(
                    create_payin_order_fn=create_payin,
                    cancel_payin_fn=cancel,
                    order_id="O123",
                    user_id=42,
                    crypto="BTC",
                    crypto_amount=0.001,
                    fiat_amount=7260,
                    rate=8000000.0,
                    requisites="bc1qexample",
                    sub_token="SBPRUB",
                    callback_url="https://cb",
                )
        return ctx.exception, cancel

    async def test_no_bill_cancels_merchant_order(self):
        # Мерчант вернул UUID, но без валидных реквизитов.
        exc, cancel = await self._run(
            {"uuid_system": "UUID-1", "bill": {}, "data_order": {}}
        )
        self.assertEqual(str(exc), "NO_BILL")
        cancel.assert_awaited_once_with("UUID-1")

    async def test_provider_error_cancels_merchant_order(self):
        exc, cancel = await self._run(
            {"status_pending": "error", "uuid": "UUID-2", "data_order": {}}
        )
        self.assertEqual(str(exc), "PAYMENT_PROVIDER_ERROR")
        cancel.assert_awaited_once_with("UUID-2")


class BuyCashbackHoldReleaseTests(unittest.IsolatedAsyncioTestCase):
    """Холд скидки балансом обязан сниматься, если заявка так и не создана."""

    async def _create(
        self,
        *,
        create_payin,
        api_response=None,
        ensure_bill=None,
    ):
        from services.buy_order_service import create_buy_part_order

        cancel = AsyncMock()
        hold = AsyncMock(return_value=3053.23)
        release_cb = AsyncMock()
        release_disc = AsyncMock()
        create_order = AsyncMock()
        ensure = (
            ensure_bill
            if ensure_bill is not None
            else AsyncMock(side_effect=lambda r: r)
        )
        with (
            patch(
                "services.buy_order_service.get_pool",
                new=AsyncMock(return_value=_pool_with_conn()),
            ),
            patch(
                "services.buy_order_service.should_use_cashback",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "services.buy_order_service.user_has_active_buy_order",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "services.buy_order_service.apply_cashback_with_conn",
                new=AsyncMock(return_value=(1223.77, 0.00050608, 3053.23)),
            ),
            patch(
                "services.buy_order_service.hold_cashback_for_order",
                new=hold,
            ),
            patch(
                "services.buy_order_service.release_cashback_for_order",
                new=release_cb,
            ),
            patch(
                "services.buy_order_service.release_discount_for_order",
                new=release_disc,
            ),
            patch(
                "services.buy_order_service.clamp_buy_crypto_amount",
                new=lambda c, **k: c,
            ),
            patch(
                "services.buy_order_service._ensure_bill_via_poll",
                new=ensure,
            ),
            patch(
                "services.buy_order_service._create_buy_order_in_tx",
                new=create_order,
            ),
        ):
            try:
                result = await create_buy_part_order(
                    create_payin_order_fn=create_payin,
                    cancel_payin_fn=cancel,
                    order_id="OHOLD1",
                    user_id=42,
                    crypto="BTC",
                    crypto_amount=0.00050608,
                    fiat_amount=4277,
                    rate=8000000.0,
                    requisites="bc1qexample",
                    sub_token="CARDRUB",
                    callback_url="https://cb",
                    api_response=api_response,
                )
            except BaseException as exc:
                return {
                    "exc": exc,
                    "result": None,
                    "cancel": cancel,
                    "hold": hold,
                    "release_cb": release_cb,
                    "create_order": create_order,
                }
        return {
            "exc": None,
            "result": result,
            "cancel": cancel,
            "hold": hold,
            "release_cb": release_cb,
            "create_order": create_order,
        }

    async def test_cancelled_after_hold_releases_cashback(self):
        # Probe на полную сумму, холд снижает к оплате → перевыставление счёта,
        # которое рвётся CancelledError (таймаут wait_for 75s).
        create_payin = AsyncMock(side_effect=asyncio.CancelledError())
        out = await self._create(
            create_payin=create_payin,
            api_response={
                "uuid_system": "UUID-STALE",
                "bill": {"reciver": "40817", "bank": "Sber"},
            },
        )
        self.assertIsInstance(out["exc"], asyncio.CancelledError)
        out["hold"].assert_awaited()
        out["release_cb"].assert_awaited_with("OHOLD1")
        out["create_order"].assert_not_awaited()
        out["cancel"].assert_any_await("UUID-STALE")

    async def test_cancelled_during_bill_poll_releases_and_cancels_new_payin(self):
        create_payin = AsyncMock(
            return_value={"uuid_system": "UUID-NEW", "bill": {}, "data_order": {}}
        )
        ensure = AsyncMock(side_effect=asyncio.CancelledError())
        out = await self._create(
            create_payin=create_payin,
            api_response=None,
            ensure_bill=ensure,
        )
        self.assertIsInstance(out["exc"], asyncio.CancelledError)
        out["release_cb"].assert_awaited_with("OHOLD1")
        out["create_order"].assert_not_awaited()
        out["cancel"].assert_any_await("UUID-NEW")

    async def test_no_bill_after_cashback_releases_hold(self):
        create_payin = AsyncMock(
            return_value={"uuid_system": "UUID-1", "bill": {}, "data_order": {}}
        )
        out = await self._create(create_payin=create_payin)
        self.assertIsInstance(out["exc"], ValueError)
        self.assertEqual(str(out["exc"]), "NO_BILL")
        out["release_cb"].assert_awaited_with("OHOLD1")
        out["cancel"].assert_any_await("UUID-1")
        out["create_order"].assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
