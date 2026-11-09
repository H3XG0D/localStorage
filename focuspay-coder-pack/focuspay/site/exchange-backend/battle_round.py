"""Round lifecycle for exchange (PostgreSQL)."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from battle_config import LOCK_SECONDS, MAX_BET, MIN_BET, RAKE_PCT, ROUND_SECONDS
from battle_engine import (
    calc_bank,
    calc_odds,
    pick_winner,
    should_refund,
    split_payout,
    validate_bet,
)
from battle_models import CurrentRound, HistoryItem, MyBet, Side
from battle_wallet import ExchangeLedgerWallet
from db import get_pool


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utcnow().isoformat()


class BattleRoundManager:
    def __init__(self, wallet: ExchangeLedgerWallet | None = None) -> None:
        self.wallet = wallet or ExchangeLedgerWallet()

    async def init(self) -> None:
        await self._ensure_current_round()

    async def _ensure_current_round(self) -> int:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id FROM battle_rounds
                WHERE status IN ('open', 'locked')
                ORDER BY id DESC LIMIT 1
                """
            )
            if row:
                return int(row["id"])
        return await self.start_next_round()

    async def start_next_round(self) -> int:
        ends_at = _utcnow() + timedelta(seconds=ROUND_SECONDS)
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO battle_rounds (status, red_total, blue_total, ends_at)
                VALUES ('open', 0, 0, $1)
                RETURNING id
                """,
                ends_at,
            )
            return int(row["id"])

    def _seconds_left(self, ends_at: datetime) -> int:
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        delta = (ends_at - _utcnow()).total_seconds()
        return max(0, int(delta))

    async def get_current_for_user(self, user_id: int) -> CurrentRound:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, status, red_total, blue_total, ends_at
                FROM battle_rounds
                WHERE status IN ('open', 'locked')
                ORDER BY id DESC LIMIT 1
                """
            )
            if not row:
                await self.start_next_round()
                return await self.get_current_for_user(user_id)

            round_id = int(row["id"])
            status = row["status"]
            red_total = float(row["red_total"])
            blue_total = float(row["blue_total"])
            ends_at = row["ends_at"]
            red_pct, blue_pct = calc_odds(red_total, blue_total)

            bet_row = await conn.fetchrow(
                """
                SELECT side, SUM(amount_rub) AS total
                FROM battle_bets
                WHERE round_id = $1 AND user_id = $2
                GROUP BY side
                LIMIT 1
                """,
                round_id,
                user_id,
            )
            my_bet = None
            if bet_row:
                my_bet = MyBet(side=bet_row["side"], amount=round(float(bet_row["total"]), 2))

        balance = await self.wallet.available(str(user_id))
        return CurrentRound(
            round_id=round_id,
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

    async def place_bet(self, user_id: int, side: Side, amount: float) -> CurrentRound:
        validate_bet(amount, MIN_BET, MAX_BET)
        amount = round(float(amount), 2)

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT id, status, red_total, blue_total, ends_at
                    FROM battle_rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1
                    FOR UPDATE
                    """
                )
                if not row:
                    raise ValueError("no open round")
                round_id = int(row["id"])
                if row["status"] != "open":
                    raise ValueError("bets are locked")
                if self._seconds_left(row["ends_at"]) <= LOCK_SECONDS:
                    raise ValueError("bets are locked")

                existing = await conn.fetchval(
                    """
                    SELECT COALESCE(SUM(amount_rub), 0)::float
                    FROM battle_bets WHERE round_id = $1 AND user_id = $2
                    """,
                    round_id,
                    user_id,
                )
                user_total = float(existing or 0)
                if user_total + amount > MAX_BET:
                    raise ValueError(f"maximum bet is {MAX_BET} ₽ per round")

                bet_row = await conn.fetchrow(
                    """
                    INSERT INTO battle_bets (round_id, user_id, side, amount_rub)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (round_id, user_id, side) DO UPDATE
                    SET amount_rub = battle_bets.amount_rub + EXCLUDED.amount_rub
                    RETURNING id
                    """,
                    round_id,
                    user_id,
                    side,
                    amount,
                )
                hold_id = await conn.fetchval("SELECT nextval('battle_hold_ref_seq')")
                if side == "red":
                    await conn.execute(
                        "UPDATE battle_rounds SET red_total = red_total + $1 WHERE id = $2",
                        amount,
                        round_id,
                    )
                else:
                    await conn.execute(
                        "UPDATE battle_rounds SET blue_total = blue_total + $1 WHERE id = $2",
                        amount,
                        round_id,
                    )

        await self.wallet.hold_bet(str(user_id), round_id, amount, hold_id)
        return await self.get_current_for_user(user_id)

    async def lock_if_needed(self) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, ends_at FROM battle_rounds WHERE status = 'open'"
            )
            for row in rows:
                if self._seconds_left(row["ends_at"]) <= LOCK_SECONDS:
                    await conn.execute(
                        "UPDATE battle_rounds SET status = 'locked' WHERE id = $1",
                        row["id"],
                    )

    async def resolve_due_rounds(self) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, red_total, blue_total, ends_at
                FROM battle_rounds WHERE status IN ('open', 'locked')
                """
            )
            due = [
                (int(r["id"]), float(r["red_total"]), float(r["blue_total"]))
                for r in rows
                if self._seconds_left(r["ends_at"]) <= 0
            ]

        for round_id, red_total, blue_total in due:
            await self._resolve_round(round_id, red_total, blue_total)
            await self.start_next_round()

    async def _resolve_round(self, round_id: int, red_total: float, blue_total: float) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            bets = await conn.fetch(
                "SELECT user_id, side, amount_rub FROM battle_bets WHERE round_id = $1",
                round_id,
            )

        if should_refund(red_total, blue_total):
            winner = None
            status = "cancelled"
            for row in bets:
                await self.wallet.refund_round(str(int(row["user_id"])), round_id)
        else:
            winner = pick_winner(red_total, blue_total, secrets.randbelow(10**9) / 10**9)
            status = "resolved"
            winner_bets = [
                (str(int(row["user_id"])), float(row["amount_rub"]))
                for row in bets
                if row["side"] == winner
            ]
            payouts = split_payout(winner_bets, red_total, blue_total, RAKE_PCT)
            bet_users = {int(row["user_id"]) for row in bets}
            for uid in bet_users:
                key = str(uid)
                if key in payouts:
                    await self.wallet.release_win(key, round_id, payouts[key])
                else:
                    await self.wallet.confirm_loss(key, round_id)

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE battle_rounds
                SET status = $1, winner = $2, resolved_at = NOW()
                WHERE id = $3
                """,
                status,
                winner,
                round_id,
            )

    async def get_history(self, limit: int = 20) -> list[HistoryItem]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, winner, red_total, blue_total, resolved_at
                FROM battle_rounds
                WHERE status IN ('resolved', 'cancelled')
                ORDER BY id DESC LIMIT $1
                """,
                limit,
            )
        return [
            HistoryItem(
                round_id=int(r["id"]),
                winner=r["winner"],
                red_total=round(float(r["red_total"]), 2),
                blue_total=round(float(r["blue_total"]), 2),
                ended_at=r["resolved_at"].isoformat() if r["resolved_at"] else "",
            )
            for r in rows
        ]
