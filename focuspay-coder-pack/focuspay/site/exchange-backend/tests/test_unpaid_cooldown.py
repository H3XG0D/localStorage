"""После отмены BUY с выданными реквизитами новую заявку не даём 30 минут."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import order_service
from order_service import (
    UNPAID_COOLDOWN_MINUTES,
    _unpaid_cooldown_detail,
    _unpaid_cooldown_remaining_sec,
)


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _pool_with_rows(rows):
    conn = MagicMock()

    async def fetch(*_args, **_kwargs):
        return rows

    conn.fetch = fetch
    pool = MagicMock()
    pool.acquire.return_value = _Acquire(conn)
    return pool


def _remaining(rows):
    pool = _pool_with_rows(rows)

    async def fake_get_pool():
        return pool

    original = order_service.get_pool
    order_service.get_pool = fake_get_pool
    try:
        return asyncio.run(_unpaid_cooldown_remaining_sec(7))
    finally:
        order_service.get_pool = original


BILL = {"bill": {"bank": "Сбер", "reciver": "+79000000000", "fio": "Иван И."}}


class UnpaidCooldownTests(unittest.TestCase):
    def test_cancel_with_bill_blocks_rest_of_window(self):
        rows = [{"payment_snapshot": BILL, "age_sec": 120}]
        self.assertEqual(_remaining(rows), UNPAID_COOLDOWN_MINUTES * 60 - 120)

    def test_cancel_without_bill_does_not_block(self):
        rows = [{"payment_snapshot": {"bill": {}}, "age_sec": 60}]
        self.assertEqual(_remaining(rows), 0)

    def test_window_passed_does_not_block(self):
        rows = [{"payment_snapshot": BILL, "age_sec": UNPAID_COOLDOWN_MINUTES * 60 + 1}]
        self.assertEqual(_remaining(rows), 0)

    def test_no_cancelled_orders_does_not_block(self):
        self.assertEqual(_remaining([]), 0)

    def test_detail_mentions_minutes_and_support(self):
        detail = _unpaid_cooldown_detail(29 * 60 + 30)
        self.assertIn("30 мин", detail)
        self.assertIn("@", detail)

    def test_create_web_order_guards_buy(self):
        src = Path(__file__).resolve().parents[1].joinpath("order_service.py").read_text()
        self.assertIn("_unpaid_cooldown_remaining_sec(user_id)", src)
        self.assertIn("create_denied_unpaid_cooldown", src)
        retry = Path(__file__).resolve().parents[1].joinpath("requisite_retry.py").read_text()
        self.assertIn("_unpaid_cooldown_remaining_sec", retry)


if __name__ == "__main__":
    unittest.main()
