"""Premium stickers from a Telegram message survive as <tg-emoji>."""
from __future__ import annotations

import unittest

from services.broadcast_html import is_broadcast_copy_account, message_to_broadcast_html
from services.text_sanitize import sanitize_telegram_html

CHECK = "5206607081334906820"
STAR = "5438496463044752972"


class _Ent:
    def __init__(self, kind: str, offset: int, length: int, **extra):
        self.type = kind
        self.offset = offset
        self.length = length
        for key, value in extra.items():
            setattr(self, key, value)


class BroadcastHtmlTests(unittest.TestCase):
    def test_copy_account_username(self):
        self.assertTrue(is_broadcast_copy_account("absoluteop"))
        self.assertTrue(is_broadcast_copy_account("@AbsoluteOp"))
        self.assertFalse(is_broadcast_copy_account("someone"))
        self.assertFalse(is_broadcast_copy_account(None))

    def test_plain_text_stays_plain(self):
        self.assertEqual(message_to_broadcast_html("Просто текст", []), "Просто текст")

    def test_keyboard_emoji_becomes_nearest_premium(self):
        out = message_to_broadcast_html("Старт 🚀 скорость ⚡️", [])
        self.assertIn('<tg-emoji emoji-id="5424818078833715060">📢</tg-emoji>', out)
        self.assertIn('<tg-emoji emoji-id="5424972470023104089">🔥</tg-emoji>', out)
        self.assertNotIn("🚀", out)
        self.assertNotIn("⚡", out)

    def test_pack_unicode_becomes_tag(self):
        out = message_to_broadcast_html("Готово ✅", [])
        self.assertIn(f'<tg-emoji emoji-id="{CHECK}">✅</tg-emoji>', out)
        self.assertNotIn("🚀", out)

    def test_custom_emoji_keeps_id_after_astral_char(self):
        text = "🚀⭐"
        # 🚀 is two UTF-16 units, ⭐ is one.
        out = message_to_broadcast_html(
            text,
            [_Ent("custom_emoji", 2, 1, custom_emoji_id="99999")],
        )
        self.assertIn('<tg-emoji emoji-id="5424818078833715060">📢</tg-emoji>', out)
        self.assertIn('<tg-emoji emoji-id="99999">⭐</tg-emoji>', out)
        self.assertEqual(out.count("<tg-emoji"), 2)

    def test_known_pack_id_not_doubled(self):
        out = message_to_broadcast_html(
            "⭐",
            [_Ent("custom_emoji", 0, 1, custom_emoji_id=STAR)],
        )
        self.assertEqual(out, f'<tg-emoji emoji-id="{STAR}">⭐</tg-emoji>')

    def test_overlapping_bold_and_link_stay_nested(self):
        import re

        text = "Hello FocusVPN world"
        out = message_to_broadcast_html(
            text,
            [
                _Ent("bold", 0, 10),
                _Ent("text_link", 6, 10, url="https://t.me/focusvpn1_bot"),
            ],
        )
        self.assertIn('<a href="https://t.me/focusvpn1_bot">', out)
        stack: list[str] = []
        for token in re.findall(r"</?[a-z-]+(?:\s[^>]*)?>", out):
            closing = token.startswith("</")
            name = token.strip("<>/").split()[0]
            if closing:
                self.assertEqual(stack.pop(), name)
            else:
                stack.append(name)
        self.assertEqual(stack, [])

    def test_bold_wraps_custom_emoji(self):
        out = message_to_broadcast_html(
            "A⭐",
            [
                _Ent("bold", 0, 2),
                _Ent("custom_emoji", 1, 1, custom_emoji_id="99999"),
            ],
        )
        self.assertEqual(out, '<b>A<tg-emoji emoji-id="99999">⭐</tg-emoji></b>')

    def test_sanitize_keeps_premium_tag(self):
        raw = f'Привет <tg-emoji emoji-id="{CHECK}">✅</tg-emoji>'
        out = sanitize_telegram_html(raw)
        self.assertIn(f'<tg-emoji emoji-id="{CHECK}">✅</tg-emoji>', out)
        self.assertNotIn("&lt;tg-emoji", out)


if __name__ == "__main__":
    unittest.main()
