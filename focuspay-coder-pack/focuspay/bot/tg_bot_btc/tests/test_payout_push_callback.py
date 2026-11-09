"""Callback «пропушить / не надо» разбирается до похода в API."""
import unittest

from handlers.payout_push import parse_oppush


class ParseOppushTests(unittest.TestCase):
    def test_accept_and_decline(self):
        self.assertEqual(parse_oppush("oppush:15:1"), (15, True))
        self.assertEqual(parse_oppush("oppush:15:0"), (15, False))

    def test_junk_is_ignored(self):
        self.assertIsNone(parse_oppush("oppush:15:2"))
        self.assertIsNone(parse_oppush("pay:15"))


if __name__ == "__main__":
    unittest.main()