"""Регрессии отмены клиентской заявки через PayFast."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.exchange_flow import confirm_cancel_handler


class ConfirmCancelMerchantTests(unittest.IsolatedAsyncioTestCase):
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
            "order_id": "O1",
            "direction": "buy",
            "status": "CREATED",
            "merchant_order_id": "payfast-uuid",
        }

    async def test_buy_keeps_order_active_when_merchant_declines_cancel(self):
        update = self._update()
        context = self._context()
        with patch("handlers.exchange_flow.rate_limit_ok", new=AsyncMock(return_value=True)), patch(
            "handlers.exchange_flow.get_active_order_by_user",
            new=AsyncMock(return_value=self._buy_order()),
        ), patch(
            "services.merchant_api_helpers.cancel_payin_for_order",
            new=AsyncMock(return_value={"status": 422, "body": {"error": "not cancellable"}}),
        ), patch(
            "services.stale_payin_hold.resolve_failed_merchant_cancel",
            new=AsyncMock(return_value="still_open"),
        ), patch(
            "handlers.exchange_flow.update_order_status",
            new=AsyncMock(),
        ) as update_status, patch(
            "services.db.clear_receipt_ops_pending",
            new=AsyncMock(),
        ) as clear_pending, patch(
            "handlers.exchange_flow.menu_for",
            new=AsyncMock(return_value=None),
        ):
            await confirm_cancel_handler(update, context)

        update_status.assert_not_awaited()
        clear_pending.assert_not_awaited()
        self.assertIn("Не удалось отменить", update.message.reply_text.await_args.args[0])
        self.assertEqual(context.user_data, {"step": "confirm_cancel"})

    async def test_buy_keeps_order_active_when_merchant_cancel_raises(self):
        update = self._update()
        context = self._context()
        with patch("handlers.exchange_flow.rate_limit_ok", new=AsyncMock(return_value=True)), patch(
            "handlers.exchange_flow.get_active_order_by_user",
            new=AsyncMock(return_value=self._buy_order()),
        ), patch(
            "services.merchant_api_helpers.cancel_payin_for_order",
            new=AsyncMock(side_effect=RuntimeError("timeout")),
        ), patch(
            "handlers.exchange_flow.update_order_status",
            new=AsyncMock(),
        ) as update_status, patch(
            "services.db.clear_receipt_ops_pending",
            new=AsyncMock(),
        ) as clear_pending, patch(
            "handlers.exchange_flow.menu_for",
            new=AsyncMock(return_value=None),
        ):
            await confirm_cancel_handler(update, context)

        update_status.assert_not_awaited()
        clear_pending.assert_not_awaited()
        self.assertIn("Не удалось отменить", update.message.reply_text.await_args.args[0])

    async def test_buy_cancels_locally_after_merchant_confirmation(self):
        update = self._update()
        context = self._context()
        with patch("handlers.exchange_flow.rate_limit_ok", new=AsyncMock(return_value=True)), patch(
            "handlers.exchange_flow.get_active_order_by_user",
            new=AsyncMock(return_value=self._buy_order()),
        ), patch(
            "services.merchant_api_helpers.cancel_payin_for_order",
            new=AsyncMock(return_value={"status": 200}),
        ), patch(
            "handlers.exchange_flow.update_order_status",
            new=AsyncMock(),
        ) as update_status, patch(
            "services.db.clear_receipt_ops_pending",
            new=AsyncMock(),
        ) as clear_pending, patch(
            "services.db.get_buyer_payfast_conversion",
            new=AsyncMock(return_value={"paid": 0, "failed": 0}),
        ), patch(
            "handlers.exchange_flow.menu_for",
            new=AsyncMock(return_value=None),
        ):
            await confirm_cancel_handler(update, context)

        update_status.assert_awaited_once_with("O1", "CANCELED")
        clear_pending.assert_awaited_once_with("O1")

    async def test_sell_cancels_without_merchant_request(self):
        update = self._update()
        context = self._context()
        order = {"order_id": "O2", "direction": "sell", "status": "CREATED"}
        with patch("handlers.exchange_flow.rate_limit_ok", new=AsyncMock(return_value=True)), patch(
            "handlers.exchange_flow.get_active_order_by_user",
            new=AsyncMock(return_value=order),
        ), patch(
            "services.merchant_api_helpers.cancel_payin_for_order",
            new=AsyncMock(),
        ) as cancel_payin, patch(
            "handlers.exchange_flow.update_order_status",
            new=AsyncMock(),
        ) as update_status, patch(
            "services.db.clear_receipt_ops_pending",
            new=AsyncMock(),
        ) as clear_pending, patch(
            "services.db.get_buyer_payfast_conversion",
            new=AsyncMock(return_value={"paid": 0, "failed": 0}),
        ), patch(
            "handlers.exchange_flow.menu_for",
            new=AsyncMock(return_value=None),
        ):
            await confirm_cancel_handler(update, context)

        cancel_payin.assert_not_awaited()
        update_status.assert_awaited_once_with("O2", "CANCELED")
        clear_pending.assert_awaited_once_with("O2")
