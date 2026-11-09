"""Регрессия: кнопка обмена проходит ban-gate до выбора валюты."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.exchange_flow import exchange_start
from services.menu import MENU_EXCHANGE


class ExchangeStartTests(unittest.IsolatedAsyncioTestCase):
    async def test_exchange_button_checks_ban_then_opens_currency_step(self):
        user = SimpleNamespace(id=424242, username="buyer")
        update = SimpleNamespace(
            effective_user=user,
            message=SimpleNamespace(text=MENU_EXCHANGE, reply_text=AsyncMock()),
        )
        context = SimpleNamespace(user_data={})

        with (
            patch("handlers.exchange_flow.rate_limit_ok", new=AsyncMock(return_value=True)),
            patch("services.db.is_user_banned", new=AsyncMock(return_value=(False, None, "hard"))) as is_banned,
            patch("services.user_referral_attribution.seal_referral_gate", new=AsyncMock()) as seal_referral_gate,
            patch("handlers.exchange_flow.get_active_order_by_user", new=AsyncMock(return_value=None)),
            patch("handlers.exchange_flow._ex_show_coins", new=AsyncMock()) as show_coins,
        ):
            await exchange_start(update, context)

        is_banned.assert_awaited_once_with(user.id)
        seal_referral_gate.assert_awaited_once_with(user.id)
        self.assertEqual(context.user_data["step"], "choose_currency")
        show_coins.assert_awaited_once_with(update, context, with_banner=True)


if __name__ == "__main__":
    unittest.main()
