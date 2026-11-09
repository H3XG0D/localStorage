import unittest
from unittest.mock import AsyncMock, MagicMock

from chat_support_scope import is_support_operator_user, support_operator_user_ids


class TestSupportOperatorScope(unittest.TestCase):
    def test_is_support_operator_user(self):
        excluded = {1097952683, 42}
        self.assertTrue(is_support_operator_user(1097952683, excluded))
        self.assertFalse(is_support_operator_user(999, excluded))
        self.assertFalse(is_support_operator_user(None, excluded))

    def test_is_support_operator_user_empty(self):
        self.assertFalse(is_support_operator_user(1, set()))


class TestSupportOperatorUserIds(unittest.IsolatedAsyncioTestCase):
    async def test_collects_from_business_and_username(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[{"user_id": 555}])
        conn.fetchval = AsyncMock(return_value=777)

        from config import settings

        old_owner = settings.security_telegram_user_id
        old_uname = settings.chat_support_username
        try:
            settings.security_telegram_user_id = 1097952683
            settings.chat_support_username = "focus_operator"
            ids = await support_operator_user_ids(conn)
        finally:
            settings.security_telegram_user_id = old_owner
            settings.chat_support_username = old_uname

        self.assertEqual(ids, {1097952683, 555, 777})


if __name__ == "__main__":
    unittest.main()
