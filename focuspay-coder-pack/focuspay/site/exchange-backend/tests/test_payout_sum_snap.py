"""Подгонка суммы SELL: попадание в цель, cap, коридор спреда, выключатель."""
from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import payout_sum_snap
from payout_requisite_matcher import to_kop
from payout_sum_snap import (
    clear_targets,
    get_targets,
    set_targets,
    snap_sell_fiat,
    targets_from_free_amounts,
)

ROOT = Path(__file__).resolve().parents[1]

# Курс рынка 100 ₽, спред 5% → базовый курс 95 ₽, 100 монет = 9500 ₽.
# Сдвиг на 200 ₽ здесь равен 2 п.п. спреда, поэтому коридор берём 3..7%:
# именно он, а не cap в рублях, обычно и ограничивает подгонку.
MARKET = Decimal("100")
CRYPTO = Decimal("100")

CONF = {
    "enabled": True,
    "cap_rub": 300.0,
    "spread_min_pct": 3.0,
    "spread_max_pct": 7.0,
}


def conf(**over):
    out = dict(CONF)
    out.update(over)
    return out


class SnapCoreTests(unittest.TestCase):
    def tearDown(self):
        clear_targets()

    def test_snaps_up_to_nearby_target(self):
        out = snap_sell_fiat(
            Decimal("9500.00"), CRYPTO, MARKET, config=conf(), targets=[to_kop(9700)]
        )
        self.assertIsNotNone(out)
        fiat, rate = out
        self.assertEqual(fiat, Decimal("9700.00"))
        self.assertEqual(rate, Decimal("97.0000"))
        self.assertEqual(fiat, (rate * CRYPTO).quantize(Decimal("0.01")))

    def test_snaps_down_within_corridor(self):
        out = snap_sell_fiat(
            Decimal("9500.00"), CRYPTO, MARKET, config=conf(), targets=[to_kop(9300)]
        )
        fiat, rate = out
        self.assertEqual(fiat, Decimal("9300.00"))
        self.assertEqual(rate, Decimal("93.0000"))

    def test_cap_blocks_far_target(self):
        self.assertIsNone(
            snap_sell_fiat(
                Decimal("9500.00"), CRYPTO, MARKET, config=conf(), targets=[to_kop(9900)]
            )
        )

    def test_spread_corridor_blocks_even_inside_cap(self):
        # 9200 ₽ = спред 8%: cap в 1000 ₽ пропустил бы, коридор 3..7% — нет.
        self.assertIsNone(
            snap_sell_fiat(
                Decimal("9500.00"),
                CRYPTO,
                MARKET,
                config=conf(cap_rub=1000.0),
                targets=[to_kop(9200)],
            )
        )

    def test_markup_corridor_uses_premium_over_market(self):
        # Рынок 100, 100 монет, база 10500 ₽ (наценка 5%). Цель 10700 → премия 7%.
        markup_conf = conf(pricing_mode="markup", spread_min_pct=3.0, spread_max_pct=7.0)
        out = snap_sell_fiat(
            Decimal("10500.00"),
            CRYPTO,
            MARKET,
            config=markup_conf,
            targets=[to_kop(10700)],
        )
        self.assertIsNotNone(out)
        self.assertEqual(out[0], Decimal("10700.00"))
        self.assertIsNone(
            snap_sell_fiat(
                Decimal("10500.00"),
                CRYPTO,
                MARKET,
                config=markup_conf,
                targets=[to_kop(10800)],
            )
        )

    def test_disabled_switch_never_snaps(self):
        self.assertIsNone(
            snap_sell_fiat(
                Decimal("9500.00"),
                CRYPTO,
                MARKET,
                config=conf(enabled=False),
                targets=[to_kop(9700)],
            )
        )

    def test_zero_cap_never_snaps(self):
        self.assertIsNone(
            snap_sell_fiat(
                Decimal("9500.00"),
                CRYPTO,
                MARKET,
                config=conf(cap_rub=0),
                targets=[to_kop(9700)],
            )
        )

    def test_exact_match_needs_no_snap(self):
        self.assertIsNone(
            snap_sell_fiat(
                Decimal("9500.00"), CRYPTO, MARKET, config=conf(), targets=[to_kop(9500)]
            )
        )

    def test_picks_nearest_target(self):
        out = snap_sell_fiat(
            Decimal("9500.00"),
            CRYPTO,
            MARKET,
            config=conf(),
            targets=[to_kop(9700), to_kop(9550)],
        )
        self.assertEqual(out[0], Decimal("9550.00"))

    def test_equal_distance_prefers_client_favour(self):
        out = snap_sell_fiat(
            Decimal("9500.00"),
            CRYPTO,
            MARKET,
            config=conf(),
            targets=[to_kop(9400), to_kop(9600)],
        )
        self.assertEqual(out[0], Decimal("9600.00"))

    def test_no_targets_no_snap(self):
        self.assertIsNone(
            snap_sell_fiat(Decimal("9500.00"), CRYPTO, MARKET, config=conf(), targets=[])
        )

    def test_bad_inputs_are_ignored(self):
        self.assertIsNone(
            snap_sell_fiat(
                Decimal("9500"), Decimal("0"), MARKET, config=conf(), targets=[to_kop(9700)]
            )
        )
        self.assertIsNone(
            snap_sell_fiat(
                Decimal("9500"), CRYPTO, Decimal("0"), config=conf(), targets=[to_kop(9700)]
            )
        )


class TargetCacheTests(unittest.TestCase):
    def tearDown(self):
        clear_targets()

    def test_targets_are_deduped_sorted_and_positive(self):
        set_targets([500, 100, 500, 0, -3])
        self.assertEqual(get_targets(), (100, 500))

    def test_stale_cache_is_not_used(self):
        set_targets([to_kop(9700)])
        with patch.object(payout_sum_snap, "_targets_ts", 0.0):
            self.assertEqual(get_targets(), ())

    def test_free_amounts_convert_to_kopecks(self):
        self.assertEqual(
            targets_from_free_amounts([Decimal("9700.00"), Decimal("0.00"), Decimal("300.50")]),
            [970000, 30050],
        )

    def test_cached_targets_used_when_not_passed(self):
        set_targets([to_kop(9700)])
        out = snap_sell_fiat(Decimal("9500.00"), CRYPTO, MARKET, config=conf())
        self.assertEqual(out[0], Decimal("9700.00"))


class RuntimeSettingsTests(unittest.TestCase):
    def test_defaults_disable_snap_and_build_corridor(self):
        import runtime_settings

        runtime_settings.invalidate_cache()
        cfg = runtime_settings.sell_snap_config()
        self.assertFalse(cfg["enabled"])
        self.assertGreater(cfg["cap_rub"], 0)
        self.assertLessEqual(cfg["spread_min_pct"], cfg["spread_max_pct"])

    def test_snap_keys_are_persisted_settings(self):
        from runtime_settings import _SETTING_KEYS

        for key in (
            "sell_snap_enabled",
            "sell_snap_cap_rub",
            "sell_spread_min_pct",
            "sell_spread_max_pct",
        ):
            self.assertIn(key, _SETTING_KEYS)

    def test_admin_pricing_guards_corridor(self):
        src = (ROOT / "routers" / "admin_pricing.py").read_text()
        self.assertIn("sell_spread_min_pct must be <= sell_spread_max_pct", src)
        self.assertIn("sell_spread_pct must stay inside", src)


class OrderServiceHookTests(unittest.TestCase):
    def test_sell_branch_calls_snap_and_skips_operator_manual(self):
        src = (ROOT / "order_service.py").read_text()
        self.assertIn("from payout_sum_snap import snap_sell_fiat", src)
        self.assertIn('if direction == "sell" and not operator_manual:', src)
        self.assertIn("snapped = snap_sell_fiat(fiat, crypto_amt, market_dec)", src)

    def test_public_quote_endpoint_declared(self):
        src = (ROOT / "routers" / "public.py").read_text()
        self.assertIn('@router.post("/sell/quote")', src)
        self.assertIn("quote_sell", src)


class QuoteSellTests(unittest.IsolatedAsyncioTestCase):
    async def test_quote_reports_adjustment(self):
        import order_service

        rates = AsyncMock(return_value={"usdt": 100.0})
        with patch.object(order_service, "get_sell_market_rates", new=rates), patch(
            "runtime_settings.sell_discount", return_value=0.95
        ), patch(
            "payout_sum_snap.snap_sell_fiat",
            return_value=(Decimal("9700.00"), Decimal("97.0000")),
        ):
            out = await order_service.quote_sell("usdt", crypto_amount=100)
        self.assertEqual(out["fiat_amount"], 9700.0)
        self.assertEqual(out["base_rate"], 95.0)
        self.assertTrue(out["adjusted"])

    async def test_quote_without_snap_is_plain(self):
        import order_service

        rates = AsyncMock(return_value={"usdt": 100.0})
        with patch.object(order_service, "get_sell_market_rates", new=rates), patch(
            "runtime_settings.sell_discount", return_value=0.95
        ), patch("payout_sum_snap.snap_sell_fiat", return_value=None):
            out = await order_service.quote_sell("usdt", crypto_amount=100)
        self.assertEqual(out["fiat_amount"], 9500.0)
        self.assertFalse(out["adjusted"])


class LoopTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        clear_targets()

    async def test_tick_stores_plans_refreshes_targets_and_notifies_once(self):
        import payout_requisite_loop as loop_mod
        from payout_requisite_matcher import Candidate, Plan

        loop_mod.reset_notification_state()

        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(return_value=555)
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        from datetime import datetime, timedelta, timezone

        row = {
            "id": 1,
            "operator_id": 5,
            "label": "Карта",
            "method": "card",
            "requisites": "2202200112345678",
            "amount_rub": Decimal("9700.00"),
            "paid_rub": Decimal("0.00"),
            "deadline_at": datetime.now(timezone.utc) + timedelta(hours=2),
        }
        plan = Plan(orders=[Candidate(order_id="S1", amount_kop=970000)])
        send = AsyncMock(return_value=1)

        with patch.object(loop_mod, "expire_overdue", new=AsyncMock(return_value=0)), patch.object(
            loop_mod, "active_requisites", new=AsyncMock(return_value=[row])
        ), patch.object(
            loop_mod,
            "plan_for_requisite",
            new=AsyncMock(return_value=(plan, Decimal("9700.00"))),
        ), patch.object(
            loop_mod, "store_plan", new=AsyncMock()
        ), patch(
            "telegram_notify.send_admin_message", new=send
        ):
            first = await loop_mod.run_tick(pool)
            second = await loop_mod.run_tick(pool)

        self.assertEqual(first["plans"], 1)
        self.assertEqual(first["notified"], 1)
        self.assertEqual(second["notified"], 0)
        self.assertEqual(get_targets(), (970000,))
        self.assertIn("S1", send.await_args.args[0])

    async def test_expire_overdue_releases_orders_and_marks_expired(self):
        import payout_requisite_loop as loop_mod

        conn = MagicMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)

        async def fetch(sql, *args):
            if "FROM operator_payout_requisites" in sql:
                return [
                    {
                        "id": 7,
                        "operator_id": 5,
                        "paid_rub": Decimal("0.00"),
                        "cost_pct": Decimal("3.000"),
                    }
                ]
            if "UPDATE payout_requisite_allocations" in sql:
                return [{"order_id": "S9", "operator_id": 5}]
            return []

        conn.fetch = AsyncMock(side_effect=fetch)
        count = await loop_mod.expire_overdue(conn)
        self.assertEqual(count, 1)
        statements = [c.args[0] for c in conn.execute.await_args_list]
        self.assertTrue(any("SET operator_id = NULL" in s for s in statements))
        self.assertTrue(any("status = 'EXPIRED'" in s for s in statements))

    async def test_expire_overdue_keeps_empty_pending_withdrawal(self):
        import payout_requisite_loop as loop_mod

        conn = MagicMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[None, "pending"])

        async def fetch(sql, *args):
            if "FROM operator_payout_requisites" in sql and "deadline_at" in sql:
                return [
                    {
                        "id": 65,
                        "direction": "payin",
                        "operator_id": 5,
                        "source_withdrawal_id": 65,
                        "amount_rub": Decimal("988.00"),
                        "paid_rub": Decimal("0.00"),
                        "cost_pct": Decimal("0"),
                    }
                ]
            return []

        conn.fetch = AsyncMock(side_effect=fetch)
        count = await loop_mod.expire_overdue(conn)
        self.assertEqual(count, 0)
        statements = [c.args[0] for c in conn.execute.await_args_list]
        self.assertTrue(any("make_interval" in s for s in statements))
        self.assertFalse(any("status = 'EXPIRED'" in s for s in statements))

    async def test_give_up_cancels_idle_withdrawal_card_and_skips_booked(self):
        from payin_requisite_rail import MANUAL_PAYOUT_NOTE, give_up_idle_withdrawal_triangles

        conn = MagicMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[None, 1])
        conn.fetch = AsyncMock(
            return_value=[
                {"id": 1, "operator_id": 5, "label": "Вывод #65", "method": "sbp",
                 "amount_rub": Decimal("900.00"), "source_withdrawal_id": 65},
                {"id": 2, "operator_id": 5, "label": "Вывод #66", "method": "card",
                 "amount_rub": Decimal("1500.00"), "source_withdrawal_id": 66},
            ]
        )
        out = await give_up_idle_withdrawal_triangles(conn, minutes=30)

        self.assertEqual([r["source_withdrawal_id"] for r in out], [65])
        select_sql, *select_args = conn.fetch.await_args.args
        self.assertIn("FOR UPDATE", select_sql)
        self.assertIn("w.status = 'pending'", select_sql)
        self.assertEqual(select_args[1], 30)
        self.assertEqual(conn.execute.await_count, 1)
        self.assertEqual(conn.execute.await_args.args[1:], (1, MANUAL_PAYOUT_NOTE))

    async def test_tick_pings_finance_operator_for_manual_payout(self):
        import payout_requisite_loop as loop_mod

        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(return_value=555)
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx
        row = {"id": 1, "operator_id": 5, "label": "Вывод #65", "method": "sbp",
               "amount_rub": Decimal("900.00"), "source_withdrawal_id": 65}
        send = AsyncMock(return_value=1)

        with patch.object(
            loop_mod, "give_up_idle_withdrawal_triangles", new=AsyncMock(return_value=[row])
        ), patch.object(loop_mod, "expire_overdue", new=AsyncMock(return_value=0)), patch(
            "payin_requisite_rail.reopen_pending_withdrawal_triangles", new=AsyncMock(return_value=0)
        ), patch("telegram_notify.send_admin_message", new=send):
            out = await loop_mod.run_tick(pool)

        self.assertEqual(out["gave_up"], 1)
        self.assertEqual(out["notified"], 1)
        text = send.await_args.args[0]
        self.assertIn("Вывод #65: выплатить вручную", text)
        self.assertIn("900 ₽ на СБП", text)
        self.assertEqual(send.await_args.kwargs["chat_id"], 555)

    async def test_expire_overdue_keeps_partial_payin_during_hunt(self):
        import payout_requisite_loop as loop_mod
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        conn = MagicMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[None, now - timedelta(minutes=10)])

        async def fetch(sql, *args):
            if "FROM operator_payout_requisites" in sql:
                return [
                    {
                        "id": 13,
                        "direction": "payin",
                        "operator_id": 5,
                        "amount_rub": Decimal("26000.00"),
                        "paid_rub": Decimal("15000.00"),
                        "cost_pct": Decimal("0"),
                    }
                ]
            return []

        conn.fetch = AsyncMock(side_effect=fetch)
        count = await loop_mod.expire_overdue(conn)
        self.assertEqual(count, 0)
        self.assertFalse(any("status = 'EXPIRED'" in c.args[0] for c in conn.execute.await_args_list))

    async def test_expire_overdue_payin_after_hunt_tail(self):
        import payout_requisite_loop as loop_mod
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        conn = MagicMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[None, now - timedelta(minutes=140)])

        async def fetch(sql, *args):
            if "FROM operator_payout_requisites" in sql:
                return [
                    {
                        "id": 13,
                        "direction": "payin",
                        "operator_id": 5,
                        "amount_rub": Decimal("26000.00"),
                        "paid_rub": Decimal("15000.00"),
                        "cost_pct": Decimal("0"),
                    }
                ]
            if "UPDATE payout_requisite_allocations" in sql:
                return []
            return []

        conn.fetch = AsyncMock(side_effect=fetch)
        count = await loop_mod.expire_overdue(conn)
        self.assertEqual(count, 1)
        self.assertTrue(any("status = 'EXPIRED'" in c.args[0] for c in conn.execute.await_args_list))

    def test_loop_wired_into_lifespan(self):
        main = (ROOT / "main.py").read_text()
        self.assertIn("_payout_requisite_loop", main)
        self.assertIn("payout_requisite_task = asyncio.create_task", main)
        self.assertIn("payout_requisite_task.cancel()", main)
        staging_idx = main.find("staging_disable_background_tasks")
        self.assertGreater(staging_idx, 0)
        staging_block = main[staging_idx : staging_idx + 1800]
        self.assertIn("_payout_requisite_loop", staging_block)
        self.assertIn("init_bot_status_bridge", staging_block)

    async def test_tick_notifies_single_client_plus_doliv(self):
        import payout_requisite_loop as loop_mod
        from payout_requisite_matcher import Candidate, Plan

        loop_mod.reset_notification_state()

        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(return_value=555)
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        from datetime import datetime, timedelta, timezone

        row = {
            "id": 2,
            "operator_id": 5,
            "label": "Карта",
            "method": "card",
            "requisites": "2202200112345678",
            "amount_rub": Decimal("10000.00"),
            "paid_rub": Decimal("0.00"),
            "deadline_at": datetime.now(timezone.utc) + timedelta(hours=2),
        }
        plan = Plan(orders=[Candidate(order_id="S2", amount_kop=970000)], doliv_kop=30000)
        send = AsyncMock(return_value=1)

        with patch.object(loop_mod, "expire_overdue", new=AsyncMock(return_value=0)), patch.object(
            loop_mod, "active_requisites", new=AsyncMock(return_value=[row])
        ), patch.object(
            loop_mod,
            "plan_for_requisite",
            new=AsyncMock(return_value=(plan, Decimal("10000.00"))),
        ), patch.object(
            loop_mod, "store_plan", new=AsyncMock()
        ), patch(
            "telegram_notify.send_admin_message", new=send
        ):
            first = await loop_mod.run_tick(pool)

        self.assertEqual(first["notified"], 1)
        text = send.await_args.args[0]
        self.assertIn("S2", text)
        self.assertIn("долив", text.lower())

    async def test_tick_notifies_triangle_pure_doliv(self):
        import payout_requisite_loop as loop_mod
        from payout_requisite_matcher import Plan

        loop_mod.reset_notification_state()

        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(return_value=555)
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        from datetime import datetime, timedelta, timezone

        row = {
            "id": 8,
            "operator_id": 5,
            "label": "SELL S1",
            "method": "sbp",
            "requisites": "79991234567",
            "amount_rub": Decimal("5000.00"),
            "paid_rub": Decimal("3300.00"),
            "status": "PARTIAL",
            "source_sell_order_id": "S1",
            "deadline_at": datetime.now(timezone.utc) + timedelta(hours=2),
        }
        plan = Plan(orders=[], doliv_kop=170000, extra={"kind": "triangle"})
        send = AsyncMock(return_value=1)

        with patch.object(loop_mod, "expire_overdue", new=AsyncMock(return_value=0)), patch.object(
            loop_mod, "active_requisites", new=AsyncMock(return_value=[])
        ), patch.object(
            loop_mod, "active_payin_requisites", new=AsyncMock(return_value=[row])
        ), patch.object(
            loop_mod,
            "plan_for_requisite",
            new=AsyncMock(return_value=(plan, Decimal("1700.00"))),
        ), patch.object(
            loop_mod, "store_plan", new=AsyncMock()
        ), patch(
            "telegram_notify.send_admin_message", new=send
        ):
            first = await loop_mod.run_tick(pool)

        self.assertEqual(first["notified"], 1)
        text = send.await_args.args[0]
        self.assertIn("Треугольник", text)
        self.assertIn("S1", text)
        self.assertIn("долив", text.lower())


if __name__ == "__main__":
    unittest.main()
