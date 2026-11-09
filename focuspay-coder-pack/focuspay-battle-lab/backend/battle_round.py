"""Round lifecycle: 60s rounds, T-3 lock, resolve, payouts."""
from __future__ import annotations

import random
from datetime import datetime, timedelta

import aiosqlite

from battle_engine import (
    calc_bank,
    calc_odds,
    pick_winner,
    should_refund,
    split_payout,
    validate_bet,
)
from config import LOCK_SECONDS, MAX_BET, MIN_BET, RAKE_PCT, ROUND_SECONDS
from models import BATTLE_SCHEMA, CurrentRound, HistoryItem, MyBet, Side, iso_now
from sqlite_db import fetchall, fetchone
from wallet import WalletProvider


class BattleRoundManager:
    def __init__(self, wallet: WalletProvider, db_path: str) -> None:
        self.wallet = wallet
        self.db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(BATTLE_SCHEMA)
            await db.commit()
        await self._ensure_current_round()

    async def _ensure_current_round(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            row = await fetchone(
                db,
                "SELECT id FROM battle_rounds WHERE status IN ('open', 'locked') ORDER BY id DESC LIMIT 1",
            )
            if row:
                return int(row[0])
        return await self.start_next_round()

    async def start_next_round(self) -> int:
        ends_at = (datetime.utcnow() + timedelta(seconds=ROUND_SECONDS)).isoformat() + "Z"
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                INSERT INTO battle_rounds (status, red_total, blue_total, ends_at)
                VALUES ('open', 0, 0, ?)
                """,
                (ends_at,),
            )
            await db.commit()
            return int(cur.lastrowid)

    def _seconds_left(self, ends_at: str) -> int:
        end = datetime.fromisoformat(ends_at.replace("Z", ""))
        delta = (end - datetime.utcnow()).total_seconds()
        return max(0, int(delta))

    async def get_current_for_user(self, user_id: str) -> CurrentRound:
        async with aiosqlite.connect(self.db_path) as db:
            row = await fetchone(
                db,
                """
                SELECT id, status, red_total, blue_total, ends_at
                FROM battle_rounds
                WHERE status IN ('open', 'locked')
                ORDER BY id DESC LIMIT 1
                """,
            )
            if not row:
                await self.start_next_round()
                return await self.get_current_for_user(user_id)

            round_id, status, red_total, blue_total, ends_at = row
            red_total = float(red_total)
            blue_total = float(blue_total)
            red_pct, blue_pct = calc_odds(red_total, blue_total)

            bet_rows = await fetchall(
                db,
                """
                SELECT side, SUM(amount_rub) FROM battle_bets
                WHERE round_id = ? AND user_id = ?
                GROUP BY side
                """,
                (round_id, user_id),
            )
            my_bet = None
            if bet_rows:
                side, amount = bet_rows[0]
                my_bet = MyBet(side=side, amount=round(float(amount), 2))

        balance = await self.wallet.available(user_id)
        return CurrentRound(
            round_id=int(round_id),
            seconds_left=self._seconds_left(ends_at),
            red_total=round(red_total, 2),
            blue_total=round(blue_total, 2),
            red_pct=round(red_pct * 100, 1),
            blue_pct=round(blue_pct * 100, 1),
            bank=calc_bank(red_total, blue_total),
            status=status,
            my_bet=my_bet,
            balance_available=balance,
        )

    async def place_bet(self, user_id: str, side: Side, amount: float) -> CurrentRound:
        validate_bet(amount, MIN_BET, MAX_BET)
        amount = round(float(amount), 2)

        async with aiosqlite.connect(self.db_path) as db:
            row = await fetchone(
                db,
                """
                SELECT id, status, red_total, blue_total, ends_at
                FROM battle_rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1
                """,
            )
            if not row:
                raise ValueError("no open round")
            round_id, status, red_total, blue_total, ends_at = row
            if status != "open":
                raise ValueError("bets are locked")
            if self._seconds_left(ends_at) <= LOCK_SECONDS:
                raise ValueError("bets are locked")

            existing = await fetchone(
                db,
                "SELECT COALESCE(SUM(amount_rub), 0) FROM battle_bets WHERE round_id = ? AND user_id = ?",
                (round_id, user_id),
            )
            user_total = float(existing[0] if existing else 0)
            if user_total + amount > MAX_BET:
                raise ValueError(f"maximum bet is {MAX_BET} ₽ per round")

        await self.wallet.hold_bet(user_id, int(round_id), amount)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO battle_bets (round_id, user_id, side, amount_rub)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(round_id, user_id, side) DO UPDATE SET amount_rub = amount_rub + excluded.amount_rub
                """,
                (round_id, user_id, side, amount),
            )
            col = "red_total" if side == "red" else "blue_total"
            await db.execute(
                f"UPDATE battle_rounds SET {col} = {col} + ? WHERE id = ?",
                (amount, round_id),
            )
            await db.commit()

        return await self.get_current_for_user(user_id)

    async def lock_if_needed(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            rows = await fetchall(db, "SELECT id, ends_at FROM battle_rounds WHERE status = 'open'")
            for round_id, ends_at in rows:
                if self._seconds_left(ends_at) <= LOCK_SECONDS:
                    await db.execute(
                        "UPDATE battle_rounds SET status = 'locked' WHERE id = ?",
                        (round_id,),
                    )
            await db.commit()

    async def resolve_due_rounds(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            rows = await fetchall(
                db,
                "SELECT id, red_total, blue_total, ends_at FROM battle_rounds WHERE status IN ('open', 'locked')",
            )
            due = [
                (int(r[0]), float(r[1]), float(r[2]))
                for r in rows
                if self._seconds_left(r[3]) <= 0
            ]

        for round_id, red_total, blue_total in due:
            await self._resolve_round(round_id, red_total, blue_total)
            await self.start_next_round()

    async def _resolve_round(self, round_id: int, red_total: float, blue_total: float) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            bets = await fetchall(
                db,
                "SELECT user_id, side, amount_rub FROM battle_bets WHERE round_id = ?",
                (round_id,),
            )

        if should_refund(red_total, blue_total):
            winner = None
            status = "cancelled"
            for user_id, _, _ in bets:
                await self.wallet.refund_round(user_id, round_id)
        else:
            winner = pick_winner(red_total, blue_total, random.random())
            status = "resolved"
            winner_bets = [
                (user_id, float(amount))
                for user_id, side, amount in bets
                if side == winner
            ]
            payouts = split_payout(winner_bets, red_total, blue_total, RAKE_PCT)

            bet_users = {user_id for user_id, _, _ in bets}
            for user_id in bet_users:
                if user_id in payouts:
                    await self.wallet.release_win(user_id, round_id, payouts[user_id])
                else:
                    await self.wallet.confirm_loss(user_id, round_id)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE battle_rounds
                SET status = ?, winner = ?, resolved_at = ?
                WHERE id = ?
                """,
                (status, winner, iso_now(), round_id),
            )
            await db.commit()

    async def get_history(self, limit: int = 20) -> list[HistoryItem]:
        async with aiosqlite.connect(self.db_path) as db:
            rows = await fetchall(
                db,
                """
                SELECT id, winner, red_total, blue_total, resolved_at
                FROM battle_rounds
                WHERE status IN ('resolved', 'cancelled')
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            )
        return [
            HistoryItem(
                round_id=int(r[0]),
                winner=r[1],
                red_total=round(float(r[2]), 2),
                blue_total=round(float(r[3]), 2),
                ended_at=r[4] or "",
            )
            for r in rows
        ]
