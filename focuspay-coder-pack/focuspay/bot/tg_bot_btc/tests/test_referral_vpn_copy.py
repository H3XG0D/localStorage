"""Referral copy tells people that VPN purchases pay the same ladder."""
import unittest
from unittest.mock import AsyncMock, patch

from services.ux_copy import txt_referral_cabinet


class ReferralVpnCopyTests(unittest.IsolatedAsyncioTestCase):
    def test_cabinet_mentions_vpn_ladder(self):
        text = txt_referral_cabinet(
            pct=5,
            tier_step=5,
            tier_every=5,
            tier_max=20,
            referred=0,
            paid_orders=0,
            today_rub=0,
            total_rub=0,
            balance_rub=0,
            cashback_rub=0,
            referral_rub=0,
            partner_rub=0,
            available_rub=0,
            pending_withdraw=0,
            link="https://t.me/focus",
            withdraw_footer="вывод",
        )
        self.assertIn("обменам", text)
        self.assertIn("VPN", text)
        self.assertIn("20%", text)
        self.assertIn("5 приглашённых", text)

    async def test_post_paid_followup_mentions_vpn(self):
        from services import marketing_messages

        with patch.object(
            marketing_messages, "resolve_share_links", AsyncMock(return_value={"telegram_link": "https://t.me/focus"}),
        ), patch.object(marketing_messages.runtime_settings, "user_referral_pct", return_value=5), \
             patch.object(
                 marketing_messages.runtime_settings,
                 "partner_tier_global",
                 return_value={"step_percent": 5, "every_n": 5, "max_percent": 20},
             ), \
             patch.object(marketing_messages, "cashback_progress_line", AsyncMock(return_value=None)), \
             patch.object(marketing_messages, "focus_lucky_progress_line", AsyncMock(return_value=None)):
            text = await marketing_messages.post_paid_followup_text(1)
        self.assertIn("VPN", text)
        self.assertIn("20%", text)
        self.assertIn("5%", text)
