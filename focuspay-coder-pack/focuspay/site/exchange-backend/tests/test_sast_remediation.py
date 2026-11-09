"""SAST remediations that can be checked from source (no PyJWT install)."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SastRemediationSourceTests(unittest.TestCase):
    def test_auth_uses_pyjwt_not_jose(self):
        text = (ROOT / "auth.py").read_text()
        self.assertIn("import jwt", text)
        self.assertNotIn("jose", text.lower())

    def test_captcha_rng_is_secrets_not_random(self):
        src = (ROOT / "math_captcha.py").read_text()
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

    def test_requirements_pin_pyjwt_not_jose(self):
        text = (ROOT / "requirements.txt").read_text()
        self.assertIn("PyJWT", text)
        self.assertNotIn("python-jose", text)


if __name__ == "__main__":
    unittest.main()
