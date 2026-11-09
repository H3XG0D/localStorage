"""Потолки подписанта из runtime settings."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from auto_settings import signer_coin_caps, signer_policy_payload


class SignerPolicyCapsTests(unittest.TestCase):
    def test_payload_uses_settings(self):
        with patch(
            "auto_settings.get_settings_sync",
            return_value={
                "signer_max_tx_btc": 0.05,
                "signer_max_tx_ltc": 20.0,
                "signer_daily_cap_btc": 0.2,
                "signer_daily_cap_ltc": 60.0,
            },
        ):
            payload = signer_policy_payload()
            self.assertEqual(payload["max_tx_ltc"], 20.0)
            self.assertEqual(payload["daily_cap_ltc"], 60.0)
            self.assertEqual(signer_coin_caps("ltc"), {"max_tx": 20.0, "daily_cap": 60.0})
            self.assertEqual(signer_coin_caps("btc")["max_tx"], 0.05)


if __name__ == "__main__":
    unittest.main()
