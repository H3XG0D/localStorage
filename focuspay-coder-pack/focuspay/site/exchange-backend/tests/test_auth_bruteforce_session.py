"""GET /auth/me is a session probe, not password guessing."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import security_threats as st
from security_threats import evaluate_threat, is_credential_auth_attempt


class AuthBruteforceSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        with st._lock:
            st._auth_fail_windows.clear()

    def tearDown(self) -> None:
        with st._lock:
            st._auth_fail_windows.clear()

    def test_login_paths_are_credential_attempts(self):
        self.assertTrue(is_credential_auth_attempt("POST", "/api/auth/login"))
        self.assertTrue(is_credential_auth_attempt("POST", "/api/auth/admin/login/2fa"))
        self.assertTrue(is_credential_auth_attempt("POST", "/api/auth/operator/login"))
        self.assertFalse(is_credential_auth_attempt("GET", "/api/auth/me"))
        self.assertFalse(is_credential_auth_attempt("GET", "/api/auth/admin/me"))
        self.assertFalse(is_credential_auth_attempt("POST", "/api/auth/logout"))
        self.assertFalse(is_credential_auth_attempt("POST", "/api/auth/me"))

    def test_repeated_auth_me_401_is_not_bruteforce(self):
        ip = "203.0.113.77"
        with patch.object(st.settings, "security_auth_fail_threshold", 5), patch.object(
            st.settings, "security_auth_fail_window_sec", 300
        ):
            for _ in range(20):
                threat, score = evaluate_threat(
                    ip=ip,
                    method="GET",
                    path="/api/auth/me",
                    status_code=401,
                    zone="auth",
                    scope=None,
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                )
                self.assertIsNone(threat)
                self.assertEqual(score, 0)
        with st._lock:
            self.assertNotIn(ip, st._auth_fail_windows)

    def test_admin_me_and_bot_wait_get_401_ignored(self):
        for path in (
            "/api/auth/admin/me",
            "/api/auth/operator/me",
            "/api/auth/telegram/bot-wait",
        ):
            threat, score = evaluate_threat(
                ip="198.51.100.20",
                method="GET",
                path=path,
                status_code=401,
                zone="auth",
                scope=None,
            )
            self.assertIsNone(threat)
            self.assertEqual(score, 0)

    def test_post_login_401_still_trips_bruteforce(self):
        ip = "203.0.113.88"
        last = (None, 0)
        with patch.object(st.settings, "security_auth_fail_threshold", 5), patch.object(
            st.settings, "security_auth_fail_window_sec", 300
        ):
            for _ in range(4):
                threat, score = evaluate_threat(
                    ip=ip,
                    method="POST",
                    path="/api/auth/admin/login",
                    status_code=401,
                    zone="auth",
                    scope=None,
                )
                self.assertIsNone(threat)
                self.assertEqual(score, 0)
            last = evaluate_threat(
                ip=ip,
                method="POST",
                path="/api/auth/admin/login",
                status_code=401,
                zone="auth",
                scope=None,
            )
        self.assertEqual(last, ("auth_bruteforce", 75))


if __name__ == "__main__":
    unittest.main()
