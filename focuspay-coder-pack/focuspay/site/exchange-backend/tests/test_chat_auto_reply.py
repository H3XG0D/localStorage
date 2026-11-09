import unittest

from chat_auto_reply import matches_che_kogo


class TestCheKogoMatch(unittest.TestCase):
    def test_exact(self):
        self.assertTrue(matches_che_kogo("че кого"))
        self.assertTrue(matches_che_kogo("Чё кого"))
        self.assertTrue(matches_che_kogo("ЧЕ КОГО"))

    def test_with_punctuation(self):
        self.assertTrue(matches_che_kogo("че кого???"))
        self.assertTrue(matches_che_kogo("Ну че кого там"))

    def test_compact(self):
        self.assertTrue(matches_che_kogo("чекого"))

    def test_negative(self):
        self.assertFalse(matches_che_kogo("привет"))
        self.assertFalse(matches_che_kogo(""))
        self.assertFalse(matches_che_kogo(None))
        self.assertFalse(matches_che_kogo("кого-то че-то"))


if __name__ == "__main__":
    unittest.main()
