"""UI context anchors for Ops AI task drafting."""
from __future__ import annotations

import unittest

from ops_ai_ui_context import (
    UiContextValidationError,
    is_filing_desk,
    normalize_path,
    page_label,
    ui_anchor_lines,
    validate_ui_context,
)


class PageLabelTests(unittest.TestCase):
    def test_sticker_ai_label(self):
        self.assertIn("Sticker AI", page_label("/x8/sticker-ai"))
        self.assertIn("Sticker AI", page_label("/x8/sticker-ai/tasks/abc"))

    def test_ops_and_admin_known(self):
        self.assertEqual(page_label("/ops/chat"), "Чаты с клиентами")
        self.assertIn("AI-задач", page_label("/x8/ai-tasks"))

    def test_normalize_trailing_slash(self):
        self.assertEqual(normalize_path("/x8/sticker-ai/"), "/x8/sticker-ai")


class UiAnchorTests(unittest.TestCase):
    def test_anchor_mentions_path_and_rule(self):
        lines = ui_anchor_lines(
            {"path": "/x8/sticker-ai", "hint": "Sticker AI (брендовые стикеры)"}
        )
        blob = "\n".join(lines)
        self.assertIn("/x8/sticker-ai", blob)
        self.assertIn("Sticker AI", blob)
        self.assertIn("/exchange", blob)  # negative rule mentioned
        self.assertIn("источник правды", blob.lower() + blob)

    def test_empty_ui(self):
        self.assertEqual(ui_anchor_lines(None), [])
        self.assertEqual(ui_anchor_lines({}), [])

    def test_filing_desk_is_inbox_not_bug_screen(self):
        self.assertTrue(is_filing_desk("/ops/dev-requests"))
        self.assertTrue(is_filing_desk("/x8/ai-tasks/"))
        self.assertFalse(is_filing_desk("/ops/orders"))
        self.assertFalse(is_filing_desk("/x8/sticker-ai"))
        blob = "\n".join(
            ui_anchor_lines(
                {"path": "/ops/dev-requests", "hint": "Inbox: форма создания задачи, не баг-экран"}
            )
        )
        self.assertIn("inbox", blob.lower())
        self.assertIn("filed_from", blob)
        self.assertNotIn("источник правды про ЭКРАН", blob)
        self.assertIn("Telegram-бот", blob)
        self.assertIn("/exchange", blob)

    def test_validate_require_ai_tasks(self):
        ok = validate_ui_context(
            {"path": "/x8/ai-tasks", "hint": "Очередь AI-задач"},
            require_path="/x8/ai-tasks",
            require_hint_contains="AI-задач",
        )
        self.assertEqual(ok["path"], "/x8/ai-tasks")
        with self.assertRaises(UiContextValidationError):
            validate_ui_context(
                {"path": "/x8/orders", "hint": "Очередь AI-задач"},
                require_path="/x8/ai-tasks",
            )


if __name__ == "__main__":
    unittest.main()
