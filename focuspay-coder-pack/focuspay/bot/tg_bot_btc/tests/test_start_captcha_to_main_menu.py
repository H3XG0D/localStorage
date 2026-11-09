"""Регрессия: пройденная капча повторно запускает /start с реальным главным меню."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.captcha_handler import CAPTCHA_TOKEN_KEY, captcha_text_handler
from handlers.start import start_handler
from services.menu import MENU_ABOUT, MENU_EXCHANGE, MENU_FOCUSBET, MENU_FOCUSVPN, MENU_PROFILE


class StartCaptchaToMainMenuTests(unittest.IsolatedAsyncioTestCase):
    async def test_captcha_success_restarts_start_and_sends_real_main_menu(self):
        user = SimpleNamespace(id=424242, username="buyer", first_name="Buyer")
        message = SimpleNamespace(text="/start", reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_user=user,
            effective_chat=SimpleNamespace(id=user.id),
            message=message,
        )
        context = SimpleNamespace(
            args=[],
            user_data={},
            bot=SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock()),
        )
        captcha_token = "captcha-token"
        os.environ.pop("EXCHANGE_MINIAPP_URL", None)

        with (
            patch("handlers.start.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch(
                "handlers.start.get_bot_user",
                new=AsyncMock(side_effect=[None, {"captcha_passed_at": "now"}]),
            ),
            patch("handlers.start.ensure_bot_user", new=AsyncMock()),
            patch("handlers.start._approve_pending_gated_joins", new=AsyncMock()),
            patch("handlers.captcha_handler.generate_captcha_image", return_value=(b"png", captcha_token)),
            patch("handlers.captcha_handler.verify_captcha_answer", return_value=True),
            patch("handlers.captcha_handler.set_captcha_passed", new=AsyncMock()) as set_captcha_passed,
            patch("handlers.ops_bind.maybe_handle_ops_bind", new=AsyncMock(return_value=False)),
            patch("handlers.exchange_flow.resend_active_order_prompt", new=AsyncMock(return_value=False)),
            patch("handlers.start.stash_pending_ref_token_from_payload", new=AsyncMock()),
            patch("handlers.start.log_start_ref_payload", new=AsyncMock()),
            patch("services.user_referral_attribution.assign_referrer_by_token", new=AsyncMock(return_value="empty")),
            patch("handlers.start.apply_promo_from_start_payload", new=AsyncMock(return_value=False)),
            patch("handlers.start.apply_pending_ref_token_if_any", new=AsyncMock(return_value="empty")),
            patch("services.user_referral_attribution.apply_pending_ref_token_if_any", new=AsyncMock(return_value="empty")),
            patch("handlers.start.user_has_attribution", new=AsyncMock(return_value=True)),
            patch("handlers.start.get_unified_balance_stats", new=AsyncMock(return_value={"saved_rub": 0})),
            patch("services.menu.get_partner_by_telegram", new=AsyncMock(return_value=None)),
            patch("services.db.user_has_payment_active_order", new=AsyncMock(return_value=False)),
            patch("handlers.start.send_welcome_photo", new=AsyncMock()) as send_welcome_photo,
        ):
            await start_handler(update, context)
            self.assertEqual(context.user_data[CAPTCHA_TOKEN_KEY], captcha_token)

            message.text = "4"
            await captcha_text_handler(update, context)

        set_captcha_passed.assert_awaited_once_with(user.id)
        self.assertNotIn(CAPTCHA_TOKEN_KEY, context.user_data)
        send_welcome_photo.assert_awaited_once()
        _, kwargs = send_welcome_photo.await_args
        menu = kwargs["reply_markup"]
        labels = [button.text for row in menu.keyboard for button in row]
        self.assertEqual(labels, [MENU_EXCHANGE, MENU_PROFILE, MENU_ABOUT, MENU_FOCUSBET, MENU_FOCUSVPN])
        context.bot.send_message.assert_not_awaited()

    async def test_start_leaves_exchange_open_as_the_last_message(self):
        user = SimpleNamespace(id=424242, username="buyer", first_name="Buyer")
        message = SimpleNamespace(text="/start", reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_user=user,
            effective_chat=SimpleNamespace(id=user.id),
            message=message,
        )
        context = SimpleNamespace(
            args=[],
            user_data={},
            bot=SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock()),
        )

        with (
            patch.dict("os.environ", {"EXCHANGE_MINIAPP_URL": "https://focuspay.org/exchange/tg"}),
            patch("handlers.start.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch("handlers.start.get_bot_user", new=AsyncMock(return_value={"captcha_passed_at": "now"})),
            patch("handlers.start.ensure_bot_user", new=AsyncMock()),
            patch("handlers.start._approve_pending_gated_joins", new=AsyncMock()),
            patch("handlers.ops_bind.maybe_handle_ops_bind", new=AsyncMock(return_value=False)),
            patch("handlers.exchange_flow.resend_active_order_prompt", new=AsyncMock(return_value=False)),
            patch("handlers.start.log_start_ref_payload", new=AsyncMock()),
            patch("services.user_referral_attribution.assign_referrer_by_token", new=AsyncMock(return_value="empty")),
            patch("handlers.start.apply_promo_from_start_payload", new=AsyncMock(return_value=False)),
            patch("handlers.start.apply_pending_ref_token_if_any", new=AsyncMock(return_value="empty")),
            patch("handlers.start.user_has_attribution", new=AsyncMock(return_value=True)),
            patch("handlers.start.get_unified_balance_stats", new=AsyncMock(return_value={"saved_rub": 0})),
            patch("services.menu.get_partner_by_telegram", new=AsyncMock(return_value=None)),
            patch("services.db.user_has_payment_active_order", new=AsyncMock(return_value=False)),
            patch("handlers.start.send_welcome_photo", new=AsyncMock()) as send_welcome_photo,
        ):
            await start_handler(update, context)

        send_welcome_photo.assert_awaited_once()
        context.bot.send_message.assert_awaited_once()
        _, kwargs = context.bot.send_message.await_args
        self.assertEqual(kwargs["text"], "Обмен в приложении")
        button = kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.web_app.url, "https://focuspay.org/exchange/tg")


if __name__ == "__main__":
    unittest.main()
