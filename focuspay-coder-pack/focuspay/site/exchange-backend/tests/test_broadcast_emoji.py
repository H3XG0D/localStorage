"""Premium emoji tags in broadcast text."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from broadcast_emoji import apply_premium_emoji, fit_premium_text
from text_sanitize import sanitize_telegram_html

CHECK = "5206607081334906820"
INFO = "5323442290708985472"


class PremiumEmojiTests(unittest.TestCase):
    def test_unique_unicode_becomes_tag(self):
        out = apply_premium_emoji("Готово ✅")
        self.assertIn(f'<tg-emoji emoji-id="{CHECK}">✅</tg-emoji>', out)
        self.assertIn("Готово", out)

    def test_info_without_variation_selector(self):
        out = apply_premium_emoji("Важно \u2139")
        self.assertIn(INFO, out)

    def test_shared_fallback_stays_plain(self):
        out = apply_premium_emoji("Курс 💵 и карта 💳")
        self.assertNotIn("tg-emoji", out)
        self.assertIn("💵", out)

    def test_existing_tag_not_doubled(self):
        tag = f'<tg-emoji emoji-id="{CHECK}">✅</tg-emoji>'
        self.assertEqual(apply_premium_emoji(f"A {tag} B"), f"A {tag} B")

    def test_dirty_tag_loses_attributes_and_keeps_glyph(self):
        raw = f'<tg-emoji emoji-id="{CHECK}" onclick="alert(1)">✅</tg-emoji>'
        out = apply_premium_emoji(raw)
        self.assertNotIn("onclick", out)
        self.assertIn(f'<tg-emoji emoji-id="{CHECK}">✅</tg-emoji>', out)

    def test_foreign_custom_emoji_kept(self):
        tag = '<tg-emoji emoji-id="5425089761285001463">🎰</tg-emoji>'
        out = apply_premium_emoji(f"Игра {tag} и готово ✅")
        self.assertIn(tag, out)
        self.assertIn(CHECK, out)
        self.assertNotIn("🚀", out)

    def test_short_unknown_id_unwrapped(self):
        out = apply_premium_emoji('<tg-emoji emoji-id="1234">🎰</tg-emoji>')
        self.assertNotIn("tg-emoji", out)
        self.assertIn("🎰", out)

    def test_html_around_emoji_survives(self):
        out = apply_premium_emoji("<b>Запуск</b> ✅")
        self.assertIn("<b>Запуск</b>", out)
        self.assertIn(CHECK, out)

    def test_keyboard_emoji_becomes_nearest_premium(self):
        out = apply_premium_emoji("Старт 🚀")
        self.assertEqual(
            out,
            'Старт <tg-emoji emoji-id="5424818078833715060">📢</tg-emoji>',
        )

    def test_fit_unwraps_instead_of_cutting_a_tag(self):
        tag = f'<tg-emoji emoji-id="{CHECK}">✅</tg-emoji>'
        text = ("а" * 20) + tag
        out = fit_premium_text(text, max_len=22)
        self.assertNotIn("<tg-emoji", out)
        self.assertTrue(out.endswith("✅"))
        self.assertLessEqual(len(out), 22)

    def test_sanitize_then_upgrade_keeps_bold(self):
        cleaned = sanitize_telegram_html("<b>Сервис</b>\n✅")
        out = fit_premium_text(apply_premium_emoji(cleaned))
        self.assertIn("<b>Сервис</b>", out)
        self.assertIn(CHECK, out)

    def test_catalog_matches_bot(self):
        bot = Path(__file__).resolve().parents[3] / "bot/tg_bot_btc/services/tg_emoji.py"
        text = bot.read_text(encoding="utf-8")
        pairs = re.findall(r'"(\w+)": \("(\d*)", "([^"]*)"\)', text)
        self.assertGreaterEqual(len(pairs), 30)
        from broadcast_emoji import EMOJI

        for key, eid, fb in pairs:
            self.assertIn(key, EMOJI)
            self.assertEqual(EMOJI[key], (eid, fb))


if __name__ == "__main__":
    unittest.main()
