"""App IP bans (Redis key ban:{ip} + memory fallback) including IPv6 unban."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import ip_blocklist as bl
import security_threats as st


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def ping(self) -> bool:
        return True

    def setex(self, key: str, _ttl: int, value: str) -> bool:
        self.store[key] = value
        return True

    def exists(self, key: str) -> int:
        return int(key in self.store)

    def get(self, key: str):
        return self.store.get(key)

    def ttl(self, key: str) -> int:
        return 3600 if key in self.store else -2

    def delete(self, *keys: str) -> int:
        n = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                n += 1
        return n

    def scan_iter(self, match: str = "*", count: int = 200):
        import fnmatch

        for key in list(self.store):
            if fnmatch.fnmatch(key, match):
                yield key


class IpBlocklistUnbanTests(unittest.TestCase):
    def setUp(self) -> None:
        with bl._lock:
            bl._blocked.clear()
        bl._redis_checked = True
        bl._redis_client = None
        with st._lock:
            st._auth_fail_windows.clear()

    def tearDown(self) -> None:
        with bl._lock:
            bl._blocked.clear()
        bl._redis_checked = False
        bl._redis_client = None
        with st._lock:
            st._auth_fail_windows.clear()

    def test_memory_ban_unban_ipv4(self):
        ip = "203.0.113.50"
        bl.ban_ip(ip, duration_sec=600, reason="auth_bruteforce")
        self.assertTrue(bl.is_ip_banned(ip))
        first = bl.unban_ip(ip)
        self.assertTrue(first["ok"])
        self.assertTrue(first["was_banned"])
        self.assertFalse(bl.is_ip_banned(ip))
        second = bl.unban_ip(ip)
        self.assertTrue(second["ok"])
        self.assertFalse(second["was_banned"])

    def test_memory_unban_ipv6_variants(self):
        ip = "2403:6200:8871:6a71::4"
        bl.ban_ip(ip, duration_sec=600, reason="auth_bruteforce")
        self.assertTrue(bl.is_ip_banned(ip))
        result = bl.unban_ip("2403:6200:8871:6a71:0:0:0:4")
        self.assertTrue(result["ok"])
        self.assertTrue(result["was_banned"])
        self.assertFalse(bl.is_ip_banned(ip))

    def test_unban_ipv6_with_cidr_suffix(self):
        ip = "2403:6200:8871:6a71::4"
        bl.ban_ip(ip, duration_sec=600, reason="auth_bruteforce")
        result = bl.unban_ip(ip + "/128")
        self.assertTrue(result["was_banned"])
        self.assertFalse(bl.is_ip_banned(ip))

    def test_redis_unban_ipv6_and_list(self):
        fake = FakeRedis()
        bl._redis_client = fake
        ip = "2403:6200:8871:6a71::4"
        bl.ban_ip(ip, duration_sec=600, reason="auth_bruteforce")
        self.assertEqual(fake.store.get(f"ban:{ip}"), "auth_bruteforce")
        self.assertTrue(bl.is_ip_banned(ip))
        listed = bl.list_bans()
        self.assertEqual(listed[0]["ip"], ip)
        self.assertEqual(listed[0]["reason"], "auth_bruteforce")
        result = bl.unban_ip(f"[{ip}]")
        self.assertTrue(result["was_banned"])
        self.assertEqual(result["reason"], "auth_bruteforce")
        self.assertNotIn(f"ban:{ip}", fake.store)
        self.assertFalse(bl.is_ip_banned(ip))
        again = bl.unban_ip(ip)
        self.assertTrue(again["ok"])
        self.assertFalse(again["was_banned"])

    def test_unban_clears_auth_fail_window(self):
        ip = "198.51.100.9"
        with st._lock:
            st._auth_fail_windows[ip] = [1.0, 2.0, 3.0]
        bl.ban_ip(ip, duration_sec=120, reason="auth_bruteforce")
        bl.unban_ip(ip)
        with st._lock:
            self.assertNotIn(ip, st._auth_fail_windows)

    def test_unban_skips_relative_fail2ban_script(self):
        with patch.object(bl.settings, "security_fail2ban_bridge", True), patch.object(
            bl.settings, "security_fail2ban_bridge_script", "unban.sh"
        ), patch.object(bl, "subprocess") as sp, patch.object(bl.os.path, "isfile", return_value=True):
            bl._maybe_fail2ban_unban("192.0.2.8")
            sp.run.assert_not_called()

    def test_unban_skips_invalid_ip(self):
        with patch.object(bl.settings, "security_fail2ban_bridge", True), patch.object(
            bl.settings, "security_fail2ban_bridge_script", "/opt/focuspay/ban-bridge.sh"
        ), patch.object(bl, "subprocess") as sp, patch.object(bl.os.path, "isfile", return_value=True):
            bl._maybe_fail2ban_unban("not-an-ip; rm -rf /")
            sp.run.assert_not_called()

    def test_unban_runs_allowlisted_argv(self):
        with patch.object(bl.settings, "security_fail2ban_bridge", True), patch.object(
            bl.settings, "security_fail2ban_bridge_script", "/opt/focuspay/ban-bridge.sh"
        ), patch.object(bl, "subprocess") as sp, patch.object(bl.os.path, "isfile", return_value=True):
            bl._maybe_fail2ban_unban("192.0.2.8")
            sp.run.assert_called_once()
            argv = sp.run.call_args[0][0]
            self.assertEqual(argv, ["/opt/focuspay/ban-bridge.sh", "unban", "192.0.2.8"])

    def test_never_bans_loopback(self):
        bl.ban_ip("127.0.0.1", duration_sec=600, reason="auth_bruteforce")
        self.assertFalse(bl.is_ip_banned("127.0.0.1"))
        bl.ban_ip("::1", duration_sec=600, reason="auth_bruteforce")
        self.assertFalse(bl.is_ip_banned("::1"))

    def test_never_bans_on_staging(self):
        ip = "203.0.113.77"
        with patch.object(bl.settings, "environment", "staging"):
            bl.ban_ip(ip, duration_sec=600, reason="auth_bruteforce")
            self.assertFalse(bl.is_ip_banned(ip))


if __name__ == "__main__":
    unittest.main()
