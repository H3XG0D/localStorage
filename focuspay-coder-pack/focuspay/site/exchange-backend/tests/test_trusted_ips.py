"""Owner/office trusted IPs: exact match + CIDR, IPv6 compression."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import ip_blocklist as bl
import security_alerts as sa
import trusted_ips as ti
from security_threats import evaluate_threat, record_auth_failure


class TrustedIpCidrTests(unittest.TestCase):
    def setUp(self) -> None:
        ti.clear_trusted_ip_caches()
        sa.reset_alert_cooldowns_for_tests()
        with bl._lock:
            bl._blocked.clear()
        bl._redis_checked = True
        bl._redis_client = None

    def tearDown(self) -> None:
        ti.clear_trusted_ip_caches()
        sa.reset_alert_cooldowns_for_tests()
        with bl._lock:
            bl._blocked.clear()
        bl._redis_checked = False
        bl._redis_client = None

    def test_ipv6_prefix_covers_privacy_address(self):
        with patch.object(
            ti.settings, "security_trusted_ips", "217.60.34.122,2403:6200:8871:6a71::/64"
        ):
            ti.clear_trusted_ip_caches()
            self.assertTrue(ti.is_trusted_ip("2403:6200:8871:6a71::a"))
            self.assertTrue(ti.is_trusted_ip("2403:6200:8871:6a71::4"))
            self.assertTrue(ti.is_trusted_ip("2403:6200:8871:6a71:0:0:0:a"))
            self.assertTrue(ti.is_trusted_ip("[2403:6200:8871:6a71::a]"))
            self.assertTrue(ti.is_trusted_ip("217.60.34.122"))
            self.assertFalse(ti.is_trusted_ip("2403:6200:8871:6a72::a"))
            self.assertFalse(ti.is_trusted_ip("203.0.113.50"))

    def test_exact_ipv6_compressed_vs_exploded(self):
        with patch.object(ti.settings, "security_trusted_ips", "2403:6200:8871:6a71::4"):
            ti.clear_trusted_ip_caches()
            self.assertTrue(ti.is_trusted_ip("2403:6200:8871:6a71:0:0:0:4"))
            self.assertFalse(ti.is_trusted_ip("2403:6200:8871:6a71::a"))

    def test_trusted_cidr_not_banned_even_if_key_exists(self):
        with patch.object(ti.settings, "security_trusted_ips", "2403:6200:8871:6a71::/64"):
            ti.clear_trusted_ip_caches()
            bl.ban_ip("2403:6200:8871:6a71::a", duration_sec=600, reason="auth_bruteforce")
            self.assertFalse(bl.is_ip_banned("2403:6200:8871:6a71::a"))

    def test_evaluate_threat_skips_trusted(self):
        with patch.object(ti.settings, "security_trusted_ips", "2403:6200:8871:6a71::/64"):
            ti.clear_trusted_ip_caches()
            t, score = evaluate_threat(
                ip="2403:6200:8871:6a71::a",
                method="POST",
                path="/api/auth/admin/login",
                status_code=401,
                zone="auth",
                scope=None,
            )
            self.assertIsNone(t)
            self.assertEqual(score, 0)
            self.assertIsNone(record_auth_failure("2403:6200:8871:6a71::a"))

    def test_alerts_skip_trusted_bruteforce(self):
        with patch.object(ti.settings, "security_trusted_ips", "2403:6200:8871:6a71::/64"), patch.object(
            sa.settings, "security_alerts_enabled", True
        ), patch.object(sa.settings, "telegram_bot_token", "tok"), patch.object(
            sa, "security_alert_chat_id", return_value=-100
        ):
            ti.clear_trusted_ip_caches()
            self.assertFalse(
                sa.should_send_alert(
                    "2403:6200:8871:6a71::a",
                    "auth_bruteforce",
                    path="/api/auth/admin/login",
                    status_code=401,
                )
            )


if __name__ == "__main__":
    unittest.main()
