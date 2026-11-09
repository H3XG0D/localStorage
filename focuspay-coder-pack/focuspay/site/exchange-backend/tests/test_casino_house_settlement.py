"""House game_settlement helper: ledger + balance, idempotent, no silent UPDATE."""
from __future__ import annotations

from decimal import Decimal
import unittest

from casino_finance import credit_house_game_settlement, money


class _HouseConn:
    def __init__(self):
        self.balance = Decimal("1000.00")
        self.reserved = Decimal("0.00")
        self.ledger: dict[str, Decimal] = {}
        self.queries: list[str] = []

    async def fetchrow(self, query, *args):
        self.queries.append(query)
        sql = " ".join(query.split())
        if "FROM casino_house_ledger WHERE entry_key" in sql and "INSERT" not in sql:
            amount = self.ledger.get(args[0])
            return None if amount is None else {"amount_rub": amount}
        if sql.strip().startswith("SELECT id, balance_rub") or "SELECT id, balance_rub FROM casino_house_accounts" in sql:
            return {"id": 1, "balance_rub": self.balance}
        if "UPDATE casino_house_accounts" in sql:
            delta = money(args[0])
            nxt = money(self.balance + delta)
            if nxt < 0:
                return None
            self.balance = nxt
            return {"id": 1, "balance_rub": self.balance}
        if "INSERT INTO casino_house_ledger" in sql:
            entry_key = args[1]
            amount = money(args[2])
            if entry_key in self.ledger:
                return None
            self.ledger[entry_key] = amount
            return {"id": len(self.ledger)}
        raise AssertionError(query)


class CreditHouseGameSettlementTests(unittest.IsolatedAsyncioTestCase):
    async def test_credits_balance_and_writes_ledger(self):
        conn = _HouseConn()
        await credit_house_game_settlement(
            conn, amount_rub=Decimal("12.50"), entry_key="jackpot-rake-abc", reason="rake"
        )
        self.assertEqual(conn.balance, Decimal("1012.50"))
        self.assertEqual(conn.ledger["jackpot-rake-abc"], Decimal("12.50"))
        self.assertTrue(any("game_settlement" in q for q in conn.queries))

    async def test_idempotent_replay_does_not_double_credit(self):
        conn = _HouseConn()
        await credit_house_game_settlement(
            conn, amount_rub=Decimal("5"), entry_key="room-rake-1", reason="rake"
        )
        await credit_house_game_settlement(
            conn, amount_rub=Decimal("5"), entry_key="room-rake-1", reason="rake"
        )
        self.assertEqual(conn.balance, Decimal("1005.00"))
        self.assertEqual(len(conn.ledger), 1)

    async def test_conflict_on_different_amount(self):
        conn = _HouseConn()
        await credit_house_game_settlement(
            conn, amount_rub=Decimal("5"), entry_key="k", reason="rake"
        )
        with self.assertRaises(RuntimeError):
            await credit_house_game_settlement(
                conn, amount_rub=Decimal("7"), entry_key="k", reason="rake"
            )

    async def test_zero_skipped_unless_allowed(self):
        conn = _HouseConn()
        await credit_house_game_settlement(
            conn, amount_rub=Decimal("0"), entry_key="zero", reason="rake"
        )
        self.assertEqual(conn.ledger, {})
        await credit_house_game_settlement(
            conn, amount_rub=Decimal("0"), entry_key="zero", reason="rake", allow_zero=True
        )
        self.assertEqual(conn.ledger["zero"], Decimal("0.00"))
        self.assertEqual(conn.balance, Decimal("1000.00"))


class CreditHouseGameSettlementImportTests(unittest.TestCase):
    def test_rooms_and_jackpot_call_the_helper(self):
        import inspect
        import casino_fixed_rooms
        import casino_jackpot

        self.assertIn("credit_house_game_settlement", inspect.getsource(casino_jackpot._credit_house))
        self.assertIn("credit_house_game_settlement", inspect.getsource(casino_fixed_rooms._credit_house))
        self.assertIn("room-rake-", inspect.getsource(casino_fixed_rooms._lock_and_settle))
        self.assertIn("room-bot-consume-", inspect.getsource(casino_fixed_rooms._house_release))
