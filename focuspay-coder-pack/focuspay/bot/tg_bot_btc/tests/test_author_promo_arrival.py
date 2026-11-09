"""Приход p_CODE не путается с реферальным ref_ и не требует лимита активаций."""
import unittest
from unittest.mock import AsyncMock

from services.author_promo_arrival import (
    assign_author_arrival,
    author_coupon_block_reason,
    parse_author_start,
)


class ParseAuthorStartTests(unittest.TestCase):
    def test_platform_suffix(self):
        self.assertEqual(parse_author_start("p_Vova7k_tt"), "VOVA7K")

    def test_bare_code(self):
        self.assertEqual(parse_author_start("p_VOVA7K"), "VOVA7K")

    def test_other_payloads(self):
        self.assertIsNone(parse_author_start("ref_abc"))
        self.assertIsNone(parse_author_start("promo_SALE"))
        self.assertIsNone(parse_author_start(""))


class AssignAuthorArrivalTests(unittest.IsolatedAsyncioTestCase):
    async def test_inserts_without_touching_activation_cap(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"code": "VOVA7K", "author_telegram_id": 9})
        conn.execute = AsyncMock(return_value="INSERT 0 1")
        created = await assign_author_arrival(conn, 15, "VOVA7K")
        self.assertTrue(created)
        sql = conn.execute.await_args.args[0]
        self.assertIn("promo_attributions", sql)
        self.assertNotIn("max_activations", sql)
        self.assertEqual(conn.execute.await_args.args[1:], (15, "VOVA7K"))

    async def test_skips_self(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"code": "VOVA7K", "author_telegram_id": 9})
        created = await assign_author_arrival(conn, 9, "VOVA7K")
        self.assertFalse(created)
        conn.execute.assert_not_awaited()

    async def test_missing_campaign(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        self.assertFalse(await assign_author_arrival(conn, 15, "NOPE"))


class BlockReasonTests(unittest.TestCase):
    def test_matches_exchange_rules(self):
        self.assertEqual(
            author_coupon_block_reason(3, 3, has_completed_order=False),
            "Нельзя использовать свой промокод",
        )
