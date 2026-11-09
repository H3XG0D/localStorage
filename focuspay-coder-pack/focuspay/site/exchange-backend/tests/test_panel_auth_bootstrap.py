"""Регрессия: panel auth bootstrap paths + client-side session gate (logic mirror)."""
from __future__ import annotations

import re
import unittest


_BOOTSTRAP_RE = re.compile(r"^/auth/(admin|operator)/login(/2fa)?$")


def is_panel_auth_bootstrap_path(path: str) -> bool:
    """Mirrors focussite/frontend/src/panel/lib/panelApi.ts isPanelAuthBootstrapPath."""
    p = path.replace("/api", "", 1) if path.startswith("/api") else path
    p = p.split("?")[0]
    return bool(_BOOTSTRAP_RE.match(p))


class PanelAuthBootstrapPathTests(unittest.TestCase):
    def test_login_allowed_without_token(self):
        self.assertTrue(is_panel_auth_bootstrap_path("/auth/operator/login"))
        self.assertTrue(is_panel_auth_bootstrap_path("/auth/admin/login/2fa"))
        self.assertTrue(is_panel_auth_bootstrap_path("/api/auth/operator/login"))

    def test_protected_paths_need_token(self):
        self.assertFalse(is_panel_auth_bootstrap_path("/operator/orders"))
        self.assertFalse(is_panel_auth_bootstrap_path("/api/operator/me"))
        self.assertFalse(is_panel_auth_bootstrap_path("/auth/operator/me"))
        self.assertFalse(is_panel_auth_bootstrap_path("/operator/ai/status"))


if __name__ == "__main__":
    unittest.main()
