"""Пустой sqlite подписанта поднимает адреса из свежей копии и не затирает живые выплаты."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import store


def _backup(path: Path, *, address: str, request_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE deposit_addresses (
            coin TEXT PRIMARY KEY, address TEXT NOT NULL, created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO deposit_addresses VALUES ('btc', ?, 1)",
        (address,),
    )
    conn.execute(
        """
        CREATE TABLE payouts (
            request_id TEXT PRIMARY KEY,
            coin TEXT NOT NULL,
            address TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL,
            txid TEXT,
            reason TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO payouts VALUES (?, 'btc', ?, 0.1, 'sent', 'abc', NULL, 1, 1)
        """,
        (request_id, address),
    )
    conn.commit()
    conn.close()


class RestoreTests(unittest.TestCase):
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

    def test_empty_database_takes_the_newest_backup(self) -> None:
        old = self.root / "backups" / "old"
        new = self.root / "backups" / "new"
        _backup(old / "signer.sqlite3", address="bc1qold", request_id="order:old")
        _backup(new / "signer.sqlite3", address="bc1qnew", request_id="order:new")
        # newest by mtime
        (new / "signer.sqlite3").touch()
        copied = store.restore_empty_tables_from_backup(self.root / "backups")
        self.assertEqual(copied["deposits"], 1)
        self.assertEqual(copied["payouts"], 1)
        self.assertEqual(store.deposit_address("btc"), "bc1qnew")
        count = store._db().execute("SELECT COUNT(*) FROM payouts").fetchone()[0]
        self.assertEqual(count, 1)
        kept = store._db().execute("SELECT request_id FROM payouts").fetchone()[0]
        self.assertEqual(kept, "order:new")

    def test_live_payouts_are_not_replaced_by_an_older_copy(self) -> None:
        _backup(
            self.root / "backups" / "t" / "signer.sqlite3",
            address="bc1qfrombackup",
            request_id="order:backup",
        )
        store._db().execute(
            """
            INSERT INTO payouts (
                request_id, coin, address, amount, status, created_at, updated_at
            ) VALUES ('order:live', 'btc', 'bc1qlive', 0.2, 'sent', 2, 2)
            """
        )
        copied = store.restore_empty_tables_from_backup(self.root / "backups")
        self.assertEqual(copied["payouts"], 0)
        self.assertEqual(copied["deposits"], 1)
        ids = [
            row[0]
            for row in store._db().execute("SELECT request_id FROM payouts").fetchall()
        ]
        self.assertEqual(ids, ["order:live"])
        self.assertEqual(store.deposit_address("btc"), "bc1qfrombackup")


if __name__ == "__main__":
    unittest.main()
