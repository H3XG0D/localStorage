"""Тесты флагов доверия внештатников."""
import unittest

from external_exchange_trust import (
    client_trust_label,
    deal_client_label,
    deal_fields_from_row,
    effective_auto_credit,
    trust_fields_from_row,
)


class ExternalExchangerTrustTests(unittest.TestCase):
    def test_client_trust_label(self):
        self.assertEqual(client_trust_label(True), "доверенный")
        self.assertEqual(client_trust_label(False), "новый")

    def test_deal_client_label(self):
        self.assertEqual(deal_client_label(True), "новый")
        self.assertEqual(deal_client_label(False), "повторный")

    def test_deal_fields_from_row(self):
        fields = deal_fields_from_row({"client_is_new": False})
        self.assertFalse(fields["client_is_new"])
        self.assertEqual(fields["deal_client_label"], "повторный")

        default = deal_fields_from_row(None)
        self.assertTrue(default["client_is_new"])
        self.assertEqual(default["deal_client_label"], "новый")

    def test_auto_credit_blocked_for_non_trusted(self):
        self.assertFalse(effective_auto_credit(False, True))
        self.assertFalse(effective_auto_credit(False, False))
        self.assertTrue(effective_auto_credit(True, True))
        self.assertFalse(effective_auto_credit(True, False))

    def test_trust_fields_from_row(self):
        fields = trust_fields_from_row(
            {"is_trusted_client": True, "auto_credit_on_payfast": True}
        )
        self.assertTrue(fields["is_trusted_client"])
        self.assertTrue(fields["auto_credit_on_payfast"])
        self.assertEqual(fields["client_trust_label"], "доверенный")

        fields2 = trust_fields_from_row(
            {"is_trusted_client": False, "auto_credit_on_payfast": True}
        )
        self.assertFalse(fields2["auto_credit_on_payfast"])


if __name__ == "__main__":
    unittest.main()
