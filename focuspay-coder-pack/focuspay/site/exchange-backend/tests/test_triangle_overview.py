"""Плюс треугольника: 12% провайдера минус доплата 3% и долив, плюс фикс вывода."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from payout_requisite_stats import fetch_triangle_overview, sell_bonus_rub, triangle_net_rub


class TriangleMathTests(unittest.TestCase):
    def test_sell_bonus_is_the_extra_inside_the_card(self):
        self.assertEqual(sell_bonus_rub(10300, 3), 300.0)
        self.assertEqual(sell_bonus_rub(10000, 0), 0.0)

    def test_net_keeps_provider_saving_and_flat_fee(self):
        # 10300 * 12% = 1236, bonus 300, doliv 0, fee 100
        self.assertEqual(triangle_net_rub(1236, 300, 0, 100), 1036.0)
        self.assertEqual(triangle_net_rub(1236, 300, 0, 100, 9), 1027.0)


class TriangleOverviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_overview_splits_sell_bonus_and_balance_fee(self):
        live = {
            "sell_cards": 1,
            "withdraw_cards": 1,
            "sell_amount": 10300.0,
            "withdraw_amount": 900.0,
            "paid": 0.0,
        }
        fee = {"balance_fee": 100.0, "casino_fee": 0.0}
        period = {"cards": 1, "turnover": 10300.0, "sell_paid": 10300.0}
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=[live, fee, period, fee])
        conn.fetchval = AsyncMock(side_effect=[0, 0, 0])
        with (
            patch_enabled(),
        ):
            out = await fetch_triangle_overview(conn, date(2026, 10, 1), date(2026, 10, 10))
        self.assertEqual(out["open"]["sell_amount_rub"], 10300.0)
        self.assertEqual(out["open"]["withdraw_amount_rub"], 900.0)
        self.assertEqual(out["forecast"]["sell_bonus_rub"], 300.0)
        self.assertEqual(out["forecast"]["saved_provider_rub"], round(11200 * 0.12, 2))
        self.assertEqual(out["forecast"]["balance_fee_rub"], 100.0)
        self.assertEqual(out["period"]["sell_bonus_rub"], 300.0)
        self.assertEqual(out["period"]["withdraw_fee_rub"], 100.0)
        self.assertGreater(out["period"]["net_rub"], 0)


def patch_enabled():
    from unittest.mock import patch

    return patch.multiple(
        "runtime_settings",
        triangle_enabled=lambda: True,
        triangle_sell_bonus_pct=lambda: 3.0,
        create=True,
    )
