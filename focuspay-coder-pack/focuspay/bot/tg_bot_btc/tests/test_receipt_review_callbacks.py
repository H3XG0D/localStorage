import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.receipt_review_callbacks import receipt_review_callback_handler


def _update(action="approve"):
    message = SimpleNamespace(
        chat_id=-5043279066,
        reply_text=AsyncMock(),
    )
    query = SimpleNamespace(
        message=message,
        from_user=SimpleNamespace(id=777, username="operator"),
        data=f"rcpt:{action}:ORD-1:signature",
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(callback_query=query), query


class ReceiptReviewCallbackTests(unittest.IsolatedAsyncioTestCase):
    def _patch_common(self):
        return (
            patch(
                "services.receipt_review_callbacks.config_rates.is_ops_group_chat",
                return_value=True,
            ),
            patch(
                "services.receipt_review_callbacks.config_rates.is_client_review_group_chat",
                return_value=False,
            ),
            patch("services.receipt_review_callbacks.TELEGRAM_ADMIN_IDS", {777}),
            patch(
                "services.receipt_review_callbacks.verify_receipt_review_signature",
                return_value=True,
            ),
        )

    async def test_approve_acknowledges_before_slow_payfast_result(self):
        update, query = _update()
        patches = self._patch_common()
        for item in patches:
            item.start()
        try:
            with patch(
                "services.receipt_review_callbacks.approve_receipt_and_send_to_payfast",
                new=AsyncMock(return_value=(True, None)),
            ) as approve:
                await receipt_review_callback_handler(update, SimpleNamespace(bot=object()))
        finally:
            for item in reversed(patches):
                item.stop()

        query.answer.assert_awaited_once_with("⏳ Обрабатываю чек…", show_alert=False)
        approve.assert_awaited_once()
        query.edit_message_reply_markup.assert_awaited_once_with(reply_markup=None)
        query.message.reply_text.assert_awaited_once()

    async def test_approve_failure_replies_and_keeps_retry_button(self):
        update, query = _update()
        patches = self._patch_common()
        for item in patches:
            item.start()
        try:
            with patch(
                "services.receipt_review_callbacks.approve_receipt_and_send_to_payfast",
                new=AsyncMock(return_value=(False, "Payfast временно недоступен")),
            ):
                await receipt_review_callback_handler(update, SimpleNamespace(bot=object()))
        finally:
            for item in reversed(patches):
                item.stop()

        query.answer.assert_awaited_once_with("⏳ Обрабатываю чек…", show_alert=False)
        query.edit_message_reply_markup.assert_not_awaited()
        query.message.reply_text.assert_awaited_once_with(
            "⚠️ Payfast временно недоступен"
        )

    async def test_internal_error_does_not_leak_exception_text(self):
        update, query = _update()
        patches = self._patch_common()
        for item in patches:
            item.start()
        try:
            with patch(
                "services.receipt_review_callbacks.approve_receipt_and_send_to_payfast",
                new=AsyncMock(side_effect=RuntimeError("database password")),
            ):
                await receipt_review_callback_handler(update, SimpleNamespace(bot=object()))
        finally:
            for item in reversed(patches):
                item.stop()

        query.message.reply_text.assert_awaited_once_with(
            "⚠️ Ошибка обработки заявки. Повторите позже или сообщите оператору."
        )
        self.assertNotIn("database password", query.message.reply_text.await_args.args[0])
