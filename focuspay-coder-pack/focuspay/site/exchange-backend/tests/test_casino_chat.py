"""Casino chat: rate limit, DM isolation helpers, reserved duel join."""
from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from casino_chat import (
    MAX_BODY,
    actor_payload,
    dm_pair,
    join_allowed,
    lobby_blocks_links,
    presence_is_online,
    rate_limit_ok,
    reserved_blocks_joiner,
    sanitize_body,
)
from casino_duels import pick_autojoin_target, reserved_opponent_of
from fastapi import HTTPException


class CasinoChatPureTests(unittest.TestCase):
    def test_dm_pair_orders_and_rejects_self(self):
        self.assertEqual(dm_pair(9, 3), (3, 9))
        with self.assertRaises(ValueError):
            dm_pair(4, 4)

    def test_sanitize_rejects_empty_and_too_long(self):
        self.assertEqual(sanitize_body("  hi  "), "hi")
        with self.assertRaises(HTTPException) as empty:
            sanitize_body("   ")
        self.assertEqual(empty.exception.status_code, 400)
        with self.assertRaises(HTTPException) as long:
            sanitize_body("x" * (MAX_BODY + 1))
        self.assertEqual(long.exception.status_code, 400)

    def test_lobby_blocks_links_but_plain_text_passes(self):
        self.assertTrue(lobby_blocks_links("смотри https://spam.example"))
        self.assertTrue(lobby_blocks_links("t.me/casino"))
        self.assertFalse(lobby_blocks_links("кто на кубик 100"))

    def test_rate_limit_three_per_ten_seconds(self):
        from casino_chat import _rate

        _rate.clear()
        now = 1_000_000.0
        self.assertTrue(rate_limit_ok(11, 1, now=now))
        self.assertTrue(rate_limit_ok(11, 1, now=now + 1))
        self.assertTrue(rate_limit_ok(11, 1, now=now + 2))
        self.assertFalse(rate_limit_ok(11, 1, now=now + 3))
        self.assertTrue(rate_limit_ok(11, 2, now=now + 3))
        self.assertTrue(rate_limit_ok(12, 1, now=now + 3))
        self.assertTrue(rate_limit_ok(11, 1, now=now + 11))

    def test_presence_window(self):
        now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        fresh = now - timedelta(seconds=44)
        stale = now - timedelta(seconds=46)
        self.assertTrue(presence_is_online(fresh, now=now))
        self.assertFalse(presence_is_online(stale, now=now))
        self.assertFalse(presence_is_online(None, now=now))

    def test_reserved_join_only_addressee(self):
        self.assertTrue(join_allowed(reserved_opponent_id=None, joiner_id=2))
        self.assertTrue(join_allowed(reserved_opponent_id=7, joiner_id=7))
        self.assertFalse(join_allowed(reserved_opponent_id=7, joiner_id=8))
        game = {"game_state": {"reserved_opponent_id": 22}}
        self.assertTrue(reserved_blocks_joiner(game, 9))
        self.assertFalse(reserved_blocks_joiner(game, 22))

    def test_actor_hides_nothing_required_and_has_initial(self):
        actor = actor_payload(41, "@ivan", avatar_url="/api/public/bot-user-avatars/41?access=x")
        self.assertEqual(actor["user_id"], 41)
        self.assertEqual(actor["initial"], "I")
        self.assertIn("avatar_url", actor)

    def test_autojoin_skips_reserved_challenge(self):
        now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        waiting = [
            {
                "game_id": "reserved",
                "game_type": "pvp_dice",
                "bet_rub": Decimal("50"),
                "creator_id": 3,
                "opponent_id": None,
                "status": "waiting",
                "created_at": now - timedelta(hours=1),
                "game_state": {"reserved_opponent_id": 99},
            },
            {
                "game_id": "open",
                "game_type": "pvp_dice",
                "bet_rub": Decimal("50"),
                "creator_id": 4,
                "opponent_id": None,
                "status": "waiting",
                "created_at": now,
                "game_state": {},
            },
        ]
        picked = pick_autojoin_target(waiting, game_type="pvp_dice", stake_rub="50", viewer_id=1)
        self.assertEqual(picked["game_id"], "open")
        self.assertEqual(reserved_opponent_of(waiting[0]), 99)

    def test_third_party_cannot_infer_dm_pair_collision_with_self(self):
        a = dm_pair(10, 20)
        b = dm_pair(20, 10)
        self.assertEqual(a, b)
        self.assertNotEqual(hashlib.sha256(f"{a[0]}:{a[1]}".encode()).hexdigest(), hashlib.sha256(b"10:10").hexdigest())


class CasinoChatPanelLiveTests(unittest.TestCase):
    """Desktop keeps the docked rail visible while `open` stays false (mobile overlay)."""

    def test_docked_rail_loads_when_overlay_flag_is_false(self):
        src = (
            Path(__file__).resolve().parents[3]
            / "focussite/frontend/src/casino/CasinoChatPanel.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("function casinoChatIsLive", src)
        self.assertRegex(src, r"return open \|\| docked")
        self.assertRegex(src, r"casinoChatIsLive\(open,\s*docked\)")
        self.assertNotIn("if (!open || !isAuthed) return", src)
