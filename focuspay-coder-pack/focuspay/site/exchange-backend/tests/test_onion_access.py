"""Tor v3 hostname helpers + cookie Secure flag on .onion."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from onion_access import (
    hostname_from_host_header,
    is_onion_host,
    normalize_onion_origin,
    request_is_onion,
)
from panel_cookies import _cookie_secure


SAMPLE = "a" * 56


class OnionAccessTests(unittest.TestCase):
    def test_hostname_strips_port(self):
        self.assertEqual(hostname_from_host_header(f"{SAMPLE}.onion:80"), f"{SAMPLE}.onion")

    def test_v3_host(self):
        self.assertTrue(is_onion_host(f"{SAMPLE}.onion"))
        self.assertFalse(is_onion_host("focuspay.org"))
        self.assertFalse(is_onion_host("not-an-onion.onion"))

    def test_normalize(self):
        self.assertEqual(
            normalize_onion_origin(f"https://{SAMPLE}.onion/"),
            f"http://{SAMPLE}.onion",
        )
        self.assertEqual(normalize_onion_origin(f"{SAMPLE}.onion"), f"http://{SAMPLE}.onion")
        self.assertEqual(normalize_onion_origin("https://focuspay.org"), "")

    def test_request_is_onion(self):
        req = MagicMock()
        req.headers = {"host": f"{SAMPLE}.onion"}
        req.url.hostname = f"{SAMPLE}.onion"
        self.assertTrue(request_is_onion(req))
        req.headers = {"host": "focuspay.org"}
        req.url.hostname = "focuspay.org"
        self.assertFalse(request_is_onion(req))

    def test_cookie_not_secure_on_onion(self):
        req = MagicMock()
        req.headers = {"host": f"{SAMPLE}.onion"}
        req.url.scheme = "http"
        self.assertFalse(_cookie_secure(req))

    def test_cookie_secure_on_https_clearnet(self):
        req = MagicMock()
        req.headers = {"host": "focuspay.org", "x-forwarded-proto": "https"}
        req.url.scheme = "http"
        self.assertTrue(_cookie_secure(req))

    def test_cookie_fallback_uses_public_site_url(self):
        with patch("panel_cookies.settings", SimpleNamespace(public_site_url="https://focuspay.org")):
            self.assertTrue(_cookie_secure(None))
        with patch("panel_cookies.settings", SimpleNamespace(public_site_url="http://localhost:5173")):
            self.assertFalse(_cookie_secure(None))


if __name__ == "__main__":
    unittest.main()
