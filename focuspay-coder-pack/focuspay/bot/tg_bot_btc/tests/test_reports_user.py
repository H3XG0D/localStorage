"""Access for Telegram /dash in the reports group."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services import config_rates as cr


class ReportsUserTests(unittest.TestCase):
    def test_owner_and_admin_allowed(self):
        with patch.object(cr, "TELEGRAM_ADMIN_IDS", [111, 222]), patch.object(
            cr, "is_finance_owner", return_value=True
        ):
            self.assertTrue(cr.is_reports_user(999))
        with patch.object(cr, "TELEGRAM_ADMIN_IDS", [111, 222]), patch.object(
            cr, "is_finance_owner", return_value=False
        ):
            self.assertTrue(cr.is_reports_user(111))
            self.assertFalse(cr.is_reports_user(333))
            self.assertFalse(cr.is_reports_user(0))

    def test_username_allowlist(self):
        with patch.object(cr, "TELEGRAM_ADMIN_IDS", []), patch.object(
            cr, "is_finance_owner", return_value=False
        ), patch.object(cr, "_env", return_value="boss, @other"):
            self.assertTrue(cr.is_reports_user(1, "boss"))
            self.assertTrue(cr.is_reports_user(1, "@Other"))
            self.assertFalse(cr.is_reports_user(1, "nope"))

    def test_focuspayadmin_username_can_be_allowlisted(self):
        with patch.object(cr, "TELEGRAM_ADMIN_IDS", []), patch.object(
            cr, "is_finance_owner", return_value=False
        ), patch.object(cr, "_env", return_value="focuspayadmin"):
            self.assertTrue(cr.is_reports_user(8760743763, "focuspayadmin"))


if __name__ == "__main__":
    unittest.main()
