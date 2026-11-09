"""Криптопополнение казино: один txid, минимум продажи, веб-id, без фиатного рельса."""
from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

import casino_crypto_deposit
from casino_payout_rail import RAIL_FIAT

ROOT = Path(__file__).resolve().parents[1]
TX = "ab" * 32
ADDRESS = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"


class Tx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class Conn:
    def __init__(self):
        self.credits: list[dict] = []
        self.ledger: list[dict] = []
        self.locks: list[dict] = []
        self._next_id = 1

    def transaction(self):
        return Tx()

    async def execute(self, query, *args):
        if "pg_advisory_xact_lock" in query:
            return "OK"
        if "INSERT INTO casino_wagering_locks" in query and "crypto_credit_id" in query:
            crypto_credit_id, telegram_id, deposit, required, unlocked = args
            self.locks.append({
                "crypto_credit_id": crypto_credit_id,
                "telegram_id": telegram_id,
                "deposit_rub": deposit,
                "required_commission_rub": required,
                "unlocked": unlocked,
            })
            return "OK"
        raise AssertionError(query)

    async def fetch(self, query, *args):
        if "FROM casino_settings" in query:
            return []
        raise AssertionError(query)

    async def fetchrow(self, query, *args):
        if "FROM casino_crypto_credits" in query:
            coin, txid = args
            for row in self.credits:
                if row["coin"] == coin and row["txid"] == txid:
                    return row
            return None
        if "INSERT INTO casino_crypto_credits" in query:
            user_id, coin, address, txid, amount, rub, rate, confirmations, status, order_id = args
            if any(row["coin"] == coin and row["txid"] == txid for row in self.credits):
                return None
            row = {
                "id": self._next_id,
                "user_id": user_id,
                "coin": coin,
                "address": address,
                "txid": txid,
                "amount_crypto": amount,
                "amount_rub": rub,
                "rate": rate,
                "confirmations": confirmations,
                "status": status,
                "ledger_order_id": order_id,
            }
            self._next_id += 1
            self.credits.append(row)
            return {"id": row["id"]}
        if "INSERT INTO user_cashback_ledger" in query:
            user_id, rub, order_id, note = args
            if any(row["order_id"] == order_id for row in self.ledger):
                return None
            self.ledger.append({
                "user_id": user_id,
                "amount_rub": rub,
                "order_id": order_id,
                "note": note,
            })
            return {"user_id": user_id, "amount_rub": rub}
        if "FROM user_cashback_ledger" in query:
            order_id = args[0]
            for row in self.ledger:
                if row["order_id"] == order_id:
                    return row
            return None
        raise AssertionError(query)


def _quote(rub: str, *, below: bool = False):
    async def quote(coin, amount):
        return Decimal(rub), Decimal("100000"), below

    return quote


class CreditTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_txid_credits_once_and_locks_wagering(self):
        conn = Conn()
        first = await casino_crypto_deposit.credit_observed_payment(
            conn,
            user_id=100,
            coin="btc",
            address=ADDRESS,
            txid=TX,
            amount_crypto=Decimal("0.05000000"),
            confirmations=1,
            quote=_quote("5000.00"),
        )
        second = await casino_crypto_deposit.credit_observed_payment(
            conn,
            user_id=100,
            coin="btc",
            address=ADDRESS,
            txid=TX.upper(),
            amount_crypto=Decimal("0.05000000"),
            confirmations=3,
            quote=_quote("9000.00"),
        )
        self.assertEqual(first, "credited")
        self.assertEqual(second, "duplicate")
        self.assertEqual(len(conn.credits), 1)
        self.assertEqual(len(conn.ledger), 1)
        self.assertEqual(conn.ledger[0]["amount_rub"], Decimal("5000.00"))
        self.assertTrue(conn.ledger[0]["note"].startswith("Casino deposit: btc "))
        self.assertLessEqual(len(conn.ledger[0]["order_id"]), 64)
        self.assertEqual(conn.locks[0]["deposit_rub"], Decimal("5000.00"))
        self.assertEqual(conn.locks[0]["required_commission_rub"], Decimal("1050.00"))
        self.assertNotIn("casino_deposit_credits", (ROOT / "casino_crypto_deposit.py").read_text())

    async def test_below_minimum_does_not_grow_the_balance(self):
        conn = Conn()

        async def quote(coin, amount):
            return None, None, True

        result = await casino_crypto_deposit.credit_observed_payment(
            conn,
            user_id=100,
            coin="btc",
            address=ADDRESS,
            txid=TX,
            amount_crypto=Decimal("0.00001000"),
            confirmations=2,
            quote=quote,
        )
        self.assertEqual(result, "below_minimum")
        self.assertEqual(conn.credits[0]["status"], "below_minimum")
        self.assertEqual(conn.ledger, [])
        self.assertEqual(conn.locks, [])

    async def test_web_client_id_is_credited(self):
        conn = Conn()
        result = await casino_crypto_deposit.credit_observed_payment(
            conn,
            user_id=-56,
            coin="BTC",
            address=ADDRESS,
            txid=TX,
            amount_crypto=Decimal("0.02"),
            confirmations=1,
            quote=_quote("2000"),
        )
        self.assertEqual(result, "credited")
        self.assertEqual(conn.credits[0]["user_id"], -56)
        self.assertEqual(conn.locks[0]["telegram_id"], -56)

    async def test_unavailable_rate_and_zero_conf_are_left_for_the_next_scan(self):
        conn = Conn()

        async def broken(coin, amount):
            raise RuntimeError("rates")

        skipped = await casino_crypto_deposit.credit_observed_payment(
            conn,
            user_id=100,
            coin="ltc",
            address="ltc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
            txid=TX,
            amount_crypto=Decimal("1"),
            confirmations=1,
            quote=broken,
        )
        unconfirmed = await casino_crypto_deposit.credit_observed_payment(
            conn,
            user_id=100,
            coin="ltc",
            address="ltc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
            txid=TX,
            amount_crypto=Decimal("1"),
            confirmations=0,
            quote=broken,
        )
        self.assertEqual(skipped, "skipped")
        self.assertEqual(unconfirmed, "skipped")
        self.assertEqual(conn.credits, [])

    def test_min_deposit_is_one_hundred_rub(self):
        self.assertEqual(casino_crypto_deposit.min_deposit_rub("btc"), Decimal("100.00"))
        self.assertEqual(casino_crypto_deposit.min_deposit_rub("ltc"), Decimal("100.00"))
        src = (ROOT / "casino_crypto_deposit.py").read_text()
        self.assertIn('MIN_DEPOSIT_RUB = Decimal("100")', src)
        self.assertIn('if exc.status_code == 400 and "Минимум" in detail:', src)
        self.assertNotIn("amount_limits", src)

    def test_fiat_rail_ignores_crypto_credits(self):
        src = (ROOT / "casino_payout_rail.py").read_text()
        self.assertIn("rail = 'fiat'", src)
        self.assertNotIn("casino_crypto_credits", src)
        self.assertEqual(RAIL_FIAT, "fiat")

    def test_player_routes_issue_an_address_and_list_credits(self):
        src = (ROOT / "routers" / "user_balance.py").read_text()
        self.assertIn('"/casino/crypto-deposit/address"', src)
        self.assertIn('"/casino/crypto-deposits"', src)

    def test_worker_is_wired_beside_the_hot_wallet_loop(self):
        src = (ROOT / "main.py").read_text()
        self.assertIn("casino_crypto_deposit_loop", src)
        self.assertIn("crypto_deposit_task.cancel()", src)

    def test_migration_keeps_house_deals_and_web_ids(self):
        sql = (ROOT / "migrations" / "add_casino_crypto_deposits.sql").read_text()
        self.assertIn("CREATE TABLE IF NOT EXISTS casino_crypto_addresses", sql)
        self.assertIn("UNIQUE (coin, txid)", sql)
        self.assertIn("crypto_credit_id", sql)
        self.assertIn("telegram_id <> 0", sql)
        self.assertIn("CHECK (user_id <> 0)", sql)


if __name__ == "__main__":
    unittest.main()
