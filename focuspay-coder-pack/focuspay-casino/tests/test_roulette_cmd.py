from decimal import Decimal
import unittest

from games.roulette_cmd import (
    COMMA_PACK_MESSAGE,
    ParsedRouletteCommand,
    RouletteCommandError,
    parse_roulette_command,
)


class RouletteCommandParseTests(unittest.TestCase):
    def test_empty_args_are_cheatsheet(self):
        self.assertIsNone(parse_roulette_command("/roulette"))
        self.assertIsNone(parse_roulette_command("/рулетка"))

    def test_named_color_without_suffix(self):
        parsed = parse_roulette_command("/roulette red 10")
        self.assertEqual(parsed, ParsedRouletteCommand(cells=("red",), amount_rub=Decimal("10.00"), multi=False))

    def test_russian_color_and_dozen(self):
        self.assertEqual(parse_roulette_command("/roulette красное 50").cells, ("red",))
        self.assertEqual(parse_roulette_command("/roulette 1rd 50").cells, ("dozen1",))
        self.assertEqual(parse_roulette_command("/roulette чёт 20").cells, ("even",))

    def test_straight_requires_suffix_when_amount_looks_like_pocket(self):
        with self.assertRaisesRegex(RouletteCommandError, "напишите 10р, иначе это число 10"):
            parse_roulette_command("/roulette 10 10")
        parsed = parse_roulette_command("/roulette 10 10р")
        self.assertEqual(parsed.cells, ("10",))
        self.assertEqual(parsed.amount_rub, Decimal("10.00"))

    def test_straight_amount_above_36_ok_without_suffix(self):
        parsed = parse_roulette_command("/roulette 17 500")
        self.assertEqual(parsed.cells, ("17",))
        self.assertEqual(parsed.amount_rub, Decimal("500.00"))

    def test_multi_requires_suffix_for_pocket_like_amount(self):
        with self.assertRaisesRegex(RouletteCommandError, "напишите 10р"):
            parse_roulette_command("/roulette multi 1 4 10")
        parsed = parse_roulette_command("/roulette multi 1 4 6 10р")
        self.assertEqual(parsed.cells, ("1", "4", "6"))
        self.assertEqual(parsed.amount_rub, Decimal("10.00"))
        self.assertEqual(parsed.debit_rub, Decimal("30.00"))
        self.assertTrue(parsed.multi)

    def test_comma_pack_is_refused(self):
        with self.assertRaisesRegex(RouletteCommandError, "multi"):
            parse_roulette_command("/roulette 1,5,8 10р")
        self.assertIn("1,5,8", COMMA_PACK_MESSAGE)

    def test_zero_and_aliases(self):
        self.assertEqual(parse_roulette_command("/roulette 0 50").cells, ("zero",))
        self.assertEqual(parse_roulette_command("/roulette 1col 50").cells, ("col1",))
