"""HTTPS-only urllib helper (Bandit B310)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from urllib.request import Request

from https_fetch import https_urlopen


class HttpsFetchTests(unittest.TestCase):
    def test_rejects_http(self):
        with self.assertRaises(ValueError):
            https_urlopen("http://example.com/")

    def test_rejects_file_scheme(self):
        with self.assertRaises(ValueError):
            https_urlopen("file:///etc/passwd")

    def test_https_calls_urlopen(self):
        fake = MagicMock(name="resp")
        with patch("https_fetch.urllib.request.urlopen", return_value=fake) as opener:
            out = https_urlopen("https://example.com/x", timeout=7)
        self.assertIs(out, fake)
        opener.assert_called_once()
        args, kwargs = opener.call_args
        self.assertEqual(args[0], "https://example.com/x")
        self.assertEqual(kwargs.get("timeout"), 7)

    def test_https_request_object(self):
        req = Request("https://focuspay.org/api/")
        fake = MagicMock(name="resp")
        with patch("https_fetch.urllib.request.urlopen", return_value=fake) as opener:
            https_urlopen(req, timeout=3)
        opener.assert_called_once()
        self.assertIs(opener.call_args[0][0], req)


if __name__ == "__main__":
    unittest.main()
