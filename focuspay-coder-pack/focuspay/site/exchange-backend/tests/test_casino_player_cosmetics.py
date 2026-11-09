"""Casino nickname/avatar cosmetics; public_actors prefers them over Telegram."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from casino_player_cosmetics import (
    NICK_MAX,
    apply_cosmetics,
    cosmetics_avatar_path_key,
    cosmetics_avatar_public_url,
    cosmetics_avatar_stem,
    detect_avatar_ext,
    parse_signed_user_id,
    sanitize_nickname,
)
from casino_chat import actor_payload, public_actors, _actor


class CosmeticsPureTests(unittest.TestCase):
    def test_nickname_bounds_and_rejects_links(self):
        self.assertEqual(sanitize_nickname("  Аня  "), "Аня")
        with self.assertRaises(HTTPException) as short:
            sanitize_nickname("x")
        self.assertEqual(short.exception.status_code, 400)
        with self.assertRaises(HTTPException):
            sanitize_nickname("x" * (NICK_MAX + 1))
        with self.assertRaises(HTTPException):
            sanitize_nickname("смотри https://spam.example")

    def test_avatar_magic_and_stems(self):
        self.assertEqual(detect_avatar_ext(b"\xff\xd8\xff" + b"\x00" * 16), ".jpg")
        self.assertEqual(detect_avatar_ext(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8), ".png")
        self.assertEqual(detect_avatar_ext(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 4), ".webp")
        with self.assertRaises(HTTPException):
            detect_avatar_ext(b"GIF89a")
        self.assertEqual(cosmetics_avatar_stem(41), "casino_41")
        self.assertEqual(cosmetics_avatar_stem(-7), "casino_n7")
        self.assertEqual(cosmetics_avatar_path_key(41), "41")
        self.assertEqual(cosmetics_avatar_path_key(-1), "n1")
        self.assertEqual(parse_signed_user_id(-1), -1)
        self.assertEqual(parse_signed_user_id("n1"), -1)
        self.assertEqual(parse_signed_user_id("-1"), -1)
        with self.assertRaises(HTTPException) as zero:
            parse_signed_user_id(0)
        self.assertEqual(zero.exception.status_code, 404)

    def test_negative_web_id_avatar_url_is_path_safe(self):
        with patch(
            "casino_player_cosmetics.make_attachment_access_token",
            return_value="tok",
        ):
            url = cosmetics_avatar_public_url(-1, has_avatar=True)
        self.assertEqual(url, "/api/public/casino-avatars/n1?access=tok")
        self.assertNotIn("/-1", url.split("?", 1)[0])

    def test_starlette_str_key_accepts_web_ids(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()

        @app.get("/key/{user_key}")
        def as_key(user_key: str):
            return {"user_key": user_key}

        client = TestClient(app)
        self.assertEqual(client.get("/key/n1").json(), {"user_key": "n1"})
        self.assertEqual(client.get("/key/-1").json(), {"user_key": "-1"})

    def test_apply_cosmetics_overrides_name_and_avatar(self):
        display, avatar = apply_cosmetics(
            41,
            "Ира",
            avatar_url="/api/public/bot-user-avatars/41?access=x",
            cosmetics={"nickname": "Куб", "avatar_ext": "jpg"},
        )
        self.assertEqual(display, "Куб")
        self.assertTrue(str(avatar).startswith("/api/public/casino-avatars/41?"))
        fallback_name, fallback_avatar = apply_cosmetics(
            41,
            "Ира",
            avatar_url="/tg",
            cosmetics=None,
        )
        self.assertEqual(fallback_name, "Ира")
        self.assertEqual(fallback_avatar, "/tg")
        none_name, none_avatar = apply_cosmetics(
            -3,
            "Веб",
            avatar_url=None,
            cosmetics=None,
        )
        self.assertEqual(none_name, "Веб")
        self.assertEqual(none_avatar, "/api/public/casino-idents/n3?v=3")
        self.assertIsNone(cosmetics_avatar_public_url(0))
        self.assertIsNotNone(cosmetics_avatar_public_url(-3, has_avatar=True))


class CosmeticsActorTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_actors_prefer_cosmetics_nickname(self):
        class Conn:
            async def fetch(self, query, *args):
                if "casino_player_cosmetics" in query:
                    return [{"user_id": 41, "nickname": "Куб", "avatar_ext": "png"}]
                raise AssertionError(query)

            async def fetchrow(self, query, *args):
                if "casino_chat_presence" in query:
                    return {"display_name": "Ира"}
                raise AssertionError(query)

        with patch(
            "casino_player_cosmetics.make_attachment_access_token",
            return_value="tok",
        ), patch(
            "casino_chat.bot_user_avatar_public_url",
            return_value="/tg",
        ), patch(
            "casino_chat.schedule_prefetch_bot_user_avatars",
        ), patch(
            "casino_chat.resolve_bot_user_avatar_path",
            return_value=None,
        ):
            actors = await public_actors(Conn(), [41])
        self.assertEqual(actors[41]["display_name"], "Куб")
        self.assertTrue(str(actors[41]["avatar_url"]).startswith("/api/public/casino-avatars/41?"))
        self.assertEqual(actor_payload(41, "Куб", avatar_url=actors[41]["avatar_url"])["initial"], "К")

    async def test_actor_telegram_file_else_ident(self):
        class Conn:
            async def fetch(self, query, *args):
                if "casino_player_cosmetics" in query:
                    return []
                raise AssertionError(query)

            async def fetchrow(self, query, *args):
                if "casino_chat_presence" in query:
                    return {"display_name": "@ivan"}
                raise AssertionError(query)

        with patch("casino_chat.schedule_prefetch_bot_user_avatars"), patch(
            "casino_chat.resolve_bot_user_avatar_path",
            return_value="/tmp/41.jpg",
        ), patch(
            "casino_chat.bot_user_avatar_public_url",
            return_value="/api/public/bot-user-avatars/41?access=x",
        ):
            with_file = await public_actors(Conn(), [41])
        self.assertEqual(with_file[41]["avatar_url"], "/api/public/bot-user-avatars/41?access=x")

        with patch("casino_chat.schedule_prefetch_bot_user_avatars"), patch(
            "casino_chat.resolve_bot_user_avatar_path",
            return_value=None,
        ), patch(
            "casino_chat.bot_user_avatar_public_url",
            return_value="/api/public/bot-user-avatars/41?access=x",
        ):
            without = await public_actors(Conn(), [41])
        self.assertTrue(str(without[41]["avatar_url"]).startswith("/api/public/casino-idents/u41"))

    async def test_actor_loads_cosmetics_for_web_negative_id(self):
        class Conn:
            async def fetch(self, query, *args):
                if "casino_player_cosmetics" in query:
                    return [{"user_id": -1, "nickname": "P2", "avatar_ext": "png"}]
                raise AssertionError(query)

            async def fetchrow(self, query, *args):
                if "casino_chat_presence" in query:
                    return {"display_name": "Player 2"}
                raise AssertionError(query)

        with patch(
            "casino_player_cosmetics.make_attachment_access_token",
            return_value="tok",
        ):
            actor = await _actor(Conn(), -1)
        self.assertEqual(actor["display_name"], "P2")
        self.assertTrue(str(actor["avatar_url"]).startswith("/api/public/casino-avatars/n1?"))
