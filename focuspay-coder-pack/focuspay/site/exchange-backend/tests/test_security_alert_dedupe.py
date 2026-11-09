"""Регрессия: дедуп security alerts + loopback/selfcheck без Telegram-спама + trusted proxy IP."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import security_alerts as sa
from client_ip import get_client_ip
from security_threats import evaluate_threat


class SecurityAlertDedupeTests(unittest.TestCase):
    def setUp(self) -> None:
        sa.reset_alert_cooldowns_for_tests()

    def tearDown(self) -> None:
        sa.reset_alert_cooldowns_for_tests()

    def test_loopback_skipped_for_operator_probe(self):
        with patch.object(sa.settings, "security_alerts_enabled", True), patch.object(
            sa.settings, "telegram_bot_token", "x"
        ), patch.object(sa, "security_alert_chat_id", return_value=-100):
            self.assertFalse(
                sa.should_send_alert(
                    "127.0.0.1",
                    "operator_probe",
                    path="/api/operator/orders",
                    status_code=401,
                )
            )
            self.assertFalse(
                sa.should_send_alert(
                    "::1",
                    "admin_probe",
                    path="/api/admin/orders",
                    status_code=401,
                )
            )

    def test_selfcheck_ua_skipped(self):
        with patch.object(sa.settings, "security_alerts_enabled", True), patch.object(
            sa.settings, "telegram_bot_token", "tok"
        ), patch.object(sa, "security_alert_chat_id", return_value=-100):
            self.assertFalse(
                sa.should_send_alert(
                    "153.80.249.77",
                    "operator_probe",
                    path="/api/operator/orders",
                    status_code=401,
                    user_agent="FocusPay-SelfCheck/1.0",
                )
            )

    def test_routine_401_probe_is_not_telegram(self):
        with patch.object(sa.settings, "security_alerts_enabled", True), patch.object(
            sa.settings, "telegram_bot_token", "tok"
        ), patch.object(sa, "security_alert_chat_id", return_value=-100):
            self.assertFalse(
                sa.should_send_alert(
                    "203.0.113.50",
                    "admin_probe",
                    path="/api/admin/chat/unread-count",
                    status_code=401,
                )
            )
            self.assertFalse(
                sa.should_send_alert(
                    "203.0.113.50",
                    "operator_probe",
                    path="/api/operator/orders",
                    status_code=401,
                )
            )

    def test_bruteforce_still_alerts_then_cools_down(self):
        with patch.object(sa.settings, "security_alerts_enabled", True), patch.object(
            sa.settings, "telegram_bot_token", "tok"
        ), patch.object(sa.settings, "security_alert_cooldown_sec", 900), patch.object(
            sa, "security_alert_chat_id", return_value=-100
        ):
            self.assertTrue(
                sa.should_send_alert(
                    "203.0.113.50",
                    "auth_bruteforce",
                    path="/api/auth/admin/login",
                    status_code=401,
                )
            )
            self.assertFalse(
                sa.should_send_alert(
                    "203.0.113.50",
                    "auth_bruteforce",
                    path="/api/auth/admin/login",
                    status_code=401,
                )
            )

    def test_dangerous_alert_classification(self):
        self.assertTrue(sa.is_dangerous_alert("auth_bruteforce", 401))
        self.assertTrue(sa.is_dangerous_alert("unknown", 500))
        self.assertFalse(sa.is_dangerous_alert("operator_probe", 401))

    def test_is_loopback_helpers(self):
        self.assertTrue(sa.is_loopback_ip("127.0.0.1"))
        self.assertTrue(sa.is_loopback_ip("127.0.0.9"))
        self.assertTrue(sa.is_loopback_ip("::1"))
        self.assertFalse(sa.is_loopback_ip("153.80.249.77"))
        self.assertFalse(sa.is_loopback_ip(None))


class OperatorProbeClassificationTests(unittest.TestCase):
    def test_unauth_operator_401_is_probe(self):
        t, score = evaluate_threat(
            ip="203.0.113.9",
            method="GET",
            path="/api/operator/ai/status",
            status_code=401,
            zone="operator",
            scope=None,
        )
        self.assertEqual(t, "operator_probe")
        self.assertGreaterEqual(score, 1)

    def test_valid_operator_scope_not_probe(self):
        t, score = evaluate_threat(
            ip="203.0.113.9",
            method="GET",
            path="/api/operator/orders",
            status_code=401,
            zone="operator",
            scope="operator",
        )
        self.assertIsNone(t)
        self.assertEqual(score, 0)

    def test_selfcheck_is_internal_probe(self):
        t, score = evaluate_threat(
            ip="153.80.249.77",
            method="GET",
            path="/api/operator/orders",
            status_code=401,
            zone="operator",
            scope=None,
            user_agent="FocusPay-SelfCheck/1.0",
        )
        self.assertEqual(t, "internal_probe")
        self.assertEqual(score, 0)


class TrustedProxyIpTests(unittest.TestCase):
    def test_spoofed_xff_ignored_from_untrusted_peer(self):
        req = MagicMock()
        req.headers = {
            "x-forwarded-for": "203.0.113.99",
            "x-real-ip": "203.0.113.99",
            "cf-connecting-ip": "203.0.113.99",
        }
        req.client = MagicMock(host="198.51.100.50")  # not a trusted proxy
        self.assertEqual(get_client_ip(req), "198.51.100.50")

    def test_xff_honored_from_loopback_proxy(self):
        req = MagicMock()
        req.headers = {
            "cf-connecting-ip": "203.0.113.10",
            "x-real-ip": "198.51.100.1",
            "x-forwarded-for": "203.0.113.1",
        }
        req.client = MagicMock(host="127.0.0.1")
        self.assertEqual(get_client_ip(req), "203.0.113.10")


if __name__ == "__main__":
    unittest.main()
