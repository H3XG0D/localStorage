"""Captcha RNG must not use the stdlib random module (Bandit B311)."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BotCaptchaRngTests(unittest.TestCase):
    def test_bot_captcha_uses_secrets(self):
        src = (ROOT / "services" / "bot_captcha.py").read_text()
        tree = ast.parse(src)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        from_imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertIn("secrets", imported)
        self.assertNotIn("random", imported)
        self.assertNotIn("random", from_imported)


if __name__ == "__main__":
    unittest.main()
