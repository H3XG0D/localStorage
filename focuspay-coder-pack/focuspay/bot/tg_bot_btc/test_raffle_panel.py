"""FocusLucky admin panel and accrual block tests."""
import unittest
from unittest.mock import AsyncMock, patch

from services.raffle_constants import (
    get_default_how_to_text,
    get_default_info_text,
    resolve_how_to_text,
    resolve_info_text,
)
from services.raffle_db import format_participant_admin_line


class CampaignTextTests(unittest.TestCase):
    def test_info_text_default_when_null(self):
        self.assertEqual(resolve_info_text(None), get_default_info_text())
        self.assertEqual(resolve_info_text({}), get_default_info_text())

    def test_info_text_custom(self):
        self.assertEqual(resolve_info_text({"info_text": "Свой текст"}), "Свой текст")

    def test_how_to_text_default_when_null(self):
        self.assertEqual(resolve_how_to_text(None), get_default_how_to_text())

    def test_how_to_text_custom(self):
        self.assertEqual(
            resolve_how_to_text({"how_to_text": "<b>Test</b>"}),
            "<b>Test</b>",
        )


class ParticipantLineTests(unittest.TestCase):
    def test_format_participant_line_chance(self):
        line = format_participant_admin_line(
            {
                "user_id": 12345,
                "username": "alice",
                "tickets_own": 10,
                "tickets_referral": 5,
                "tickets_total": 15,
                "accrual_blocked": False,
            },
            rank=1,
            pool_total=1500,
        )
        self.assertIn("12345", line)
        self.assertIn("@alice", line)
        self.assertIn("1%", line)
        self.assertIn("свои 10", line)

    def test_format_participant_blocked_marker(self):
        line = format_participant_admin_line(
            {
                "user_id": 1,
                "username": None,
                "tickets_own": 0,
                "tickets_referral": 0,
                "tickets_total": 0,
                "accrual_blocked": True,
            },
            rank=5,
            pool_total=100,
        )
        self.assertIn("🚫", line)


class AccrualBlockTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_user_skips_accrual(self):
        from services.raffle_accrual import _accrue_kind
        from services.raffle_constants import KIND_OWN

        conn = AsyncMock()
        campaign = {
            "id": 1,
            "rub_per_own_ticket": 1000,
            "rub_per_referral_ticket": 3000,
            "max_tickets_per_user": None,
        }
        with patch(
            "services.raffle_accrual.is_accrual_blocked",
            new=AsyncMock(return_value=True),
        ):
            result = await _accrue_kind(
                conn,
                campaign,
                42,
                "O1",
                KIND_OWN,
                5000.0,
                own_delta_rub=5000.0,
            )
        self.assertIsNone(result)
        conn.fetchrow.assert_not_called()

    async def test_unblocked_user_proceeds(self):
        from services.raffle_accrual import _accrue_kind
        from services.raffle_constants import KIND_OWN

        conn = AsyncMock()
        conn.fetchrow.return_value = None
        campaign = {
            "id": 1,
            "rub_per_own_ticket": 1000,
            "rub_per_referral_ticket": 3000,
            "max_tickets_per_user": None,
        }
        with patch(
            "services.raffle_accrual.is_accrual_blocked",
            new=AsyncMock(return_value=False),
        ):
            with patch(
                "services.raffle_accrual._upsert_participant_volumes",
                new=AsyncMock(return_value=(0, 0, 0, 0)),
            ):
                result = await _accrue_kind(
                    conn,
                    campaign,
                    42,
                    "O1",
                    KIND_OWN,
                    5000.0,
                    own_delta_rub=5000.0,
                )
        self.assertIsNone(result)


class ReferralAccrualTests(unittest.IsolatedAsyncioTestCase):
    async def test_partner_referrer_still_gets_tickets(self):
        """Реф. билеты FocusLucky — отдельно от партнёрской комиссии."""
        from services.raffle_accrual import _accrue_raffle_tickets

        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            {
                "order_id": "O1",
                "user_id": 100,
                "status": "PAID",
                "direction": "buy",
                "fiat_amount": 4920,
                "payout_confirmed_at": None,
                "updated_at": __import__("datetime").datetime(
                    2026, 6, 29, 12, 0, 0, tzinfo=__import__("datetime").timezone.utc
                ),
            },
            {"referrer_user_id": 200},
        ]
        campaign = {
            "id": 1,
            "starts_at": __import__("datetime").datetime(
                2026, 6, 1, 0, 0, 0, tzinfo=__import__("datetime").timezone.utc
            ),
            "ends_at": __import__("datetime").datetime(
                2026, 7, 31, 0, 0, 0, tzinfo=__import__("datetime").timezone.utc
            ),
            "min_order_rub": 500,
            "rub_per_own_ticket": 1000,
            "rub_per_referral_ticket": 3000,
            "max_tickets_per_user": None,
        }
        own_result = {"kind": "own", "delta": 4}
        ref_result = {"kind": "referral", "delta": 1}

        with patch(
            "services.raffle_accrual.get_active_campaign",
            new=AsyncMock(return_value=campaign),
        ):
            with patch(
                "services.raffle_accrual._accrue_kind",
                new=AsyncMock(side_effect=[own_result, ref_result]),
            ) as accrue:
                results = await _accrue_raffle_tickets(conn, "O1")

        self.assertEqual(len(results), 2)
        self.assertEqual(accrue.await_count, 2)
        ref_call = accrue.await_args_list[1]
        self.assertEqual(ref_call.args[2], 200)
        self.assertEqual(ref_call.kwargs.get("referral_delta_rub"), 4920)


if __name__ == "__main__":
    unittest.main()
