"""Низкий горячий кошелёк: часы в тексте, пауза 4 часа, только старшие на смене."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hot_wallet_alert import (
    _SENIORS_SQL,
    alert_due,
    finance_seniors_on_shift,
    format_low_balance_message,
    maybe_alert_low_hot_wallet,
)
from hot_wallet_runway import assemble_runway

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


def _low_runway():
    return assemble_runway(
        coins=[
            {"coin": "btc", "spendable": 0.0001, "rate_rub": 100_000_000},
            {"coin": "ltc", "spendable": 1, "rate_rub": 5_000},
        ],
        outflow={"btc": {"buy_crypto": 0.0168, "buy_rub": 16_800, "withdraw_rub": 0, "deals": 2}},
        min_hot_balance_rub=50_000,
        signer_ok=True,
    )


class MemoryConn:
    def __init__(self, recipients: list[int] | None = None, stored=None):
        self.recipients = recipients or []
        self.stored = stored
        self.executes: list[tuple] = []

    async def fetchrow(self, _sql, *_args):
        if self.stored is None:
            return None
        return {"value": self.stored}

    async def fetch(self, _sql, *_args):
        return [{"telegram_user_id": cid} for cid in self.recipients]

    async def execute(self, sql, *args):
        self.executes.append((sql, args))
        if "DELETE" in sql.upper():
            self.stored = None
        elif args:
            self.stored = json.loads(args[1])


class AlertGateTests(unittest.IsolatedAsyncioTestCase):
    def test_message_names_hours(self):
        text = format_low_balance_message(_low_runway())
        self.assertIn("Низкий баланс горячего кошелька", text)
        self.assertIn("хватит ≈ 1 ч", text)
        self.assertIn("ниже порога", text)
        self.assertIn("50 000", text)

    def test_due_when_never_sent_and_after_four_hours(self):
        self.assertTrue(alert_due(None, NOW))
        self.assertFalse(alert_due(NOW - timedelta(hours=3), NOW))
        self.assertTrue(alert_due(NOW - timedelta(hours=4), NOW))

    def test_recipient_sql_is_finance_senior_on_shift(self):
        self.assertIn("p.role = 'finance'", _SENIORS_SQL)
        self.assertIn("p.grade = 'senior'", _SENIORS_SQL)
        self.assertIn("ended_at IS NULL", _SENIORS_SQL)
        self.assertIn("telegram_user_id IS NOT NULL", _SENIORS_SQL)

    async def test_skips_empty_telegram_id(self):
        conn = MemoryConn()

        async def fetch(_sql, *_args):
            return [{"telegram_user_id": 111}, {"telegram_user_id": None}, {"telegram_user_id": 111}]

        conn.fetch = fetch
        self.assertEqual(await finance_seniors_on_shift(conn), [111])

    async def test_sends_once_then_waits(self):
        conn = MemoryConn(recipients=[4242])
        sent: list[tuple] = []

        def send(ids, text):
            sent.append((ids, text))
            return True

        first = await maybe_alert_low_hot_wallet(conn, _low_runway(), now=NOW, send=send)
        second = await maybe_alert_low_hot_wallet(
            conn, _low_runway(), now=NOW + timedelta(hours=1), send=send
        )
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], [4242])
        self.assertIn("ч", sent[0][1])

    async def test_no_one_on_shift_does_not_remember(self):
        conn = MemoryConn(recipients=[])

        def send(_ids, _text):
            raise AssertionError("некому писать")

        sent = await maybe_alert_low_hot_wallet(conn, _low_runway(), now=NOW, send=send)
        self.assertFalse(sent)
        self.assertIsNone(conn.stored)
        self.assertEqual(conn.executes, [])

    async def test_failed_send_does_not_start_the_pause(self):
        conn = MemoryConn(recipients=[7])
        sent = await maybe_alert_low_hot_wallet(
            conn, _low_runway(), now=NOW, send=lambda _ids, _text: False
        )
        self.assertFalse(sent)
        self.assertIsNone(conn.stored)

    async def test_above_floor_clears_the_pause(self):
        conn = MemoryConn(stored={"last_sent_at": (NOW - timedelta(hours=1)).isoformat()})
        healthy = assemble_runway(
            coins=[{"coin": "btc", "spendable": 1, "rate_rub": 1_000_000}],
            outflow={},
            min_hot_balance_rub=50_000,
            signer_ok=True,
        )
        sent = await maybe_alert_low_hot_wallet(conn, healthy, now=NOW, send=lambda *_a: True)
        self.assertFalse(sent)
        self.assertIsNone(conn.stored)
        self.assertTrue(any("DELETE" in sql.upper() for sql, _args in conn.executes))

    async def test_signer_down_does_not_clear_or_send(self):
        conn = MemoryConn(stored={"last_sent_at": NOW.isoformat()}, recipients=[1])
        down = assemble_runway(
            coins=[],
            outflow={},
            min_hot_balance_rub=50_000,
            signer_ok=False,
        )
        sent = await maybe_alert_low_hot_wallet(conn, down, now=NOW, send=lambda *_a: True)
        self.assertFalse(sent)
        self.assertIsNotNone(conn.stored)
        self.assertEqual(conn.executes, [])


class MonitorWiringTests(unittest.TestCase):
    def test_loop_calls_alert_tick(self):
        text = (ROOT / "hot_wallet_monitor.py").read_text()
        self.assertIn("alert_hot_wallet_tick", text)


if __name__ == "__main__":
    unittest.main()
