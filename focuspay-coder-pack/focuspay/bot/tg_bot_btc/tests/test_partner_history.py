"""История партнёра: плюс по сделке виден, hold партнёрского леджера скрыт."""
import unittest
from datetime import datetime, timezone

from services.partner_db import format_partner_history_message, merge_partner_history_rows


def _row(kind, amount, note, created, **extra):
    return {
        "type": kind,
        "amount_rub": amount,
        "note": note,
        "created_at": created,
        **extra,
    }


class PartnerHistoryTests(unittest.TestCase):
    def test_partner_accrual_hides_profit_note_and_drops_hold(self):
        older = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
        newer = datetime(2026, 10, 11, 14, 5, tzinfo=timezone.utc)
        referral = [
            _row("accrual", 40, "5% от прибыли 800.00 ₽, сделка OLD1", older),
            _row("hold", -10, "Резерв реферального баланса", older),
        ]
        partner = [
            _row("hold", -50, "Резерв партнёрского баланса", newer),
            _row(
                "accrual",
                120.5,
                "12% (tier) от прибыли 1004.17 ₽ по сделке NEW9",
                newer,
            ),
        ]

        picked = merge_partner_history_rows(referral, partner)
        kinds = [row["type"] for row in picked]
        self.assertEqual(kinds, ["accrual", "accrual", "hold"])
        self.assertEqual(picked[0]["amount_rub"], 120.5)

        text = format_partner_history_message(picked)
        self.assertNotIn("12% (tier) от прибыли 1004.17 ₽ по сделке NEW9", text)
        self.assertNotIn("от прибыли", text)
        self.assertNotIn("NEW9", text)
        self.assertIn("+120.50 ₽", text)
        self.assertNotIn("5% от прибыли 800.00 ₽, сделка OLD1", text)
        self.assertNotIn("Резерв партнёрского баланса", text)
        self.assertIn("Резерв реферального баланса", text)

    def test_note_is_escaped_and_limit_keeps_newest(self):
        rows = [
            _row(
                "accrual",
                1 + i,
                f"плюс <{i}>",
                datetime(2026, 1, 1, 0, i, tzinfo=timezone.utc),
            )
            for i in range(20)
        ]
        picked = merge_partner_history_rows([], rows, limit=15)
        self.assertEqual(len(picked), 15)
        self.assertEqual(picked[0]["amount_rub"], 20)
        text = format_partner_history_message(picked[:1])
        self.assertIn("плюс &lt;19&gt;", text)
        self.assertNotIn("плюс <19>", text)

    def test_empty_history(self):
        self.assertEqual(merge_partner_history_rows([], []), [])
        self.assertEqual(format_partner_history_message([]), "")
