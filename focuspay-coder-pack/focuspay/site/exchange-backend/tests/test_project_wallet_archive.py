"""История адресов не удаляется при смене текущего."""
from __future__ import annotations

import unittest

from project_wallet_archive import (
    _clean,
    addresses_from_signer_payload,
    remember_retired_addresses,
    remember_seen_addresses,
)


class CleanTests(unittest.TestCase):
    def test_rejects_unknown_source_and_short_address(self):
        self.assertIsNone(_clean("btc", "bc1short", "hot_wallet"))
        self.assertIsNone(_clean("btc", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "other"))
        self.assertEqual(
            _clean("BTC", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "hot_wallet"),
            ("btc", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "hot_wallet"),
        )


class RememberTests(unittest.IsolatedAsyncioTestCase):
    async def test_replace_retires_previous_and_never_deletes(self):
        class Conn:
            def __init__(self) -> None:
                self.sql: list[str] = []

            async def execute(self, sql, *args):
                self.sql.append(" ".join(sql.split()))
                return "OK"

        conn = Conn()
        written = await remember_seen_addresses(
            conn,
            [("btc", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "hot_wallet")],
        )
        self.assertEqual(written, 1)
        blob = "\n".join(conn.sql)
        self.assertNotIn("DELETE", blob.upper())
        self.assertIn("SET retired_at = now()", blob)
        self.assertIn("INSERT INTO project_wallet_addresses", blob)
        self.assertIn("ON CONFLICT", blob)

    async def test_retired_row_is_not_promoted_back(self) -> None:
        class Conn:
            def __init__(self) -> None:
                self.sql: list[str] = []

            async def execute(self, sql, *args):
                self.sql.append(" ".join(sql.split()))
                return "OK"

        conn = Conn()
        written = await remember_retired_addresses(
            conn,
            [("btc", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "hot_wallet")],
        )
        self.assertEqual(written, 1)
        blob = "\n".join(conn.sql)
        self.assertIn("DO NOTHING", blob)
        self.assertNotIn("retired_at = NULL", blob)


class SignerPayloadTests(unittest.TestCase):
    def test_known_list_includes_retired_addresses(self) -> None:
        addrs = addresses_from_signer_payload(
            {
                "addresses": {"btc": "bc1qnewaddress000000000000000000000"},
                "known": [
                    {"coin": "btc", "address": "bc1qoldaddress000000000000000000000", "current": False},
                    {"coin": "btc", "address": "bc1qnewaddress000000000000000000000", "current": True},
                ],
            }
        )
        self.assertEqual(
            addrs,
            [
                "bc1qoldaddress000000000000000000000",
                "bc1qnewaddress000000000000000000000",
            ],
        )

    def test_old_payload_without_history_uses_current_only(self) -> None:
        addrs = addresses_from_signer_payload(
            {"addresses": {"btc": "bc1qonlyaddress00000000000000000000", "ltc": None}}
        )
        self.assertEqual(addrs, ["bc1qonlyaddress00000000000000000000"])


if __name__ == "__main__":
    unittest.main()
