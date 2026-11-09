import importlib
import unittest
from unittest.mock import patch

from tests.telebot_stub import TelebotModules


with TelebotModules("games.site_links"):
    site_links = importlib.import_module("games.site_links")


class SiteLinksTests(unittest.TestCase):
    def test_http_origin_builds_live_paths(self):
        with patch.object(
            site_links.config, "CASINO_MINIAPP_URL", "http://127.0.0.1:18081/casino/tg"
        ):
            self.assertEqual(
                site_links.roulette_play_url(),
                "http://127.0.0.1:18081/casino/play/roulette?mode=players",
            )
            self.assertEqual(
                site_links.jackpot_play_url(),
                "http://127.0.0.1:18081/casino/play/jackpot?mode=players",
            )
            self.assertEqual(
                site_links.duel_url("web-03e1a2745423"),
                "http://127.0.0.1:18081/casino/duels/web-03e1a2745423",
            )
            self.assertEqual(
                site_links.table_url("tbl-1"),
                "http://127.0.0.1:18081/casino/tables/tbl-1",
            )
            self.assertIsNone(site_links.https_only(site_links.jackpot_play_url()))
            self.assertEqual(
                site_links.room_url("fr-aabbccddeeff"),
                "http://127.0.0.1:18081/casino/rooms/fr-aabbccddeeff",
            )
            html = site_links.append_watch_line("ok", site_links.jackpot_play_url())
            self.assertIn('href="http://127.0.0.1:18081/casino/play/jackpot?mode=players"', html)
            self.assertIn("Смотреть на сайте", html)
            self.assertIn("<code>http://127.0.0.1:18081/casino/play/jackpot?mode=players</code>", html)
            keyboard = site_links.watch_keyboard(site_links.jackpot_play_url())
            self.assertIsNotNone(keyboard)
            button = keyboard.keyboard[0][0]
            self.assertEqual(button.url, "http://127.0.0.1:18081/casino/play/jackpot?mode=players")
            self.assertIsNone(button.web_app)

    def test_https_origin_keeps_https_only_helper(self):
        with patch.object(
            site_links.config, "CASINO_MINIAPP_URL", "https://example.test/casino/tg"
        ):
            url = site_links.roulette_play_url()
            self.assertEqual(site_links.https_only(url), url)

    def test_missing_origin_skips_link_and_button(self):
        with patch.object(site_links.config, "CASINO_MINIAPP_URL", ""):
            self.assertIsNone(site_links.jackpot_play_url())
            self.assertEqual(site_links.append_watch_line("ok", None), "ok")
            self.assertIsNone(site_links.watch_keyboard(None))
            self.assertIsNone(site_links.duel_url(""))
            self.assertIsNone(site_links.table_url(None))


if __name__ == "__main__":
    unittest.main()
