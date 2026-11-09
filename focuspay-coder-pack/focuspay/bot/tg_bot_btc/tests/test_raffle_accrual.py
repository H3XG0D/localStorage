"""FocusLucky raffle unit tests."""
import unittest
from unittest.mock import AsyncMock, MagicMock

from services.raffle_accrual import _tickets_for_volume, format_accrual_message
from services.raffle_constants import (
    format_prizes_block,
    format_chance_pct,
    format_ticket_numbers,
    win_chance_pct,
)
from services.raffle_db import find_ticket_owner


class FormatPrizesTests(unittest.TestCase):
    def test_prizes_block_lists_all_places(self):
        text = format_prizes_block()
        self.assertIn("1 место", text)
        self.assertIn("4–5 место", text)
        self.assertIn("6–10 место", text)
        self.assertNotIn("7 место", text)
        self.assertIn("5 000 ₽", text)
        self.assertNotIn("LTC", text)
        self.assertIn("баланс", text)


class DrawCountdownTests(unittest.TestCase):
    def test_campaign_schedule_30_days(self):
        from datetime import datetime, timedelta
        from services.raffle_constants import CAMPAIGN_DURATION_DAYS
        from services.raffle_schedule import MSK, campaign_schedule

        start = datetime(2026, 6, 1, 12, 0, 0, tzinfo=MSK)
        starts, ends, draw = campaign_schedule(start)
        self.assertEqual(starts, start)
        self.assertEqual(draw.date(), (start + timedelta(days=CAMPAIGN_DURATION_DAYS)).date())
        self.assertEqual(draw.hour, 20)
        self.assertEqual(ends, draw - timedelta(seconds=1))

    def test_ru_days_word(self):
        from services.raffle_db import _ru_days_word

        self.assertEqual(_ru_days_word(1), "день")
        self.assertEqual(_ru_days_word(2), "дня")
        self.assertEqual(_ru_days_word(5), "дней")
        self.assertEqual(_ru_days_word(21), "день")
        self.assertEqual(_ru_days_word(30), "дней")

    def test_countdown_line_uses_cherez(self):
        from datetime import datetime, timedelta
        from services.raffle_db import MSK, format_draw_countdown_line

        draw = datetime.now(MSK).date() + timedelta(days=30)
        draw_at = datetime(
            draw.year, draw.month, draw.day, 20, 0, 0, tzinfo=MSK
        )
        line = format_draw_countdown_line(draw_at)
        self.assertIn("через", line)
        self.assertIn("30", line)
        self.assertIn("дней", line)


class WinChanceTests(unittest.TestCase):
    def test_fifteen_of_fifteen_hundred(self):
        self.assertEqual(win_chance_pct(15, 1500), 1.0)

    def test_thirty_is_two_percent(self):
        self.assertEqual(win_chance_pct(30, 1500), 2.0)

    def test_zero_tickets(self):
        self.assertEqual(win_chance_pct(0, 1500), 0.0)

    def test_sole_player_is_100(self):
        self.assertEqual(win_chance_pct(1000, 1000), 100.0)

    def test_format_chance(self):
        self.assertEqual(format_chance_pct(10.0), "10%")
        self.assertEqual(format_chance_pct(0.3), "0.3%")


class TicketVolumeTests(unittest.TestCase):
    def test_floor_division(self):
        self.assertEqual(_tickets_for_volume(5500, 1000), 5)
        self.assertEqual(_tickets_for_volume(999, 1000), 0)
        self.assertEqual(_tickets_for_volume(9000, 3000), 3)


class FormatTicketNumbersTests(unittest.TestCase):
    def test_single_range(self):
        text = format_ticket_numbers([{"ticket_no_from": 1247, "ticket_no_to": 1261, "ticket_count": 15}])
        self.assertIn("#1247", text)
        self.assertIn("15", text)

    def test_empty(self):
        self.assertEqual(format_ticket_numbers([]), "—")


class AccrualMessageTests(unittest.TestCase):
    def test_own_accrual_message(self):
        msg = format_accrual_message(
            [
                {
                    "kind": "own",
                    "delta": 3,
                    "ticket_from": 10,
                    "ticket_to": 12,
                    "tickets_total": 15,
                    "win_chance_label": "10%",
                }
            ]
        )
        self.assertIn("15", msg)
        self.assertIn("10%", msg)
        self.assertIn("FocusLucky", msg)


class FindTicketOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_ordinal_maps_to_user(self):
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"user_id": 1, "ticket_no_from": 1, "ticket_no_to": 5, "ticket_count": 5},
            {"user_id": 2, "ticket_no_from": 6, "ticket_no_to": 10, "ticket_count": 5},
        ]
        owner = await find_ticket_owner(1, 8, conn)
        self.assertEqual(owner, (2, 8))

    async def test_exclude_user(self):
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"user_id": 1, "ticket_no_from": 1, "ticket_no_to": 5, "ticket_count": 5},
            {"user_id": 2, "ticket_no_from": 6, "ticket_no_to": 10, "ticket_count": 5},
        ]
        owner = await find_ticket_owner(1, 3, conn, exclude_users={1})
        self.assertEqual(owner, (2, 8))


class IdempotentAccrualTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_range_exists(self):
        from services.raffle_accrual import _allocate_ticket_range

        conn = AsyncMock()
        conn.fetchval.return_value = 1
        result = await _allocate_ticket_range(conn, 1, 42, "O1", "own", 5000, 3)
        self.assertIsNone(result)
        conn.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
