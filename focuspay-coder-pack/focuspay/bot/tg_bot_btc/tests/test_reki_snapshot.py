"""Разбор ответа бота на /reki и подбор суммы под свободный коридор."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.reki_snapshot import (  # noqa: E402
    FIT_EXACT,
    FIT_NONE,
    FIT_OVER_PAY,
    FIT_TOP_UP,
    SUB_TOKEN_CARD,
    SUB_TOKEN_SBP,
    describe_fit,
    fit_reki,
    format_snapshot,
    ops_summary_line,
    parse_reki_snapshot,
)

# Реальный ответ бота «ручные» на /reki (2026-11-02).
REKI_TEXT = """🟢 Количество активных СБП: 11
💸 Доступно всего:  78207 RUB
По лимитам: 
🟢 0 RUB - 2403 RUB

💸 Доступно: 2403 RUB

🟢 1500 RUB - 2000 RUB

💸 Доступно: 2000 RUB

🟢 3000 RUB - 3100 RUB

💸 Доступно: 3100 RUB

🟢 3029 RUB - 3129 RUB

💸 Доступно: 3129 RUB

🟢 3400 RUB - 3600 RUB

💸 Доступно: 3600 RUB

🟢 3500 RUB - 3600 RUB

💸 Доступно: 3600 RUB

🟢 4200 RUB - 5050 RUB

💸 Доступно: 5050 RUB

🟢 4300 RUB - 5050 RUB

💸 Доступно: 5050 RUB

🟢 4500 RUB - 4700 RUB

💸 Доступно: 9300 RUB

🟢 9000 RUB - 40975 RUB

💸 Доступно: 40975 RUB


🟢 Количество активных C2C: 15
💸 Доступно всего: 106202 RUB
По лимитам: 
🟢 2500 RUB - 2500 RUB

💸 Доступно: 2500 RUB

🟢 2750 RUB - 8100 RUB

💸 Доступно: 8100 RUB

🟢 3050 RUB - 3100 RUB

💸 Доступно: 3100 RUB

🟢 3300 RUB - 3500 RUB

💸 Доступно: 7000 RUB

🟢 3500 RUB - 3700 RUB

💸 Доступно: 3700 RUB

🟢 4000 RUB - 4200 RUB

💸 Доступно: 16600 RUB

🟢 4002 RUB - 4102 RUB

💸 Доступно: 4102 RUB

🟢 4500 RUB - 5050 RUB

💸 Доступно: 5050 RUB

🟢 5000 RUB - 5500 RUB

💸 Доступно: 5500 RUB

🟢 10000 RUB - 35350 RUB

💸 Доступно: 35350 RUB

🟢 15000 RUB - 15200 RUB

💸 Доступно: 15200 RUB



ℹ️Дополнительные реквизиты"""

NOW = datetime(2026, 11, 2, 22, 33, tzinfo=timezone.utc)


def _snapshot(text=REKI_TEXT, taken_at=NOW):
    return parse_reki_snapshot(text, taken_at=taken_at)


class ParseTests(unittest.TestCase):
    def test_sections_and_headers(self):
        snap = _snapshot()
        self.assertFalse(snap.empty)
        sbp = snap.section(SUB_TOKEN_SBP)
        card = snap.section(SUB_TOKEN_CARD)
        self.assertEqual(sbp.count, 11)
        self.assertEqual(sbp.total_rub, Decimal("78207.00"))
        self.assertEqual(card.count, 15)
        self.assertEqual(card.total_rub, Decimal("106202.00"))

    def test_bands_parsed(self):
        snap = _snapshot()
        sbp = snap.bands(SUB_TOKEN_SBP)
        card = snap.bands(SUB_TOKEN_CARD)
        # В тексте 10 полос СБП и 11 полос C2C — «активных» больше, чем коридоров.
        self.assertEqual(len(sbp), 10)
        self.assertEqual(len(card), 11)
        self.assertEqual(sbp[0].min_rub, Decimal("0.00"))
        self.assertEqual(sbp[0].max_rub, Decimal("2403.00"))
        self.assertEqual(sbp[-1].max_rub, Decimal("40975.00"))
        self.assertEqual(card[0].min_rub, Decimal("2500.00"))

    def test_available_can_be_multiple_of_max(self):
        snap = _snapshot()
        band = next(b for b in snap.bands(SUB_TOKEN_SBP) if b.max_rub == Decimal("4700.00"))
        self.assertEqual(band.available_rub, Decimal("9300.00"))
        self.assertEqual(band.slots, 2)

    def test_total_line_is_not_a_band(self):
        snap = _snapshot()
        for band in snap.bands(SUB_TOKEN_SBP):
            self.assertNotEqual(band.available_rub, Decimal("78207.00"))

    def test_empty_and_garbage(self):
        self.assertTrue(parse_reki_snapshot("", taken_at=NOW).empty)
        self.assertTrue(parse_reki_snapshot("ℹ️Дополнительные реквизиты", taken_at=NOW).empty)
        self.assertTrue(parse_reki_snapshot("🟢 3000 RUB - 3100 RUB", taken_at=NOW).empty)

    def test_single_method(self):
        text = "🟢 Количество активных СБП: 1\n💸 Доступно всего: 3100 RUB\n🟢 3000 RUB - 3100 RUB\n💸 Доступно: 3100 RUB"
        snap = parse_reki_snapshot(text, taken_at=NOW)
        self.assertEqual(len(snap.bands(SUB_TOKEN_SBP)), 1)
        self.assertEqual(snap.bands(SUB_TOKEN_CARD), ())

    def test_zero_available_band_dropped(self):
        text = "🟢 Количество активных СБП: 1\n💸 Доступно всего: 0 RUB\n🟢 3000 RUB - 3100 RUB\n💸 Доступно: 0 RUB"
        self.assertTrue(parse_reki_snapshot(text, taken_at=NOW).empty)


class FreshnessTests(unittest.TestCase):
    def test_fresh_within_ttl(self):
        snap = _snapshot()
        self.assertTrue(snap.is_fresh(ttl_seconds=300, now=NOW + timedelta(seconds=120)))
        self.assertFalse(snap.is_fresh(ttl_seconds=300, now=NOW + timedelta(seconds=600)))

    def test_stale_snapshot_gives_no_fit(self):
        snap = _snapshot()
        fit = fit_reki(snap, SUB_TOKEN_SBP, 3050, now=NOW + timedelta(hours=1))
        self.assertEqual(fit.kind, FIT_NONE)
        self.assertFalse(fit.found)


class FitTests(unittest.TestCase):
    def test_exact_band(self):
        fit = fit_reki(_snapshot(), SUB_TOKEN_SBP, 3050, now=NOW)
        self.assertEqual(fit.kind, FIT_EXACT)
        self.assertEqual(fit.pay_rub, Decimal("3050.00"))
        self.assertEqual(fit.diff_rub, Decimal("0.00"))
        self.assertIsNone(describe_fit(fit))

    def test_top_up_from_balance(self):
        # 2450 ₽ по СБП: коридоры 0–2403 и 3000–3100. Ближе доплата 47 ₽.
        fit = fit_reki(_snapshot(), SUB_TOKEN_SBP, 2450, now=NOW)
        self.assertEqual(fit.kind, FIT_TOP_UP)
        self.assertEqual(fit.pay_rub, Decimal("2403.00"))
        self.assertEqual(fit.diff_rub, Decimal("47.00"))
        self.assertIn("на 47 ₽ меньше запрошенной", describe_fit(fit))

    def test_over_pay_to_balance(self):
        # 2950 ₽ по СБП: до 2403 далеко, до 3000 всего 50 ₽ переплаты.
        fit = fit_reki(_snapshot(), SUB_TOKEN_SBP, 2950, now=NOW)
        self.assertEqual(fit.kind, FIT_OVER_PAY)
        self.assertEqual(fit.pay_rub, Decimal("3000.00"))
        self.assertEqual(fit.diff_rub, Decimal("50.00"))
        self.assertIn("на 50 ₽ больше запрошенной", describe_fit(fit))

    def test_above_everything_tops_up(self):
        fit = fit_reki(_snapshot(), SUB_TOKEN_SBP, 90000, now=NOW)
        self.assertEqual(fit.kind, FIT_TOP_UP)
        self.assertEqual(fit.pay_rub, Decimal("40975.00"))

    def test_card_pool_is_separate(self):
        # 2500 ₽ есть ровно в C2C и не покрывается СБП-коридором 1500–2000.
        self.assertEqual(fit_reki(_snapshot(), SUB_TOKEN_CARD, 2500, now=NOW).kind, FIT_EXACT)
        self.assertNotEqual(fit_reki(_snapshot(), SUB_TOKEN_SBP, 2500, now=NOW).kind, FIT_EXACT)

    def test_no_snapshot_or_bad_quote(self):
        self.assertEqual(fit_reki(None, SUB_TOKEN_SBP, 1000, now=NOW).kind, FIT_NONE)
        self.assertEqual(fit_reki(_snapshot(), SUB_TOKEN_SBP, 0, now=NOW).kind, FIT_NONE)


class RenderTests(unittest.TestCase):
    def test_format_snapshot_lists_both_methods(self):
        text = format_snapshot(_snapshot(), now=NOW)
        self.assertIn("СБП", text)
        self.assertIn("Карта (C2C)", text)
        self.assertIn("78 207 ₽", text)
        self.assertIn("Данные на 22:33 UTC", text)

    def test_format_snapshot_stale_and_empty(self):
        self.assertIn("устарел", format_snapshot(_snapshot(), now=NOW + timedelta(hours=1)))
        self.assertIn("нет", format_snapshot(parse_reki_snapshot("", taken_at=NOW), now=NOW))
        self.assertIn("нет", format_snapshot(None, now=NOW))

    def test_ops_summary_line(self):
        line = ops_summary_line(_snapshot(), now=NOW)
        self.assertIn("78 207 ₽ СБП", line)
        self.assertIn("106 202 ₽ Карта (C2C)", line)
        self.assertIsNone(ops_summary_line(_snapshot(), now=NOW + timedelta(hours=1)))
        self.assertIsNone(ops_summary_line(None, now=NOW))


if __name__ == "__main__":
    unittest.main()
