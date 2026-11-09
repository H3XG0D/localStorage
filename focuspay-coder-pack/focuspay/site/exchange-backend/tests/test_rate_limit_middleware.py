"""Authed casino play must not fill the scanner IP rate-limit bucket."""
from __future__ import annotations

import unittest

from rate_limit_middleware import (
    _INTERNAL_API_PREFIX,
    _is_public_readonly_api,
    skips_ip_rate_limit,
)


class AuthedCasinoRateLimitSkipTests(unittest.TestCase):
    def test_play_quote_balance_and_me_skip_when_bearer_present(self):
        self.assertTrue(skips_ip_rate_limit("/api/user/casino/play", has_bearer=True))
        self.assertTrue(skips_ip_rate_limit("/api/public/casino/play/quote", has_bearer=True))
        self.assertTrue(skips_ip_rate_limit("/api/public/casino/play/tape", has_bearer=True))
        self.assertTrue(skips_ip_rate_limit("/api/user/balance", has_bearer=True))
        self.assertTrue(skips_ip_rate_limit("/api/auth/me", has_bearer=True))

    def test_anonymous_play_and_login_still_count(self):
        self.assertFalse(skips_ip_rate_limit("/api/user/casino/play", has_bearer=False))
        self.assertFalse(skips_ip_rate_limit("/api/public/casino/play/quote", has_bearer=False))
        self.assertFalse(skips_ip_rate_limit("/api/auth/login", has_bearer=False))
        self.assertFalse(skips_ip_rate_limit("/api/auth/login", has_bearer=True))
        self.assertFalse(skips_ip_rate_limit("/api/user/orders", has_bearer=True))

    def test_internal_casino_is_service_prefix_not_scanner_play_skip(self):
        self.assertTrue("/api/internal/casino/v2/tables".startswith(_INTERNAL_API_PREFIX))
        self.assertFalse(skips_ip_rate_limit("/api/internal/casino/v2/tables", has_bearer=False))
        self.assertFalse(skips_ip_rate_limit("/api/internal/casino/v2/tables", has_bearer=True))

    def test_casino_avatar_get_skips_ip_ban_bucket(self):
        self.assertTrue(_is_public_readonly_api("/api/public/casino-avatars/n1", "GET"))
        self.assertTrue(_is_public_readonly_api("/api/public/casino-idents/u41", "GET"))
        self.assertTrue(_is_public_readonly_api("/api/public/bot-user-avatars/41", "GET"))
        self.assertFalse(_is_public_readonly_api("/api/public/casino-avatars/n1", "POST"))
        self.assertFalse(_is_public_readonly_api("/api/public/casino-idents/u41", "POST"))


if __name__ == "__main__":
    unittest.main()
