"""Admin chat routes: same thread model as operator, admin auth."""
from pathlib import Path
import unittest


ADMIN_CHAT_SRC = (
    Path(__file__).resolve().parents[1] / "routers" / "chat_admin.py"
).read_text(encoding="utf-8")


class AdminChatRoutesAuthTests(unittest.TestCase):
    def test_parity_endpoints_present(self):
        for needle in (
            '@router.get("/chat/unread-count")',
            '@router.get("/chat/unread-by-source")',
            '@router.get("/chat/events")',
            '@router.get("/chat/sticker-sets")',
            '@router.post("/chat/threads/{thread_id}/messages/sticker")',
        ):
            self.assertIn(needle, ADMIN_CHAT_SRC, msg=f"missing {needle}")

    def test_live_and_sticker_handlers_require_admin(self):
        for name in (
            "chat_unread_count",
            "chat_unread_by_source",
            "chat_events_stream",
            "chat_sticker_sets",
            "reply_sticker",
        ):
            self.assertIn(
                f"async def {name}",
                ADMIN_CHAT_SRC,
                msg=f"{name} missing",
            )
            self.assertIn(
                "get_current_admin",
                ADMIN_CHAT_SRC.split(f"async def {name}", 1)[1].split("async def ", 1)[0],
                msg=f"{name} missing admin auth",
            )


CHAT_SERVICE_SRC = (
    Path(__file__).resolve().parents[1] / "chat_service.py"
).read_text(encoding="utf-8")


class AdminGetThreadIncrementalTests(unittest.TestCase):
    def test_after_id_skips_profile_and_avatar_fetch(self):
        self.assertIn("incremental = after_id > 0", CHAT_SERVICE_SRC)
        fn = CHAT_SERVICE_SRC.split("async def admin_get_thread", 1)[1].split(
            "async def _thread_message_count", 1
        )[0]
        self.assertIn("if incremental:", fn)
        self.assertIn("thread = _thread_summary(row)", fn)
        self.assertIn("build_buyer_profile", fn)
        profile_branch = fn.split("if incremental:", 1)[1].split("else:", 1)[1]
        self.assertIn("build_buyer_profile", profile_branch)
        incremental_branch = fn.split("if incremental:", 1)[1].split("else:", 1)[0]
        self.assertNotIn("build_buyer_profile", incremental_branch)
        self.assertNotIn("fetch_and_cache_bot_user_avatar", incremental_branch)
