import unittest
from unittest.mock import patch

import games.help as help_mod
from games.help import parse_help_topic, render_help


SETTINGS = {
    "min_bet_rub": 10,
    "max_bet_rub": 100000,
    "commission_rate_wagering_active": 15,
    "commission_rate_wagering_complete": 5,
    "wagering_percent": 100,
    "roulette_table_collect_seconds": 25,
}


def render(settings, text, *, deposits: bool):
    with patch.object(help_mod.config, "DEPOSITS_ENABLED", deposits):
        return render_help(settings, text)


class HelpTopicTests(unittest.TestCase):
    def test_index_lists_topics(self):
        text = render(SETTINGS, "/help", deposits=True)
        self.assertIn("/help roulette", text)
        self.assertIn("/help jackpot", text)
        self.assertIn("/help rooms", text)
        self.assertIn("/help cub", text)
        self.assertIn("/help blackjack", text)
        self.assertIn("15%", text)
        self.assertIn("5%", text)
        self.assertIn("СБП", text)
        self.assertNotIn("focus_operator", text)
        self.assertNotIn("/darts", text)
        self.assertNotIn("/boul", text)
        self.assertNotIn("/help team", text)
        self.assertNotIn("атомарн", text.lower())
        self.assertLess(len(text), 4096)

    def test_index_without_deposits_writes_five_percent_and_soon(self):
        text = render(SETTINGS, "/help", deposits=False)
        self.assertIn("Комиссия игр: 5%", text)
        self.assertNotIn("до отыгрыша", text)
        self.assertNotIn("СБП", text)
        self.assertNotIn("/deposit —", text)
        self.assertIn("скоро", text)
        self.assertIn("/help deposit", text)
        self.assertLess(len(text), 4096)

    def test_deposit_page_lists_sbp_and_card(self):
        text = render(SETTINGS, "/help deposit", deposits=True)
        self.assertIn("СБП", text)
        self.assertIn("карта", text.lower())
        self.assertNotIn("focus_operator", text)

    def test_deposit_page_soon_when_disabled(self):
        text = render(SETTINGS, "/help deposit", deposits=False)
        self.assertIn("скоро", text)
        self.assertNotIn("СБП", text)
        self.assertNotIn("/deposit", text)

    def test_rules_without_deposits_are_five_percent_only(self):
        text = render(SETTINGS, "/help rules", deposits=False)
        self.assertIn("Комиссия игр: 5%", text)
        self.assertNotIn("до отыгрыша", text)
        self.assertNotIn("15%", text)

    def test_roulette_page_has_suffix_and_multi(self):
        text = render(SETTINGS, "/help roulette", deposits=True)
        self.assertIn("1rd", text)
        self.assertIn("multi", text)
        self.assertIn("10р", text)
        self.assertIn("mode=players", text)
        self.assertLess(len(text), 4096)
        index = render(SETTINGS, "/help", deposits=True)
        self.assertIn("/fast", index)
        self.assertIn("выключены", index)

    def test_cub_and_blackjack_are_readable(self):
        cub = render(SETTINGS, "/help cub", deposits=True)
        bj = render(SETTINGS, "/help blackjack", deposits=True)
        self.assertIn("/cub", cub)
        self.assertIn("Ничья", cub)
        self.assertIn("/blackjack", bj)
        self.assertNotIn("…", bj[-2:])
        self.assertLess(len(cub), 4096)
        self.assertLess(len(bj), 4096)

    def test_live_limits_not_stale_hardcode_only(self):
        text = render({**SETTINGS, "min_bet_rub": 25, "max_bet_rub": 8000}, "/help rules", deposits=True)
        self.assertIn("25", text)
        self.assertIn("8000", text)

    def test_rooms_page_has_equal_stake_and_bot(self):
        text = render(SETTINGS, "/help rooms", deposits=True)
        self.assertIn("/rooms", text)
        self.assertIn("колесо", text)
        self.assertIn("бот", text.lower())
        self.assertLess(len(text), 4096)

    def test_unknown_topic_falls_back_to_index(self):
        text = render(SETTINGS, "/help nope", deposits=True)
        self.assertIn("Нет темы", text)
        self.assertIn("/help roulette", text)

    def test_aliases(self):
        self.assertEqual(parse_help_topic("/help рулетка"), "roulette")
        self.assertEqual(parse_help_topic("/help джекпот"), "jackpot")
        self.assertEqual(parse_help_topic("/help комнаты"), "rooms")
        self.assertEqual(parse_help_topic("/help"), "")
