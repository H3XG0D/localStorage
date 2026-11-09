"""Смена адреса пополнения: старый остаётся, текущий один."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import store
from receive_address import ensure_receive_address, needs_fresh_address

OLD = "bc1qusedaddress000000000000000000000"
NEW = "bc1qfreshaddress00000000000000000000"
LEGACY = "bc1qlegacyaddress000000000000000000"


class NeedsFreshTests(unittest.TestCase):
    def test_any_received_amount_asks_for_the_next_address(self) -> None:
        self.assertFalse(needs_fresh_address(0))
        self.assertFalse(needs_fresh_address(0.0))
        self.assertTrue(needs_fresh_address(0.00000001))
        self.assertFalse(needs_fresh_address("нет"))  # type: ignore[arg-type]


class DepositStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.live = self.root / "live"
        self.live.mkdir()
        store._conn = None
        self.path_patch = patch.object(store, "_db_path", return_value=self.live / "signer.sqlite3")
        self.path_patch.start()
        with patch.object(
            store,
            "restore_empty_tables_from_backup",
            return_value={"deposits": 0, "payouts": 0},
        ):
            store.init()

    def tearDown(self) -> None:
        if store._conn is not None:
            store._conn.close()
            store._conn = None
        self.path_patch.stop()
        self.tmp.cleanup()

    def test_first_address_stays_until_rotated(self) -> None:
        first = store.save_deposit_address("btc", OLD)
        second = store.save_deposit_address("btc", NEW)
        self.assertEqual(first, OLD)
        self.assertEqual(second, OLD)
        self.assertEqual(store.deposit_address("btc"), OLD)

    def test_rotate_keeps_the_previous_address(self) -> None:
        store.save_deposit_address("btc", OLD)
        store.save_deposit_address("ltc", "ltc1qotheraddress0000000000000000000")
        current = store.install_deposit_address("btc", NEW)
        self.assertEqual(current, NEW)
        self.assertEqual(store.deposit_address("btc"), NEW)
        self.assertEqual(store.deposit_address("ltc"), "ltc1qotheraddress0000000000000000000")
        rows = store.list_deposit_addresses("btc")
        self.assertEqual([row["address"] for row in rows if row["current"]], [NEW])
        self.assertEqual([row["address"] for row in rows if not row["current"]], [OLD])

    def test_legacy_table_migrates_as_the_current_address(self) -> None:
        if store._conn is not None:
            store._conn.close()
            store._conn = None
        path = self.live / "signer.sqlite3"
        path.unlink()
        raw = sqlite3.connect(path)
        raw.execute(
            """
            CREATE TABLE deposit_addresses (
                coin TEXT PRIMARY KEY,
                address TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        raw.execute("INSERT INTO deposit_addresses VALUES ('btc', ?, 5)", (LEGACY,))
        raw.commit()
        raw.close()
        with patch.object(
            store,
            "restore_empty_tables_from_backup",
            return_value={"deposits": 0, "payouts": 0},
        ):
            store.init()
        self.assertEqual(store.deposit_address("btc"), LEGACY)
        store.install_deposit_address("btc", NEW)
        self.assertEqual(store.deposit_address("btc"), NEW)
        self.assertEqual(len(store.list_deposit_addresses("btc")), 2)

    def test_restore_keeps_one_current_from_history(self) -> None:
        backup = self.root / "backups" / "new"
        backup.mkdir(parents=True)
        conn = sqlite3.connect(backup / "signer.sqlite3")
        conn.execute(
            """
            CREATE TABLE deposit_addresses (
                coin TEXT NOT NULL,
                address TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                retired_at INTEGER,
                PRIMARY KEY (coin, address)
            )
            """
        )
        conn.execute(
            "INSERT INTO deposit_addresses VALUES ('btc', ?, 1, 9)",
            (OLD,),
        )
        conn.execute(
            "INSERT INTO deposit_addresses VALUES ('btc', ?, 2, NULL)",
            (NEW,),
        )
        conn.commit()
        conn.close()
        copied = store.restore_empty_tables_from_backup(self.root / "backups")
        self.assertEqual(copied["deposits"], 2)
        self.assertEqual(store.deposit_address("btc"), NEW)
        self.assertEqual(len(store.list_deposit_addresses("btc")), 2)


class EnsureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
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

    def tearDown(self) -> None:
        if store._conn is not None:
            store._conn.close()
            store._conn = None
        self.path_patch.stop()
        self.tmp.cleanup()

    async def test_unused_address_stays(self) -> None:
        store.save_deposit_address("btc", OLD)
        minted = AsyncMock(side_effect=AssertionError("should not mint"))
        with (
            patch("receive_address.wallet_rpc.address_received", new=AsyncMock(return_value=0)),
            patch("receive_address.wallet_rpc.new_deposit_address", minted),
        ):
            addr, changed = await ensure_receive_address("btc")
        self.assertEqual(addr, OLD)
        self.assertFalse(changed)
        minted.assert_not_called()

    async def test_used_address_moves_to_the_next_one(self) -> None:
        store.save_deposit_address("btc", OLD)
        with (
            patch("receive_address.wallet_rpc.address_received", new=AsyncMock(return_value=0.5)),
            patch("receive_address.wallet_rpc.new_deposit_address", new=AsyncMock(return_value=NEW)),
        ):
            addr, changed = await ensure_receive_address("btc")
        self.assertTrue(changed)
        self.assertEqual(addr, NEW)
        self.assertEqual(store.deposit_address("btc"), NEW)
        retired = [row["address"] for row in store.list_deposit_addresses("btc") if not row["current"]]
        self.assertEqual(retired, [OLD])

    async def test_force_rotates_before_coins_arrive(self) -> None:
        store.save_deposit_address("btc", OLD)
        received = AsyncMock(side_effect=AssertionError("force skips the received check"))
        with (
            patch("receive_address.wallet_rpc.address_received", received),
            patch("receive_address.wallet_rpc.new_deposit_address", new=AsyncMock(return_value=NEW)),
        ):
            addr, changed = await ensure_receive_address("btc", force=True)
        self.assertTrue(changed)
        self.assertEqual(addr, NEW)
        received.assert_not_called()


if __name__ == "__main__":
    unittest.main()
