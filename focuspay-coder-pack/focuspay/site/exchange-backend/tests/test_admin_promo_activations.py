"""Админские промо: активации скидочных кодов считаются по gift_redemptions."""
import unittest
from unittest.mock import AsyncMock

from routers.admin_promo import _count_promo_activations


class CountPromoActivationsTests(unittest.IsolatedAsyncioTestCase):
    async def test_exchange_discount_counts_gift_redemptions(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=3)
        used = await _count_promo_activations(conn, "DABC123", "exchange_discount")
        self.assertEqual(used, 3)
        sql = conn.fetchval.await_args.args[0]
        self.assertIn("promo_gift_redemptions", sql)
        self.assertNotIn("promo_attributions", sql)
        self.assertEqual(conn.fetchval.await_args.args[1], "DABC123")

    async def test_fixed_rub_counts_gift_redemptions(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=2)
        used = await _count_promo_activations(conn, "BXYZ789", "fixed_rub")
        self.assertEqual(used, 2)
        sql = conn.fetchval.await_args.args[0]
        self.assertIn("promo_gift_redemptions", sql)

    async def test_partner_counts_attributions(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=11)
        used = await _count_promo_activations(conn, "P123456", "partner")
        self.assertEqual(used, 11)
        sql = conn.fetchval.await_args.args[0]
        self.assertIn("promo_attributions", sql)
        self.assertNotIn("promo_gift_redemptions", sql)
