"""Wallet abstraction — lab MockWallet; exchange will implement ExchangeLedgerWallet."""
from __future__ import annotations

from typing import Protocol

import aiosqlite

from config import DB_PATH, DEFAULT_LAB_USERS
from sqlite_db import fetchone


class WalletProvider(Protocol):
    async def available(self, user_id: str) -> float: ...
    async def hold_bet(self, user_id: str, round_id: int, amount: float) -> None: ...
    async def release_win(self, user_id: str, round_id: int, amount: float) -> None: ...
    async def confirm_loss(self, user_id: str, round_id: int) -> None: ...
    async def refund_round(self, user_id: str, round_id: int) -> None: ...
    async def seed(self, user_id: str, amount: float) -> None: ...


SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_users (
    user_id TEXT PRIMARY KEY,
    balance REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS lab_holds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'held',
    UNIQUE(user_id, round_id)
);
"""


class MockWallet:
    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            for user_id in DEFAULT_LAB_USERS:
                await db.execute(
                    "INSERT OR IGNORE INTO lab_users (user_id, balance) VALUES (?, 1000)",
                    (user_id,),
                )
            await db.commit()

    async def available(self, user_id: str) -> float:
        async with aiosqlite.connect(self.db_path) as db:
            row = await fetchone(db, "SELECT balance FROM lab_users WHERE user_id = ?", (user_id,))
            if not row:
                return 0.0
            return round(max(0.0, float(row[0])), 2)

    async def hold_bet(self, user_id: str, round_id: int, amount: float) -> None:
        amount = round(float(amount), 2)
        avail = await self.available(user_id)
        if amount > avail + 0.01:
            raise ValueError("insufficient balance")

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO lab_users (user_id, balance) VALUES (?, 0)",
                (user_id,),
            )
            existing = await fetchone(
                db, "SELECT amount FROM lab_holds WHERE user_id = ? AND round_id = ?", (user_id, round_id)
            )
            if existing:
                new_amount = round(float(existing[0]) + amount, 2)
                await db.execute(
                    "UPDATE lab_holds SET amount = ? WHERE user_id = ? AND round_id = ?",
                    (new_amount, user_id, round_id),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO lab_holds (user_id, round_id, amount, status)
                    VALUES (?, ?, ?, 'held')
                    """,
                    (user_id, round_id, amount),
                )
            await db.execute(
                "UPDATE lab_users SET balance = balance - ? WHERE user_id = ?",
                (amount, user_id),
            )
            await db.commit()

    async def confirm_loss(self, user_id: str, round_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE lab_holds SET status = 'lost' WHERE user_id = ? AND round_id = ? AND status = 'held'",
                (user_id, round_id),
            )
            await db.commit()

    async def release_win(self, user_id: str, round_id: int, amount: float) -> None:
        amount = round(float(amount), 2)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE lab_holds SET status = 'won' WHERE user_id = ? AND round_id = ? AND status = 'held'",
                (user_id, round_id),
            )
            await db.execute(
                "UPDATE lab_users SET balance = balance + ? WHERE user_id = ?",
                (amount, user_id),
            )
            await db.commit()

    async def refund_round(self, user_id: str, round_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            row = await fetchone(
                db,
                "SELECT amount FROM lab_holds WHERE user_id = ? AND round_id = ? AND status = 'held'",
                (user_id, round_id),
            )
            if not row:
                return
            amount = float(row[0])
            await db.execute(
                "UPDATE lab_holds SET status = 'refunded' WHERE user_id = ? AND round_id = ?",
                (user_id, round_id),
            )
            await db.execute(
                "UPDATE lab_users SET balance = balance + ? WHERE user_id = ?",
                (amount, user_id),
            )
            await db.commit()

    async def seed(self, user_id: str, amount: float) -> None:
        amount = round(float(amount), 2)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO lab_users (user_id, balance) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance",
                (user_id, amount),
            )
            await db.commit()
