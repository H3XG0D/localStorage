"""Тесты кабинета внештатника: URL, credentials, account fields."""
from __future__ import annotations

import unittest

from external_exchanger_accounts import (
    CLERK_ROLE,
    EXCHANGER_LOGIN_PATH,
    OWNER_ROLE,
    account_fields,
    account_public_dict,
    account_role,
    credentials_response,
    exchanger_account_to_dict,
    exchanger_login_url,
    is_owner_account,
)


class ExchangerPortalTests(unittest.TestCase):
    def test_login_path(self):
        self.assertEqual(EXCHANGER_LOGIN_PATH, "/exchanger/login")

    def test_login_url(self):
        url = exchanger_login_url("https://focuspay.org")
        self.assertEqual(url, "https://focuspay.org/exchanger/login")

    def test_credentials_response(self):
        out = credentials_response("kanglo", "secret123")
        self.assertEqual(out["username"], "kanglo")
        self.assertEqual(out["password"], "secret123")
        self.assertEqual(out["role"], OWNER_ROLE)
        self.assertEqual(out["login_path"], "/exchanger/login")
        self.assertTrue(out["login_url"].endswith("/exchanger/login"))

    def test_clerk_credentials_role(self):
        out = credentials_response("kassa", "secret123", role=CLERK_ROLE)
        self.assertEqual(out["role"], CLERK_ROLE)

    def test_account_fields_without_account(self):
        out = account_fields(None)
        self.assertFalse(out["has_account"])
        self.assertIsNone(out["account_username"])
        self.assertEqual(out["login_path"], "/exchanger/login")

    def test_account_fields_with_account(self):
        out = account_fields({"username": "inn_kanglo"})
        self.assertTrue(out["has_account"])
        self.assertEqual(out["account_username"], "inn_kanglo")

    def test_exchanger_account_to_dict(self):
        row = {
            "id": 1,
            "username": "kanglo",
            "external_exchanger_id": 5,
            "exchanger_name": "кангло",
        }
        out = exchanger_account_to_dict(row)
        self.assertEqual(out["id"], 1)
        self.assertEqual(out["exchanger_id"], 5)
        self.assertEqual(out["exchanger_name"], "кангло")
        self.assertEqual(out["role"], OWNER_ROLE)
        self.assertTrue(out["is_owner"])
        self.assertFalse(out["totp_enabled"])

    def test_legacy_row_is_owner(self):
        self.assertEqual(account_role({}), OWNER_ROLE)
        self.assertTrue(is_owner_account({"username": "x"}))
        self.assertFalse(is_owner_account({"role": CLERK_ROLE}))

    def test_clerk_account_to_dict(self):
        out = exchanger_account_to_dict(
            {
                "id": 2,
                "username": "kassa",
                "external_exchanger_id": 5,
                "exchanger_name": "кангло",
                "role": "clerk",
                "totp_enabled": True,
            }
        )
        self.assertEqual(out["role"], CLERK_ROLE)
        self.assertFalse(out["is_owner"])
        self.assertTrue(out["totp_enabled"])

    def test_account_public_dict_strips_secrets(self):
        out = account_public_dict(
            {
                "id": 3,
                "username": "kassa",
                "role": "clerk",
                "label": "ночь",
                "is_active": True,
                "totp_enabled": False,
                "totp_secret": "SHOULD_NOT_LEAK",
                "password_hash": "hash",
            }
        )
        self.assertEqual(out["username"], "kassa")
        self.assertEqual(out["label"], "ночь")
        self.assertNotIn("totp_secret", out)
        self.assertNotIn("password_hash", out)


if __name__ == "__main__":
    unittest.main()
