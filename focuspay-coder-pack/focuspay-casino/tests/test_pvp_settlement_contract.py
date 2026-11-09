import ast
from decimal import Decimal
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
GAME_FILES = ("pvp.py", "baccara.py", "blackjack.py")
REQUIRED_LIFECYCLE_METHODS = {
    "join_and_hold_game",
    "persist_game_state",
    "commit_game_outcome",
    "settle_committed_outcome",
}
FORBIDDEN_METHODS = {
    "settle_committed_game",
    "settle_head_to_head_game",
    "hold_balance",
    "release_bet",
    "confirm_bet",
}


class DurableLifecycleContractTests(unittest.TestCase):
    def _tree(self, game_file):
        return ast.parse((ROOT / "games" / game_file).read_text())

    @staticmethod
    def _calls(function):
        return [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]

    def test_every_game_uses_durable_lifecycle_without_legacy_calls(self):
        for game_file in GAME_FILES:
            calls = {node.func.attr for node in self._calls(self._tree(game_file))}
            self.assertTrue(REQUIRED_LIFECYCLE_METHODS <= calls, game_file)
            if game_file != "pvp.py":
                self.assertIn("create_or_resume_game", calls, game_file)
            self.assertFalse(FORBIDDEN_METHODS & calls, game_file)

    def test_settlement_uses_exact_committed_outcome_method_with_game_id_keyword(self):
        for game_file in GAME_FILES:
            settlements = [
                node for node in self._calls(self._tree(game_file))
                if node.func.attr == "settle_committed_outcome"
            ]
            self.assertTrue(settlements, game_file)
            for call in settlements:
                self.assertIn("game_id", {keyword.arg for keyword in call.keywords}, game_file)

    def test_non_winner_outcomes_commit_before_settlement(self):
        for game_file in GAME_FILES:
            tree = self._tree(game_file)
            helper = next(
                node for node in tree.body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "_commit_and_settle"
            )
            calls = self._calls(helper)
            names = [node.func.attr for node in calls]
            self.assertIn("commit_game_outcome", names, game_file)
            self.assertIn("_settle_committed_outcome", [
                node.func.id for node in ast.walk(helper)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            ], game_file)
            self.assertNotIn("release_game", names, game_file)

    def test_card_games_deal_from_backend_and_do_not_shuffle(self):
        for game_file in ("baccara.py", "blackjack.py"):
            source = (ROOT / "games" / game_file).read_text()
            calls = {node.func.attr for node in self._calls(self._tree(game_file))}
            self.assertIn("prepare_cards", calls, game_file)
            self.assertIn("deal_cards", calls, game_file)
            self.assertIn("reveal_cards", calls, game_file)
            self.assertNotIn("SystemRandom", source, game_file)
            self.assertNotIn("shuffle(", source, game_file)
            self.assertNotIn("bak_new_deck", source, game_file)
            self.assertNotIn("bj_new_deck", source, game_file)

    def test_winner_payout_is_derived_from_durable_settlement_response(self):
        for game_file in GAME_FILES:
            source = (ROOT / "games" / game_file).read_text()
            self.assertIn("settlement_payout_rub(settlement)", source, game_file)
            self.assertNotIn("calculate_head_to_head_settlement", source, game_file)

    def test_backend_response_example_has_expected_payout(self):
        from finance import settlement_payout_rub

        self.assertEqual(
            settlement_payout_rub({"payout_rub": "185.00"}),
            Decimal("185.00"),
        )

    def test_snapshots_exclude_optimistic_version(self):
        for game_file in GAME_FILES:
            source = (ROOT / "games" / game_file).read_text()
            self.assertIn('!= "state_version"', source, game_file)


if __name__ == "__main__":
    unittest.main()
