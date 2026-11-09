"""Operator wallet payout helpers."""
import os
import sys
import unittest
from unittest.mock import MagicMock

# Stub buy_payout before importing operator_wallet_payouts
def _fake_normalize(raw: str):
    t = (raw or "").strip()
    if t.startswith("http"):
        t = t.rstrip("/").split("/")[-1]
    t = t.split("?")[0]
    if len(t) < 8:
        return None
    return t


_bot_mod = MagicMock()
_bot_mod.normalize_tx_hash = _fake_normalize
_bot_mod.build_explorer_url = lambda c, h: f"https://example.com/{h}"
_services = MagicMock()
_services.buy_payout = _bot_mod
sys.modules.setdefault("services", _services)
sys.modules.setdefault("services.buy_payout", _bot_mod)

from operator_wallet_payouts import _normalize_tx_hash, _recipient_label


class OperatorWalletPayoutTests(unittest.TestCase):
    def test_normalize_tx_hash_accepts_hex(self):
        h = "a" * 64
        self.assertEqual(_normalize_tx_hash(h), h)

    def test_normalize_tx_hash_extracts_from_url(self):
        raw = "https://blockchair.com/litecoin/transaction/abcdef12345678"
        self.assertEqual(_normalize_tx_hash(raw), "abcdef12345678")

    def test_normalize_tx_hash_rejects_short(self):
        self.assertIsNone(_normalize_tx_hash("abc"))

    def test_recipient_label_with_username(self):
        label = _recipient_label(
            {
                "recipient_name": "Иван",
                "user_username": "ivan",
                "user_id": 1,
            }
        )
        self.assertEqual(label, "Иван (@ivan)")


if __name__ == "__main__":
    unittest.main()
