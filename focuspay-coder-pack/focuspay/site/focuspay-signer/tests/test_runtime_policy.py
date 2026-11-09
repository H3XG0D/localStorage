"""Потолки из админки перекрывают env."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime_policy
from policy import validate_amount, validate_daily_cap


class RuntimePolicyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "policy_overrides.json"
        self._path_patch = patch.object(runtime_policy, "_path", return_value=path)
        self._path_patch.start()
        self.addCleanup(self._path_patch.stop)
        with runtime_policy._lock:
            runtime_policy._overrides = {}

    def test_save_and_load_raises_ltc_caps(self):
        caps = runtime_policy.save({"max_tx_ltc": 20.0, "daily_cap_ltc": 60.0})
        self.assertEqual(caps["max_tx_ltc"], 20.0)
        self.assertEqual(caps["daily_cap_ltc"], 60.0)
        with runtime_policy._lock:
            runtime_policy._overrides = {}
        runtime_policy.load()
        self.assertEqual(runtime_policy.max_tx("ltc"), 20.0)
        self.assertEqual(runtime_policy.daily_cap("ltc"), 60.0)

    def test_request_overlay_allows_larger_send(self):
        # env default in tests may be low; overlay on the request wins for this check
        ok = validate_amount("ltc", 15.0, max_tx=20.0)
        self.assertTrue(ok.ok)
        bad = validate_amount("ltc", 21.0, max_tx=20.0)
        self.assertFalse(bad.ok)
        self.assertEqual(bad.reason, "over_ltc_cap")

    def test_daily_overlay(self):
        ok = validate_daily_cap("ltc", 5.0, 50.0, daily_cap=60.0)
        self.assertTrue(ok.ok)
        bad = validate_daily_cap("ltc", 5.0, 56.0, daily_cap=60.0)
        self.assertFalse(bad.ok)
        self.assertTrue(bad.reason.startswith("over_daily_cap:"))


if __name__ == "__main__":
    unittest.main()
