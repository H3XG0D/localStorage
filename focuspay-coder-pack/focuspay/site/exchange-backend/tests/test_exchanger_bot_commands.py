"""Парсинг команд и маска токена бота внештатников."""
from __future__ import annotations

import unittest

from exchanger_bot_commands import (
    is_balance_command,
    mask_bot_token,
    parse_add_command,
    parse_kick_command,
    parse_requisite_command,
)


class ExchangerBotCommandsTests(unittest.TestCase):
    def test_parse_sbp(self):
        out = parse_requisite_command("сбп 5400")
        self.assertEqual(out["amount_rub"], 5400.0)
        self.assertEqual(out["sub_token"], "SBPRUB")

    def test_parse_card(self):
        out = parse_requisite_command("карта 12000")
        self.assertEqual(out["sub_token"], "CARDRUB")
        self.assertEqual(out["amount_rub"], 12000.0)

    def test_parse_spaces_in_amount(self):
        out = parse_requisite_command("sbp 5 400")
        self.assertEqual(out["amount_rub"], 5400.0)

    def test_parse_rejects_garbage(self):
        self.assertIsNone(parse_requisite_command("привет"))
        self.assertIsNone(parse_requisite_command("сбп"))
        self.assertIsNone(parse_requisite_command("сбп -10"))

    def test_mask_token(self):
        masked = mask_bot_token("1234567890:AAEsecretsecret7xQ")
        self.assertTrue(masked.startswith("1234567890:…"))
        self.assertTrue(masked.endswith("7xQ"))
        self.assertNotIn("AAEsecret", masked)

    def test_mask_empty(self):
        self.assertIsNone(mask_bot_token(""))
        self.assertIsNone(mask_bot_token(None))

    def test_add_kick(self):
        self.assertEqual(parse_add_command("/add 14114102312130 Вася"), (14114102312130, "Вася"))
        self.assertEqual(parse_kick_command("/kick 14114102312130"), 14114102312130)

    def test_balance(self):
        self.assertTrue(is_balance_command("баланс"))
        self.assertFalse(is_balance_command("сбп 100"))


if __name__ == "__main__":
    unittest.main()
