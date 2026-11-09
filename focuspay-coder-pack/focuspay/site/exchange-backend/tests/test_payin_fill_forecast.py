"""Прогноз заливки payin-карты типичными BUY этого часа."""
from __future__ import annotations

import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from payin_fill_forecast import (
    DEFAULT_FIRST_CHECK_MINUTES,
    DEFAULT_GAP_MINUTES,
    FALLBACK_TYPICAL_RUB,
    build_split_payload,
    closing_splits,
    daytime_close_label,
    estimate_fill_minutes,
    fill_hint,
    forecast_payin_plan,
    format_fill_eta_minutes,
    hour_window,
    minutes_until_daytime_start,
    resolve_first_check_minutes,
    resolve_gap_minutes,
    resolve_typical_from_weekday,
    round_typical_rub,
    synthetic_candidates,
    typical_amounts_from_samples,
    weekday_label_ru,
    weekday_msk,
    weekday_past_label_ru,
)
from payout_requisite_matcher import to_kop


class TypicalAmountsTests(unittest.TestCase):
    def test_round_to_hundreds(self):
        self.assertEqual(round_typical_rub("3349"), 3300)
        self.assertEqual(round_typical_rub("3350"), 3400)

    def test_round_skips_null_and_garbage(self):
        self.assertEqual(round_typical_rub(None), 0)
        self.assertEqual(round_typical_rub(""), 0)
        self.assertEqual(round_typical_rub("not-a-number"), 0)
        amounts, source, raw = typical_amounts_from_samples(
            [{"fiat_amount": None}, {"fiat_amount": ""}, {"fiat_amount": 5000}] * 4
        )
        self.assertEqual(source, "mixed")
        self.assertEqual(raw, 4)
        self.assertEqual(amounts[0], 5000)

    def test_hour_window_wraps_midnight(self):
        self.assertEqual(hour_window(0), [23, 0, 1])
        self.assertEqual(hour_window(23), [22, 23, 0])

    def test_fallback_when_no_history(self):
        amounts, source, raw = typical_amounts_from_samples([])
        self.assertEqual(source, "fallback")
        self.assertEqual(raw, 0)
        self.assertEqual(amounts, list(FALLBACK_TYPICAL_RUB))

    def test_history_ranks_frequent_amounts(self):
        samples = [{"fiat_amount": 5000}] * 10 + [{"fiat_amount": 3300}] * 8
        amounts, source, raw = typical_amounts_from_samples(samples)
        self.assertEqual(source, "history")
        self.assertEqual(raw, 18)
        self.assertEqual(amounts[0], 5000)
        self.assertEqual(amounts[1], 3300)

    def test_synthetic_repeats_each_amount(self):
        cands = synthetic_candidates([5000, 7000], 3)
        self.assertEqual(len(cands), 6)
        self.assertEqual(cands[0].order_id, "typ:5000:1")
        self.assertEqual(cands[2].order_id, "typ:5000:3")
        self.assertEqual(cands[3].amount_kop, to_kop(7000))


class WeekdayTypicalTests(unittest.TestCase):
    def test_weekday_msk_saturday(self):
        sat = datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc)  # 16:00 MSK, суббота
        self.assertEqual(weekday_msk(sat), 6)
        self.assertEqual(weekday_label_ru(6), "суббота")
        self.assertEqual(weekday_past_label_ru(6), "субботам")

    def test_resolve_weekday_history(self):
        dow = [{"fiat_amount": 7000}] * 10
        fb = [{"fiat_amount": 3300}] * 10
        amounts, source, raw = resolve_typical_from_weekday(dow, fb)
        self.assertEqual(source, "weekday_history")
        self.assertEqual(raw, 10)
        self.assertEqual(amounts[0], 7000)

    def test_resolve_weekday_mixed(self):
        dow = [{"fiat_amount": 7000}] * 3
        fb = [{"fiat_amount": 3300}] * 10
        amounts, source, raw = resolve_typical_from_weekday(dow, fb)
        self.assertEqual(source, "weekday_mixed")
        self.assertGreaterEqual(raw, 3)
        self.assertIn(7000, amounts)

    def test_resolve_no_dow_falls_back_to_hour_window(self):
        amounts, source, raw = resolve_typical_from_weekday([], [])
        self.assertEqual(source, "fallback")
        self.assertEqual(raw, 0)
        self.assertEqual(amounts, list(FALLBACK_TYPICAL_RUB))

    def test_fill_hint_mentions_weekday(self):
        text = fill_hint(
            remaining_rub=26000,
            plan=None,
            typical=[5000, 7000],
            hour=16,
            max_checks=3,
            solo=False,
            source="weekday_history",
            weekday_past="субботам",
        )
        self.assertIn("По прошлым субботам", text or "")
        self.assertIn("16:00", text or "")


class FillEtaTests(unittest.TestCase):
    def test_format_fill_eta_minutes(self):
        self.assertEqual(format_fill_eta_minutes(45), "~45 минут")
        self.assertEqual(format_fill_eta_minutes(80), "~1 ч 20 минут")

    def test_estimate_fill_minutes_scales_with_checks(self):
        now = datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc)  # 16:00 MSK
        one = estimate_fill_minutes(
            checks_count=1, first_min=25, gap_min=30, now=now
        )
        three = estimate_fill_minutes(
            checks_count=3, first_min=25, gap_min=30, now=now
        )
        self.assertLess(one, three)
        self.assertEqual(one, 25)
        self.assertEqual(three, 85)

    def test_evening_adds_wait_until_daytime(self):
        evening = datetime(2026, 9, 5, 17, 0, tzinfo=timezone.utc)  # 20:00 MSK
        wait = minutes_until_daytime_start(evening)
        self.assertGreater(wait, 600)
        mins = estimate_fill_minutes(
            checks_count=1, first_min=25, gap_min=30, now=evening
        )
        self.assertEqual(mins, 25 + wait)

    def test_resolve_gap_weekday_history(self):
        gap, source, raw = resolve_gap_minutes(
            [{"gap_minutes": 20}] * 10,
            [{"gap_minutes": 40}] * 10,
        )
        self.assertEqual(source, "weekday_history")
        self.assertEqual(gap, 20)
        self.assertEqual(raw, 10)

    def test_resolve_first_check_fallback(self):
        first, source, raw = resolve_first_check_minutes([], [])
        self.assertEqual(source, "fallback")
        self.assertEqual(raw, 0)
        self.assertEqual(first, DEFAULT_FIRST_CHECK_MINUTES)

    def test_build_split_payload_eta_labels(self):
        now = datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc)
        payload = build_split_payload(
            [(10000, 8000, 8000), (15000, 11000)],
            first_min=25,
            gap_min=20,
            now=now,
        )
        self.assertEqual(payload[0]["checks_count"], 3)
        self.assertEqual(payload[1]["checks_count"], 2)
        self.assertEqual(payload[0]["fill_minutes"], 65)
        self.assertEqual(payload[1]["fill_minutes"], 45)
        self.assertTrue(str(payload[0]["fill_eta_label"]).startswith("~"))


class ClosingSplitTests(unittest.TestCase):
    def test_26000_proposes_10_8_8_and_15_11(self):
        splits = closing_splits(26000, 3)
        self.assertGreaterEqual(len(splits), 2)
        self.assertEqual(splits[0], (10000, 8000, 8000))
        self.assertEqual(splits[1], (15000, 11000))

    def test_evening_label_is_tomorrow_after_10(self):
        evening = datetime(2026, 9, 5, 17, 0, tzinfo=timezone.utc)  # 20:00 MSK
        self.assertEqual(daytime_close_label(evening), "завтра после 10:00 МСК")
        morning = datetime(2026, 9, 5, 6, 0, tzinfo=timezone.utc)  # 09:00 MSK
        self.assertEqual(daytime_close_label(morning), "сегодня после 10:00 МСК")

    def test_even_preferred_beats_uneven_history(self):
        weights = Counter({12000: 20, 7000: 20})
        splits = closing_splits(26000, 3, weights)
        self.assertEqual(splits[0], (10000, 8000, 8000))

    def test_5000_stays_one_check(self):
        splits = closing_splits(5000, 3)
        self.assertEqual(splits, [(5000,)])


class ForecastPlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_26000_closes_with_daytime_split(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=Decimal("0"))
        conn.fetch = AsyncMock(return_value=[])
        now = datetime(2026, 9, 5, 17, 0, tzinfo=timezone.utc)
        row = {
            "id": 6,
            "direction": "payin",
            "method": "card",
            "crypto": "usdt",
            "amount_rub": Decimal("26000"),
            "paid_rub": Decimal("0"),
            "max_checks": 3,
            "doliv_limit_rub": 2000,
            "created_at": now - timedelta(hours=2),
        }
        plan, free = await forecast_payin_plan(conn, row, now=now)
        self.assertEqual(free, Decimal("26000.00"))
        extra = plan.extra or {}
        self.assertEqual(extra.get("kind"), "forecast")
        self.assertTrue(plan.closes)
        self.assertEqual([c.amount_kop for c in plan.orders], [to_kop(10000), to_kop(8000), to_kop(8000)])
        self.assertEqual(extra.get("splits")[0]["checks"], [10000, 8000, 8000])
        self.assertEqual(extra.get("splits")[1]["checks"], [15000, 11000])
        self.assertIn("завтра после 10:00", extra.get("hint") or "")
        self.assertIn("10 000 + 8 000 + 8 000", extra.get("hint") or "")
        self.assertIn("15 000 + 11 000", extra.get("hint") or "")
        self.assertIn("комиссией", extra.get("hint") or "")
        self.assertEqual(extra.get("commission_note"), "К оплате с комиссией остаток будет меньше ввода.")
        self.assertEqual(extra.get("weekday_label"), "суббота")
        self.assertEqual(extra.get("weeks_looked"), 4)
        self.assertEqual(extra.get("gap_minutes"), DEFAULT_GAP_MINUTES)
        splits = extra.get("splits") or []
        self.assertTrue(splits[0].get("fill_eta_label"))
        self.assertTrue(splits[1].get("fill_eta_label"))
        self.assertLess(splits[1]["fill_minutes"], splits[0]["fill_minutes"])
        self.assertIn("~", extra.get("hint") or "")

    async def test_prefers_same_weekday_samples(self):
        now = datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc)
        dow = weekday_msk(now)

        async def fetch_side_effect(sql, *args):
            if "orders o" in sql:
                statuses, since, sub_token, coin, slots, weekday = args
                if weekday == dow and list(slots) == hour_window(16):
                    return [{"fiat_amount": 7000}] * 10
                if weekday is None and list(slots) == hour_window(16):
                    return [{"fiat_amount": 3300}] * 10
                return []
            if "gap_minutes" in sql:
                return [{"gap_minutes": 20}] * 10
            if "first_minutes" in sql:
                return [{"first_minutes": 25}] * 10
            return []

        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=Decimal("0"))
        conn.fetch = AsyncMock(side_effect=fetch_side_effect)
        row = {
            "id": 6,
            "direction": "payin",
            "method": "card",
            "crypto": "usdt",
            "amount_rub": Decimal("7000"),
            "paid_rub": Decimal("0"),
            "max_checks": 3,
            "doliv_limit_rub": 2000,
            "created_at": now - timedelta(hours=2),
        }
        plan, _free = await forecast_payin_plan(conn, row, now=now)
        extra = plan.extra or {}
        self.assertEqual(extra.get("source"), "weekday_history")
        self.assertEqual(extra.get("typical_rub")[0], 7000.0)
        self.assertIn("субботам", extra.get("hint") or "")

    async def test_first_hour_still_explains_solo_now(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=Decimal("0"))
        conn.fetch = AsyncMock(return_value=[])
        now = datetime.now(timezone.utc)
        row = {
            "id": 6,
            "direction": "payin",
            "method": "card",
            "crypto": "usdt",
            "amount_rub": Decimal("26000"),
            "paid_rub": Decimal("0"),
            "max_checks": 3,
            "doliv_limit_rub": 2000,
            "created_at": now - timedelta(minutes=5),
        }
        plan, _free = await forecast_payin_plan(conn, row, now=now)
        extra = plan.extra or {}
        self.assertTrue(extra.get("solo_window"))
        self.assertTrue(plan.closes)
        self.assertIn("Первый час", extra.get("now_hint") or "")

    def test_fill_hint_mentions_hour(self):
        text = fill_hint(
            remaining_rub=26000,
            plan=None,
            typical=[3300, 5000, 7000],
            hour=16,
            max_checks=3,
            solo=False,
        )
        self.assertIn("16:00", text)
