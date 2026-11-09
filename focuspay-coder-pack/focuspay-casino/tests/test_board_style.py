import unittest

from games.board_style import PHASE_LABELS, next_line, now_line, render_board, seconds_until, timer_line


class BoardStyleTests(unittest.TestCase):
    def test_phase_labels_cover_live_statuses(self):
        for key in (
            "collect",
            "countdown",
            "dealing_1",
            "dealing_2",
            "dealing_3",
            "rolling",
            "spinning",
            "slowing",
            "reel",
            "scoring",
            "settled",
        ):
            self.assertIn(key, PHASE_LABELS)
            self.assertTrue(PHASE_LABELS[key])

    def test_render_board_skips_empty_and_caps(self):
        text = render_board(
            header="🎡 <b>Рулетка</b>",
            money="Банк: 10 ₽",
            roster=["• Ann"],
            now="Сбор ставок",
            nxt="Ждём спин",
            timer="До спина 9 с",
            extra=[""],
            footer="",
        )
        self.assertIn("Сейчас: Сбор ставок", text)
        self.assertIn("Дальше: Ждём спин", text)
        self.assertIn("До спина 9 с", text)
        self.assertIn("• Ann", text)
        self.assertNotIn("\n\n\n", text)

    def test_now_and_next_prefixes(self):
        self.assertEqual(now_line("Раздача"), "Сейчас: Раздача")
        self.assertEqual(next_line("Дальше: киньте 🎲"), "Дальше: киньте 🎲")
        self.assertEqual(now_line(""), "")

    def test_timer_line_waiting_and_spin(self):
        self.assertIn("Ждём первую ставку", timer_line({"status": "open", "collect_seconds": 25}))
        self.assertEqual(
            timer_line({"status": "locked"}),
            "Колесо крутится, ставки закрыты.",
        )

    def test_seconds_until_none(self):
        self.assertIsNone(seconds_until(None))
        self.assertIsNone(seconds_until(""))
