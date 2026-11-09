"""Unique generated avatars for players without a photo."""
from __future__ import annotations

import unittest

from fastapi import HTTPException

from casino_default_avatar import (
    all_unique,
    default_avatar_public_url,
    default_avatar_url_for_user,
    parse_ident_seed,
    render_ident_svg,
    robot_ident_seed,
    user_ident_seed,
)
from casino_duels import bot_chip
from casino_player_cosmetics import apply_cosmetics


class DefaultAvatarPureTests(unittest.TestCase):
    def test_seeds_are_path_safe_and_stable(self):
        self.assertEqual(user_ident_seed(41), "u41")
        self.assertEqual(user_ident_seed(-7), "n7")
        with self.assertRaises(ValueError):
            user_ident_seed(0)
        self.assertEqual(robot_ident_seed(profile_id=12), "r12")
        self.assertNotEqual(
            robot_ident_seed(display_name="Дом", seat_no=11),
            robot_ident_seed(display_name="Касса", seat_no=12),
        )
        self.assertEqual(parse_ident_seed("u41"), "u41")
        with self.assertRaises(HTTPException) as bad:
            parse_ident_seed("../etc/passwd")
        self.assertEqual(bad.exception.status_code, 404)

    def test_same_person_same_picture_nobody_shares(self):
        first = render_ident_svg("u41")
        self.assertEqual(first, render_ident_svg("u41"))
        self.assertNotEqual(first, render_ident_svg("u42"))
        self.assertNotEqual(render_ident_svg("n1"), render_ident_svg("u1"))
        seeds = [f"u{i}" for i in range(1, 401)] + [f"n{i}" for i in range(1, 101)]
        self.assertTrue(all_unique(seeds))
        self.assertIn("<svg", first)
        self.assertIn("clipPath", first)
        self.assertIn("ellipse", first)
        self.assertTrue("cy=\"34\"" in first or "cy='34'" in first)

    def test_missing_photo_gets_ident_url_uploaded_keeps_file(self):
        name, avatar = apply_cosmetics(-3, "Веб", avatar_url=None, cosmetics=None)
        self.assertEqual(name, "Веб")
        self.assertEqual(avatar, "/api/public/casino-idents/n3?v=3")
        self.assertEqual(default_avatar_url_for_user(-3), avatar)
        self.assertEqual(default_avatar_public_url("u41"), "/api/public/casino-idents/u41?v=3")
        _, telegram = apply_cosmetics(41, "Ира", avatar_url="/tg", cosmetics=None)
        self.assertEqual(telegram, "/tg")
        _, custom = apply_cosmetics(
            41,
            "Ира",
            avatar_url="/tg",
            cosmetics={"nickname": "Куб", "avatar_ext": "jpg"},
        )
        self.assertTrue(str(custom).startswith("/api/public/casino-avatars/41?"))

    def test_robots_get_distinct_pictures_not_profile_links(self):
        house = bot_chip("Дом", profile_id=1, profile_key="house-dice", seat_no=11)
        other = bot_chip("Касса", profile_id=2, profile_key="house-dice-2", seat_no=12)
        self.assertEqual(house["user_id"], 0)
        self.assertTrue(str(house["avatar_url"]).startswith("/api/public/casino-idents/r1"))
        self.assertTrue(str(other["avatar_url"]).startswith("/api/public/casino-idents/r2"))
        self.assertNotEqual(house["avatar_url"], other["avatar_url"])
        self.assertNotEqual(render_ident_svg("r1"), render_ident_svg("r2"))


if __name__ == "__main__":
    unittest.main()
