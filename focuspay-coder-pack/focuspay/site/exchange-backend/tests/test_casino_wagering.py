"""Регрессии wagering-lock: комиссия со ставки уменьшает плюс казино."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import casino_wagering


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


class FakeConn:
    """Минимальная модель locks и finished casino_games в памяти."""

    def __init__(self, *, settings=None, played=None):
        self.settings = settings or {}
        self.locks: list[dict] = []
        self.played = played or []
        self._next_id = 1

    async def fetchrow(self, query, *args):
        if "wager_rub" in query:
            return {"wager_rub": Decimal("0")}
        return None

    async def fetch(self, query, *args):
        if "FROM casino_settings" in query:
            return [{"key": key, "value": {"percent": value}} for key, value in self.settings.items()]
        if "FROM casino_wagering_locks" in query:
            telegram_id = args[0]
            return [lock for lock in self.locks if lock["telegram_id"] == telegram_id]
        if "FROM casino_games" in query:
            since = args[1]
            rows = []
            for index, item in enumerate(self.played, 1):
                finished_at, stake, *rest = item
                if finished_at < since:
                    continue
                rows.append({
                    "id": index,
                    "bet_rub": stake,
                    "finished_at": finished_at,
                    "commission_rate": rest[0] if rest else None,
                })
            return rows
        raise AssertionError(f"Unexpected fetch: {query}")

    async def execute(self, query, *args):
        if "INSERT INTO casino_wagering_locks" in query:
            if "crypto_credit_id" in query:
                crypto_credit_id, telegram_id, deposit, required, unlocked = args
                deal_id = None
                if any(lock.get("crypto_credit_id") == crypto_credit_id for lock in self.locks):
                    return "OK"
            else:
                deal_id, telegram_id, deposit, required, unlocked = args
                crypto_credit_id = None
                if any(lock.get("deal_id") == deal_id for lock in self.locks):
                    return "OK"
            self.locks.append({
                "id": self._next_id,
                "deal_id": deal_id,
                "crypto_credit_id": crypto_credit_id,
                "telegram_id": telegram_id,
                "deposit_rub": deposit,
                "required_commission_rub": required,
                "unlocked": unlocked,
                "created_at": NOW + timedelta(minutes=len(self.locks)),
            })
            self._next_id += 1
            return "OK"
        if "SET unlocked = TRUE" in query:
            lock_id = args[0]
            for lock in self.locks:
                if lock["id"] == lock_id:
                    lock["unlocked"] = True
            return "OK"
        raise AssertionError(f"Unexpected execute: {query}")


class WageringLockTests(unittest.IsolatedAsyncioTestCase):
    def test_deposit_plus_converts_to_stake_at_active_commission(self):
        self.assertEqual(
            casino_wagering.house_take_from_stake(Decimal("1400"), Decimal("15")),
            Decimal("210.00"),
        )
        self.assertEqual(
            casino_wagering.stake_for_house_take(Decimal("210"), Decimal("15")),
            Decimal("1400.00"),
        )

    async def test_default_percent_locks_deposit_at_21_house_take(self):
        conn = FakeConn()
        await casino_wagering.record_deposit_lock(conn, deal_id=1, telegram_id=100, deposit_rub=Decimal("1000"))
        self.assertEqual(conn.locks[0]["required_commission_rub"], Decimal("210.00"))
        self.assertEqual(await casino_wagering.locked_by_wagering(conn, 100), Decimal("1000.00"))
        progress = await casino_wagering.wagering_progress(conn, 100)
        self.assertEqual(progress["required_house_take_rub"], Decimal("210.00"))
        self.assertEqual(progress["remaining_house_take_rub"], Decimal("210.00"))
        self.assertEqual(progress["required_rub"], Decimal("1400.00"))
        self.assertEqual(progress["remaining_rub"], Decimal("1400.00"))
        self.assertEqual(progress["commission_rate_percent"], Decimal("15.00"))

    async def test_zero_percent_unlocks_immediately(self):
        conn = FakeConn(settings={"wagering_percent": 0})
        await casino_wagering.record_deposit_lock(conn, deal_id=2, telegram_id=100, deposit_rub=Decimal("1000"))
        self.assertTrue(conn.locks[0]["unlocked"])
        self.assertEqual(await casino_wagering.locked_by_wagering(conn, 100), Decimal("0.00"))

    async def test_stake_equal_to_house_take_does_not_lift_lock(self):
        conn = FakeConn(played=[(NOW + timedelta(hours=1), Decimal("210"))])
        await casino_wagering.record_deposit_lock(conn, deal_id=3, telegram_id=100, deposit_rub=Decimal("1000"))
        self.assertEqual(await casino_wagering.locked_by_wagering(conn, 100), Decimal("1000.00"))
        progress = await casino_wagering.wagering_progress(conn, 100)
        self.assertEqual(progress["done_house_take_rub"], Decimal("31.50"))
        self.assertEqual(progress["remaining_house_take_rub"], Decimal("178.50"))
        self.assertEqual(progress["remaining_rub"], Decimal("1190.00"))

    async def test_stake_that_yields_required_house_take_lifts_lock(self):
        conn = FakeConn(played=[(NOW + timedelta(hours=1), Decimal("1400"))])
        await casino_wagering.record_deposit_lock(conn, deal_id=3, telegram_id=100, deposit_rub=Decimal("1000"))
        self.assertEqual(await casino_wagering.locked_by_wagering(conn, 100), Decimal("0.00"))

    async def test_partial_house_take_progress(self):
        conn = FakeConn(played=[(NOW + timedelta(hours=1), Decimal("50"))])
        await casino_wagering.record_deposit_lock(conn, deal_id=4, telegram_id=100, deposit_rub=Decimal("1000"))
        progress = await casino_wagering.wagering_progress(conn, 100)
        self.assertEqual(progress["required_house_take_rub"], Decimal("210.00"))
        self.assertEqual(progress["done_house_take_rub"], Decimal("7.50"))
        self.assertEqual(progress["remaining_house_take_rub"], Decimal("202.50"))
        self.assertEqual(progress["done_rub"], Decimal("50.00"))
        self.assertEqual(progress["remaining_rub"], Decimal("1350.00"))

    async def test_game_snapshot_rate_is_used_for_house_take(self):
        conn = FakeConn(played=[(NOW + timedelta(hours=1), Decimal("1000"), "10")])
        await casino_wagering.record_deposit_lock(conn, deal_id=10, telegram_id=100, deposit_rub=Decimal("1000"))
        progress = await casino_wagering.wagering_progress(conn, 100)
        self.assertEqual(progress["done_house_take_rub"], Decimal("100.00"))
        self.assertEqual(progress["remaining_house_take_rub"], Decimal("110.00"))

    async def test_multiple_deposits_do_not_double_count_same_stake(self):
        conn = FakeConn(played=[(NOW + timedelta(hours=1), Decimal("1400"))])
        await casino_wagering.record_deposit_lock(conn, deal_id=5, telegram_id=100, deposit_rub=Decimal("1000"))
        await casino_wagering.record_deposit_lock(conn, deal_id=6, telegram_id=100, deposit_rub=Decimal("1000"))
        progress = await casino_wagering.wagering_progress(conn, 100)
        self.assertEqual(progress["remaining_house_take_rub"], Decimal("210.00"))
        self.assertEqual(progress["remaining_rub"], Decimal("1400.00"))
        self.assertEqual(await casino_wagering.commission_rate_for_player(conn, 100), Decimal("15"))

    async def test_commission_falls_to_five_only_after_all_locks_complete(self):
        conn = FakeConn(played=[(NOW + timedelta(hours=1), Decimal("2800"))])
        await casino_wagering.record_deposit_lock(conn, deal_id=7, telegram_id=100, deposit_rub=Decimal("1000"))
        await casino_wagering.record_deposit_lock(conn, deal_id=8, telegram_id=100, deposit_rub=Decimal("1000"))
        self.assertEqual(await casino_wagering.commission_rate_for_player(conn, 100), Decimal("5"))

    async def test_stake_before_deposit_does_not_count(self):
        conn = FakeConn(played=[(NOW - timedelta(hours=1), Decimal("5000"))])
        await casino_wagering.record_deposit_lock(conn, deal_id=9, telegram_id=100, deposit_rub=Decimal("1000"))
        self.assertEqual(await casino_wagering.locked_by_wagering(conn, 100), Decimal("1000.00"))


if __name__ == "__main__":
    unittest.main()
