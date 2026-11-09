"""FocusLucky live draw: HMAC places, chance, prize editor, payout keys. No DB."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from casino_raffle import (
    HMAC_ALGORITHM,
    chance_pct,
    commit_seed,
    hmac_index,
    make_seed,
    normalize_prize_places,
    payout_order_id,
    prize_pool_rub,
    verify_raffle_place,
    find_ticket_owner,
)


class RaffleShowMathTests(unittest.TestCase):
    def test_chance_is_share_of_remaining_not_times_places(self):
        self.assertEqual(chance_pct(15, 1500), 1.0)
        self.assertEqual(chance_pct(0, 100), 0.0)
        self.assertEqual(chance_pct(50, 50), 100.0)

    def test_hmac_index_is_stable_and_in_range(self):
        seed = "ab" * 32
        first = hmac_index(seed, 1, 1000)
        self.assertEqual(first, hmac_index(seed, 1, 1000))
        self.assertNotEqual(first, hmac_index(seed, 2, 1000))
        self.assertGreaterEqual(first, 0)
        self.assertLess(first, 1000)

    def test_commit_tamper_fails(self):
        seed = make_seed()
        commit = commit_seed(seed)
        remaining = 400
        index = hmac_index(seed, 1, remaining)
        ok = verify_raffle_place(
            seed=seed, commit=commit, place=1, remaining_tickets=remaining, expected_index=index
        )
        self.assertTrue(ok["matches"])
        self.assertEqual(ok["algorithm"], HMAC_ALGORITHM)
        bad = verify_raffle_place(
            seed=seed[:-1] + ("0" if seed[-1] != "0" else "1"),
            commit=commit,
            place=1,
            remaining_tickets=remaining,
            expected_index=index,
        )
        self.assertFalse(bad["commit_matches"])
        self.assertFalse(bad["matches"])

    def test_prize_editor_renumbers_and_forces_balance(self):
        places = normalize_prize_places(
            [
                {"place": 9, "prize_rub": "5000", "payout_method": "ltc"},
                {"prize_rub": 1000},
            ]
        )
        self.assertEqual(places[0]["place"], 1)
        self.assertEqual(places[1]["place"], 2)
        self.assertEqual(places[0]["payout_method"], "balance")
        self.assertEqual(float(prize_pool_rub(places)), 6000.0)

    def test_prize_editor_rejects_empty_and_zero(self):
        with self.assertRaises(ValueError):
            normalize_prize_places([])
        with self.assertRaises(ValueError):
            normalize_prize_places([{"prize_rub": 0}])

    def test_payout_ref_is_idempotent_per_place(self):
        self.assertEqual(payout_order_id(12, 3), payout_order_id(12, 3))
        self.assertNotEqual(payout_order_id(12, 3), payout_order_id(12, 4))

    def test_watch_url_rewrites_internal_hosts(self):
        from casino_raffle import watch_url

        with patch.dict("os.environ", {"PUBLIC_SITE_URL": "http://gateway:8080"}):
            self.assertEqual(watch_url(), "https://focuspay.org/casino/play/raffle")

    def test_notice_has_watch_button(self):
        import json

        from casino_raffle import started_html, telegram_notice_payload, watch_keyboard

        html = started_html(minutes=15, live=False)
        self.assertIn("15 мин", html)
        self.assertIn("/casino/play/raffle", html)
        payload = json.loads(telegram_notice_payload(42, html))
        self.assertEqual(payload["chat_id"], 42)
        self.assertEqual(payload["reply_markup"], watch_keyboard())
        self.assertIn("Смотреть", payload["reply_markup"]["inline_keyboard"][0][0]["text"])

    def test_drawing_phase_label(self):
        from raffle_phase import campaign_phase

        phase = campaign_phase({"status": "drawing"})
        self.assertEqual(phase["phase_label"], "Идёт живой розыгрыш")
        self.assertFalse(phase["accrual_open"])

    def test_prize_editor_rejects_too_many_places(self):
        with self.assertRaises(ValueError):
            normalize_prize_places([{"prize_rub": 100} for _ in range(21)])

    def test_dropout_picks_from_remaining_ranges(self):
        rows = [
            {"user_id": 1, "ticket_no_from": 1, "ticket_no_to": 10, "ticket_count": 10},
            {"user_id": 2, "ticket_no_from": 11, "ticket_no_to": 15, "ticket_count": 5},
        ]
        self.assertEqual(find_ticket_owner(rows, 1), (1, 1))
        self.assertEqual(find_ticket_owner(rows, 10), (1, 10))
        self.assertEqual(find_ticket_owner(rows, 11), (2, 11))
        remaining = [row for row in rows if int(row["user_id"]) != 1]
        self.assertEqual(find_ticket_owner(remaining, 1), (2, 11))

    def test_instant_run_draw_is_stubbed_out(self):
        from pathlib import Path

        src = Path(__file__).resolve().parents[1].joinpath("raffle_service.py").read_text()
        start = src.index("async def run_draw")
        end = src.index("async def pay_balance_winners")
        body = src[start:end]
        self.assertIn("start-show", body)
        self.assertNotIn("INSERT INTO raffle_winners", body)


class RaffleTimedShowTests(unittest.TestCase):
    def test_parse_draw_at_naive_is_msk(self):
        from casino_raffle import parse_draw_at

        dt = parse_draw_at("2026-09-01T20:00")
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.hour, 17)
        self.assertEqual(dt.day, 1)

    def test_parse_draw_at_explicit_offset(self):
        from casino_raffle import parse_draw_at

        dt = parse_draw_at("2026-09-01T20:00:00+03:00")
        self.assertEqual(dt.hour, 17)

    def test_autostart_skips_stale_draw_at(self):
        from casino_raffle import autostart_due

        draw = datetime(2026, 7, 29, 17, 0, tzinfo=timezone.utc)
        now = datetime(2026, 9, 1, 7, 5, tzinfo=timezone.utc)
        self.assertFalse(autostart_due(draw_at=draw, now=now))
        live = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
        self.assertTrue(autostart_due(draw_at=live, now=live + timedelta(minutes=1)))
        self.assertFalse(autostart_due(draw_at=live, now=live - timedelta(minutes=1)))
        self.assertFalse(autostart_due(draw_at=live, now=live + timedelta(hours=3)))

    def test_due_milestones_exclusive_windows(self):
        from casino_raffle import due_notify_milestones

        draw = datetime(2026, 9, 1, 17, 0, tzinfo=timezone.utc)

        def due(minutes_before: float, sent: set[int] | None = None) -> list[int]:
            now = draw - timedelta(minutes=minutes_before)
            return due_notify_milestones(draw_at=draw, now=now, sent=sent or set())

        self.assertEqual(due(5), [10])
        self.assertEqual(due(120), [180])
        self.assertEqual(due(7 * 60), [])
        self.assertEqual(due(6 * 60), [360])
        self.assertEqual(due(181), [360])
        self.assertEqual(due(180), [180])
        self.assertEqual(due(61), [180])
        self.assertEqual(due(60), [60])
        self.assertEqual(due(11), [60])
        self.assertEqual(due(10), [10])
        self.assertEqual(due(5, sent={10}), [])
        self.assertEqual(
            due_notify_milestones(draw_at=draw, now=draw, sent=set()),
            [],
        )

    def test_soon_html_mentions_today_and_msk(self):
        from casino_raffle import soon_html

        draw = datetime(2026, 9, 1, 17, 0, tzinfo=timezone.utc)
        today = soon_html(minutes=360, draw_at=draw)
        self.assertIn("сегодня", today)
        self.assertIn("20:00 МСК", today)
        self.assertIn("/casino/play/raffle", today)
        hour = soon_html(minutes=60, draw_at=draw)
        self.assertIn("через час", hour)
        ten = soon_html(minutes=10, draw_at=draw)
        self.assertIn("10 мин", ten)

    def test_spin_interval_floor_is_12(self):
        from casino_raffle import clamp_spin_interval

        with self.assertRaises(ValueError):
            clamp_spin_interval(10)
        self.assertEqual(clamp_spin_interval(12), 12)

    def test_winner_chance_uses_tickets_at_settle(self):
        self.assertEqual(chance_pct(15, 1500), 1.0)
        self.assertEqual(chance_pct(50, 200), 25.0)


if __name__ == "__main__":
    unittest.main()
