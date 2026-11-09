from __future__ import annotations

import unittest
from unittest.mock import patch

from finance_access import (
    STAGING_FIXTURE_FINANCE_OWNER_TELEGRAM_ID,
    can_view_finance_admin,
    is_finance_owner_admin,
    is_staging_fixture_finance_owner,
)


class FinanceAccessStagingFixtureTests(unittest.TestCase):
    def test_fixture_owner_only_on_staging(self) -> None:
        with patch("finance_access.settings.environment", "staging"):
            self.assertTrue(
                is_staging_fixture_finance_owner(STAGING_FIXTURE_FINANCE_OWNER_TELEGRAM_ID)
            )
            self.assertFalse(is_staging_fixture_finance_owner(100000003))

        with patch("finance_access.settings.environment", "production"):
            self.assertFalse(
                is_staging_fixture_finance_owner(STAGING_FIXTURE_FINANCE_OWNER_TELEGRAM_ID)
            )

    def test_fixture_admin_is_finance_owner_on_staging_without_env_ids(self) -> None:
        admin = {"telegram_user_id": STAGING_FIXTURE_FINANCE_OWNER_TELEGRAM_ID}
        with patch("finance_access.settings.environment", "staging"):
            with patch("finance_access.is_finance_owner_telegram_id", return_value=False):
                self.assertTrue(is_finance_owner_admin(admin))
                self.assertTrue(can_view_finance_admin(admin))

    def test_fixture_admin_not_finance_owner_in_production(self) -> None:
        admin = {"telegram_user_id": STAGING_FIXTURE_FINANCE_OWNER_TELEGRAM_ID}
        with patch("finance_access.settings.environment", "production"):
            with patch("finance_access.is_finance_owner_telegram_id", return_value=False):
                self.assertFalse(is_finance_owner_admin(admin))
                self.assertFalse(can_view_finance_admin(admin))


if __name__ == "__main__":
    unittest.main()
