""" /start одобряет висящие заявки в чаты до капчи. """
from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.start import start_handler


def _stub_captcha_module() -> ModuleType:
    mod = ModuleType("handlers.captcha_handler")
    mod.send_captcha = AsyncMock()
    mod.CAPTCHA_REF_PAYLOAD_KEY = "_captcha_start_ref"
    return mod


class StartJoinBeforeCaptchaTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_user_approve_runs_before_captcha_return(self):
        user = SimpleNamespace(id=424242, username="buyer", first_name="Buyer")
        message = MagicMock()
        message.text = "/start"
        message.reply_text = AsyncMock()

        update = SimpleNamespace(
            effective_user=user,
            effective_chat=SimpleNamespace(id=424242),
            message=message,
        )
        context = MagicMock()
        context.args = []
        context.user_data = {}
        context.bot = MagicMock()

        captcha_mod = _stub_captcha_module()

        with (
            patch.dict(sys.modules, {"handlers.captcha_handler": captcha_mod}),
            patch("handlers.start.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch("handlers.start.get_bot_user", new=AsyncMock(return_value=None)),
            patch("handlers.start.ensure_bot_user", new=AsyncMock()),
            patch(
                "services.community_join_actions.try_approve_community_join",
                new=AsyncMock(return_value="approved"),
            ) as community_approve,
            patch(
                "services.news_join_actions.try_approve_news_join",
                new=AsyncMock(return_value="no_request"),
            ) as news_approve,
            patch(
                "services.reviews_join_actions.try_approve_reviews_join",
                new=AsyncMock(return_value="approved"),
            ) as reviews_approve,
            patch("services.config_rates.TELEGRAM_ADMIN_IDS", []),
            patch(
                "handlers.ops_bind.extract_ops_bind_token",
                return_value=None,
            ),
            patch(
                "handlers.start.stash_pending_ref_token_from_payload",
                new=AsyncMock(),
            ),
        ):
            await start_handler(update, context)

        community_approve.assert_awaited_once()
        news_approve.assert_awaited_once()
        reviews_approve.assert_awaited_once()
        captcha_mod.send_captcha.assert_awaited_once()
        self.assertGreaterEqual(message.reply_text.await_count, 1)
        texts = [c.args[0] for c in message.reply_text.await_args_list if c.args]
        self.assertTrue(any("focus чат" in t for t in texts))
        self.assertTrue(any("отзывов" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
