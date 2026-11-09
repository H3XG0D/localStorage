"""FocusVPN entry in the FocusPay bot: text, progress, link."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services import focusvpn_link
from services.menu import MENU_FOCUSVPN


class FocusVpnLinkTests(unittest.TestCase):
    def test_progress_text_until_gate(self):
        text = focusvpn_link.focusvpn_text(3, 10)
        self.assertIn("▰▰▰▱▱▱▱▱▱▱ 3 из 10", text)
        self.assertIn("осталось 7", text)
        self.assertIn("Пробный период", text)
        self.assertIn("либо 10 обменов, либо 30 приглашённых", text)

    def test_open_after_gate(self):
        self.assertIn("уже открыты", focusvpn_link.focusvpn_text(12, 10))
        self.assertIn("уже открыты", focusvpn_link.focusvpn_text(0, 0))
        self.assertIn("уже открыты", focusvpn_link.focusvpn_text(0, 10, 30, 30))
        self.assertIn("уже открыты", focusvpn_link.focusvpn_text(0, 10, 0, 30, trusted=True))
        self.assertTrue(focusvpn_link.trusted_from_setting("[7, 8]", 7))
        self.assertFalse(focusvpn_link.trusted_from_setting("[7]", 9))
        self.assertFalse(focusvpn_link.trusted_from_setting("nope", 7))

    def test_button_links_to_vpn_bot(self):
        with patch.dict("os.environ", {"VPN_BOT_USERNAME": "@my_vpn_bot"}):
            kb = focusvpn_link.focusvpn_keyboard()
        url = kb.inline_keyboard[0][0].url
        self.assertEqual(url, "https://t.me/my_vpn_bot?start=fp")

    def test_menu_label(self):
        self.assertEqual(MENU_FOCUSVPN, "FocusVPN")


if __name__ == "__main__":
    unittest.main()
