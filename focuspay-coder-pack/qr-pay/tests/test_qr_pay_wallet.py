"""Резервы, лимиты и применение статусов для оплат по QR СБП."""
from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

from services import qr_pay_wallet as wallet
from services.finance666_client import parse_payment
from services.qr_pay_wallet import QrPayError, charged_rub_for


def run(coro):
    return asyncio.run(coro)


class FakeConn:
    """Минимальный asyncpg-подобный conn: ответы подбираются по подстроке запроса."""

    def __init__(self, *, rows=(), vals=()):
        self._rows = list(rows)
        self._vals = list(vals)
        self.queries: list[str] = []

    def _match(self, table, query):
        for needle, value in table:
            if needle in query:
                return value
        return None

    async def execute(self, query, *args):
        self.queries.append(query)
        return "OK"

    async def fetchval(self, query, *args):
        self.queries.append(query)
        return self._match(self._vals, query)

    async def fetchrow(self, query, *args):
        self.queries.append(query)
        return self._match(self._rows, query)

    async def fetch(self, query, *args):
        self.queries.append(query)
        return self._match(self._rows, query) or []

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Tx()


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Acquire:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Acquire()


def fake_pool(conn):
    return patch(
        "services.qr_pay_wallet.get_pool",
        AsyncMock(return_value=FakePool(conn)),
    )


def checked_row(**overrides):
    row = {
        "id": 1,
        "merchant_transaction_id": "qr-1",
        "provider_transaction_id": "tx-1",
        "user_id": 500,
        "charged_rub": 1030.0,
        "amount_rub": 1000.0,
        "local_status": "CHECKED",
        "status_code": "CHECKED",
        "status_group": "PROCESSING",
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=30),
        "provider_updated_at": None,
    }
    row.update(overrides)
    return row


class MarkupTests(unittest.TestCase):
    def test_markup_added_to_qr_amount(self):
        with patch("services.qr_pay_wallet.qr_pay_markup_pct", return_value=3.0):
            self.assertEqual(charged_rub_for(1000), 1030.0)
        with patch("services.qr_pay_wallet.qr_pay_markup_pct", return_value=0.0):
            self.assertEqual(charged_rub_for(1000), 1000.0)

    def test_explicit_markup_wins_over_settings(self):
        with patch("services.qr_pay_wallet.qr_pay_markup_pct", return_value=3.0):
            self.assertEqual(charged_rub_for(1000, 10.0), 1100.0)


class LimitTests(unittest.TestCase):
    def test_single_payment_over_limit_rejected(self):
        conn = FakeConn(vals=[("SUM(charged_rub)", 0.0)])
        with patch("services.qr_pay_wallet.qr_pay_max_rub_per_tx", return_value=15000.0), patch(
            "services.qr_pay_wallet.qr_pay_max_rub_per_day", return_value=30000.0
        ):
            with self.assertRaises(QrPayError) as ctx:
                run(wallet.check_limits(conn, 500, 15001.0))
        self.assertIn("Максимум одной оплаты", str(ctx.exception))

    def test_daily_limit_counts_reserved_and_settled(self):
        conn = FakeConn(vals=[("SUM(charged_rub)", 28000.0)])
        with patch("services.qr_pay_wallet.qr_pay_max_rub_per_tx", return_value=15000.0), patch(
            "services.qr_pay_wallet.qr_pay_max_rub_per_day", return_value=30000.0
        ):
            with self.assertRaises(QrPayError) as ctx:
                run(wallet.check_limits(conn, 500, 5000.0))
            self.assertIn("Лимит за сутки", str(ctx.exception))
            run(wallet.check_limits(conn, 500, 1000.0))

    def test_spent_today_query_excludes_released(self):
        conn = FakeConn(vals=[("SUM(charged_rub)", 100.0)])
        run(wallet.spent_today_rub(conn, 500))
        query = conn.queries[-1]
        self.assertIn("'RESERVED', 'SETTLED', 'REFUNDED'", query)
        self.assertNotIn("RELEASED", query)


class ReserveTests(unittest.TestCase):
    def _reserve(self, row, *, available=5000.0):
        conn = FakeConn(
            rows=[
                ("UPDATE qr_sbp_payments", checked_row(local_status="RESERVED")),
                ("SELECT * FROM qr_sbp_payments", row),
            ],
            vals=[("SUM(charged_rub)", 0.0)],
        )
        with fake_pool(conn), patch(
            "services.qr_pay_wallet.unified_available", AsyncMock(return_value=available)
        ), patch("services.qr_pay_wallet.qr_pay_max_rub_per_tx", return_value=15000.0), patch(
            "services.qr_pay_wallet.qr_pay_max_rub_per_day", return_value=30000.0
        ):
            return run(wallet.reserve(merchant_transaction_id="qr-1", user_id=500))

    def test_reserve_locks_user_and_marks_reserved(self):
        result = self._reserve(checked_row())
        self.assertEqual(result["local_status"], "RESERVED")

    def test_expired_check_cannot_be_paid(self):
        expired = checked_row(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        with self.assertRaises(QrPayError) as ctx:
            self._reserve(expired)
        self.assertIn("истекла", str(ctx.exception))

    def test_non_checked_provider_status_blocks_pay(self):
        with self.assertRaises(QrPayError):
            self._reserve(checked_row(status_code="DECLINED"))

    def test_second_reserve_of_same_payment_rejected(self):
        with self.assertRaises(QrPayError) as ctx:
            self._reserve(checked_row(local_status="RESERVED"))
        self.assertIn("уже отправлен", str(ctx.exception))

    def test_insufficient_balance_rejected(self):
        with self.assertRaises(QrPayError) as ctx:
            self._reserve(checked_row(), available=500.0)
        self.assertIn("Не хватает баланса", str(ctx.exception))


class ProviderStatusTests(unittest.TestCase):
    def _payment(self, updated_at, *, group="SUCCEEDED", code="SUCCESS"):
        return parse_payment(
            {
                "transaction_id": "tx-1",
                "merchant_transaction_id": "qr-1",
                "status": {"group": group, "code": code, "is_final": True},
                "updated_at": updated_at,
            }
        )

    def test_older_update_is_not_applied(self):
        stored = checked_row(
            local_status="REFUNDED",
            provider_updated_at=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
        )
        conn = FakeConn(rows=[("SELECT * FROM qr_sbp_payments", stored)])
        with fake_pool(conn):
            row, applied = run(
                wallet.apply_provider_status("qr-1", self._payment("2026-08-23T11:00:00Z"))
            )
        self.assertFalse(applied)
        self.assertEqual(row["local_status"], "REFUNDED")

    def test_newer_update_is_applied(self):
        stored = checked_row(
            provider_updated_at=datetime(2026, 8, 23, 11, 0, tzinfo=timezone.utc)
        )
        conn = FakeConn(
            rows=[
                ("UPDATE qr_sbp_payments", checked_row(status_code="SUCCESS")),
                ("SELECT * FROM qr_sbp_payments", stored),
            ]
        )
        with fake_pool(conn):
            _, applied = run(
                wallet.apply_provider_status("qr-1", self._payment("2026-08-23T12:00:00Z"))
            )
        self.assertTrue(applied)

    def test_unknown_payment_reports_not_applied(self):
        conn = FakeConn(rows=[])
        with fake_pool(conn):
            row, applied = run(
                wallet.apply_provider_status("qr-404", self._payment("2026-08-23T12:00:00Z"))
            )
        self.assertIsNone(row)
        self.assertFalse(applied)


if __name__ == "__main__":
    unittest.main()
