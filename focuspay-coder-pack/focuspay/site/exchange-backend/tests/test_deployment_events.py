"""Deploy webhook signature + idempotency helpers (no DB)."""
from __future__ import annotations

import hashlib
import hmac
import unittest
from unittest.mock import patch

import deployment_events as de


class DeploySignatureTests(unittest.TestCase):
    def test_signature_ok(self):
        body = b'{"idempotency_key":"k1","status":"success"}'
        with patch.object(de.settings, "deploy_webhook_secret", "s3cret"):
            sig = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
            self.assertTrue(de.verify_deploy_signature(body, sig))
            self.assertTrue(de.verify_deploy_signature(body, f"sha256={sig}"))
            self.assertFalse(de.verify_deploy_signature(body, "deadbeef"))
            self.assertFalse(de.verify_deploy_signature(body, None))

    def test_scrub_secrets(self):
        out = de._scrub_plain("token=abc SECRET_KEY=zzz hello")
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("zzz", out)
        self.assertNotIn("abc", out)


if __name__ == "__main__":
    unittest.main()
