import importlib
import os
import unittest

os.environ["EXCHANGE_BACKEND"] = "/home/qwe/Desktop/focuspay/site/exchange-backend"

import focus_agent.config as config
import focus_agent.redact as redact_mod

importlib.reload(config)
importlib.reload(redact_mod)


class RedactTests(unittest.TestCase):
    def test_card_does_not_survive(self):
        raw = "карта 4276123456789012 на смену"
        cleaned = redact_mod.redact(raw)
        self.assertNotIn("4276123456789012", cleaned)
        self.assertIn("[REDACTED]", cleaned)


if __name__ == "__main__":
    unittest.main()
