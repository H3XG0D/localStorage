"""Адрес казино живёт в том же кошельке, но не занимает слот текущего адреса дома."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import store
import wallet_rpc
from wallet_rpc import CASINO_DEPOSIT_LABEL, HOUSE_DEPOSIT_LABEL, group_confirmed_incoming

HOUSE = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
CLIENT = "bc1qclientaddress000000000000000000000000000"
TX = "ab" * 32


class GroupIncomingTests(unittest.TestCase):
    def test_sums_confirmed_outputs_for_one_address(self) -> None:
        items = group_confirmed_incoming(
            [
                {"txid": TX, "address": CLIENT, "amount": 0.01, "confirmations": 2},
                {"txid": TX, "address": CLIENT, "amount": 0.02, "confirmations": 3},
                {"txid": TX, "address": HOUSE, "amount": 1, "confirmations": 5},
                {"txid": "cd" * 32, "address": CLIENT, "amount": 0.5, "confirmations": 0},
            ],
            [CLIENT],
        )
        self.assertEqual(
            items,
            [{"txid": TX, "address": CLIENT, "amount": "0.03000000", "confirmations": 2}],
        )

    def test_zero_conf_stays_out(self) -> None:
        self.assertEqual(
            group_confirmed_incoming(
                [{"txid": TX, "address": CLIENT, "amount": 0.1, "confirmations": 0}],
                [CLIENT],
            ),
            [],
        )


class ReceiveAddressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.live = Path(self.tmp.name)
        store._conn = None
        self.path_patch = patch.object(store, "_db_path", return_value=self.live / "signer.sqlite3")
        self.path_patch.start()
        with patch.object(
            store,
            "restore_empty_tables_from_backup",
            return_value={"deposits": 0, "payouts": 0},
        ):
            store.init()
        store.save_deposit_address("btc", HOUSE)

    async def asyncTearDown(self) -> None:
        if store._conn is not None:
            store._conn.close()
            store._conn = None
        self.path_patch.stop()
        self.tmp.cleanup()

    async def test_casino_address_does_not_replace_the_house_address(self) -> None:
        import main

        class Request:
            async def body(self):
                return b'{"coin":"btc"}'

        minted = AsyncMock(return_value=CLIENT)
        with patch.object(main, "_verify_hmac"), patch.object(main, "_audit"), patch.object(
            wallet_rpc, "_rpc", new=AsyncMock(return_value=CLIENT)
        ), patch.object(main, "new_labeled_address", minted):
            out = await main.receive_address(Request())
        self.assertEqual(out["address"], CLIENT)
        self.assertEqual(out["label"], CASINO_DEPOSIT_LABEL)
        self.assertEqual(store.deposit_address("btc"), HOUSE)
        minted.assert_awaited_once_with("btc", CASINO_DEPOSIT_LABEL)

    async def test_labeled_mint_asks_the_node_and_skips_the_house_slot(self) -> None:
        rpc = AsyncMock(return_value=CLIENT)
        with patch.object(wallet_rpc, "_rpc", new=rpc):
            addr = await wallet_rpc.new_labeled_address("btc", CASINO_DEPOSIT_LABEL)
        self.assertEqual(addr, CLIENT)
        rpc.assert_awaited_once_with("btc", "getnewaddress", [CASINO_DEPOSIT_LABEL, "bech32"])
        self.assertEqual(store.deposit_address("btc"), HOUSE)

    async def test_house_rotation_still_moves_only_the_current_address(self) -> None:
        from receive_address import ensure_receive_address

        fresh = "bc1qfreshaddress00000000000000000000000000"
        with (
            patch("receive_address.wallet_rpc.address_received", new=AsyncMock(return_value=0.5)),
            patch("receive_address.wallet_rpc.new_deposit_address", new=AsyncMock(return_value=fresh)),
        ):
            addr, changed = await ensure_receive_address("btc")
        self.assertTrue(changed)
        self.assertEqual(addr, fresh)
        self.assertEqual(store.deposit_address("btc"), fresh)
        self.assertNotEqual(HOUSE_DEPOSIT_LABEL, CASINO_DEPOSIT_LABEL)


if __name__ == "__main__":
    unittest.main()
