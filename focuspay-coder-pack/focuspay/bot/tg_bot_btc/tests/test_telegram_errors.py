"""Глобальный error handler всегда закрывает callback spinner."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from handlers.telegram_errors import (
    answer_callback_safe,
    telegram_error_handler,
    unanswered_callback_fallback,
)


class AnswerCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_ok(self):
        query = SimpleNamespace(answer=AsyncMock(), data="hub:x")
        self.assertTrue(await answer_callback_safe(query))
        query.answer.assert_awaited()

    async def test_answer_failure_logged_not_raised(self):
        query = SimpleNamespace(
            answer=AsyncMock(side_effect=RuntimeError("too old")),
            data="hub:x",
        )
        self.assertFalse(await answer_callback_safe(query, "hi", show_alert=True))


class ErrorHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_exception_answers_query(self):
        query = SimpleNamespace(answer=AsyncMock(), data="hub:balance")
        update = SimpleNamespace(callback_query=query, effective_message=None)
        context = SimpleNamespace(error=RuntimeError("boom"))
        await telegram_error_handler(update, context)
        query.answer.assert_awaited()
        kwargs = query.answer.await_args.kwargs
        self.assertTrue(kwargs.get("show_alert"))

    async def test_message_exception_replies(self):
        msg = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            callback_query=None,
            effective_message=msg,
            effective_chat=SimpleNamespace(type="private"),
        )
        context = SimpleNamespace(error=RuntimeError("boom"))
        await telegram_error_handler(update, context)
        msg.reply_text.assert_awaited()

    async def test_group_message_exception_is_silent(self):
        msg = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            callback_query=None,
            effective_message=msg,
            effective_chat=SimpleNamespace(type="supergroup"),
        )
        context = SimpleNamespace(error=RuntimeError("boom"))
        await telegram_error_handler(update, context)
        msg.reply_text.assert_not_awaited()

    async def test_unhandled_callback_answers(self):
        query = SimpleNamespace(answer=AsyncMock(), data="unknown:foo")
        update = SimpleNamespace(callback_query=query)
        await unanswered_callback_fallback(update, SimpleNamespace())
        query.answer.assert_awaited()
        self.assertTrue(query.answer.await_args.kwargs.get("show_alert"))


if __name__ == "__main__":
    unittest.main()
