"""Tests for operator chat quick replies and auto-replies."""
import inspect
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from chat_templates import matches_trigger
from routers import chat_operator


class TriggerMatchTests(unittest.TestCase):
    def test_che_kogo_trigger(self):
        self.assertTrue(matches_trigger("че кого брат", "че кого"))
        self.assertTrue(matches_trigger("Чё кого?", "че кого"))
        self.assertFalse(matches_trigger("привет", "че кого"))

    def test_simple_word_trigger(self):
        self.assertTrue(matches_trigger("где моя заявка", "заявка"))
        self.assertFalse(matches_trigger("ок", "заявка"))

    def test_phrase_trigger(self):
        self.assertTrue(matches_trigger("скажите номер заявки пожалуйста", "номер заявки"))


class PersonalTemplateCrudTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_requires_title_and_body(self):
        from chat_templates import create_personal_template

        with self.assertRaises(HTTPException) as ctx:
            await create_personal_template(1, title="", body="x")
        self.assertEqual(ctx.exception.status_code, 400)


class GlobalTemplateValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_rejects_empty(self):
        from chat_templates import create_global_template

        with self.assertRaises(HTTPException) as ctx:
            await create_global_template(title="  ", body="ok")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_create_rejects_bad_priority(self):
        from chat_templates import create_global_template

        with self.assertRaises(HTTPException) as ctx:
            await create_global_template(title="t", body="b", sort_order=-1)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_create_rejects_long_body(self):
        from chat_templates import create_global_template

        with self.assertRaises(HTTPException) as ctx:
            await create_global_template(title="t", body="x" * 2001)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_update_rejects_empty_body(self):
        from chat_templates import update_global_template

        fake_row = {
            "id": 1,
            "operator_id": None,
            "title": "t",
            "body": "old",
            "trigger_phrase": None,
            "sort_order": 10,
            "is_active": True,
            "created_at": None,
            "updated_at": None,
            "is_system": False,
            "version": 1,
            "created_by_operator_id": 1,
        }
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)
        mock_tx = MagicMock()
        mock_tx.__aenter__ = AsyncMock(return_value=None)
        mock_tx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction = MagicMock(return_value=mock_tx)
        mock_pool = MagicMock()
        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire

        with patch("db.get_pool", AsyncMock(return_value=mock_pool)):
            with self.assertRaises(HTTPException) as ctx:
                await update_global_template(1, body="   ")
        self.assertEqual(ctx.exception.status_code, 400)


class SharedTemplateRoutesAuthTests(unittest.TestCase):
    def test_shared_and_chat_endpoints_require_operator(self):
        for name in (
            "chat_list_shared_templates",
            "chat_create_shared_template",
            "chat_update_shared_template",
            "chat_delete_shared_template",
            "chat_reorder_shared_templates",
            "chat_quick_replies",
            "list_threads",
            "get_thread",
        ):
            fn = getattr(chat_operator, name)
            src = inspect.getsource(fn)
            self.assertIn(
                "get_current_operator",
                src,
                msg=f"{name} missing operator auth",
            )


class AutoReplyCooldownTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_cooldown_active(self):
        from chat_templates import maybe_apply_auto_replies

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                MagicMock(id=1, body="Ответ", trigger_phrase="test"),
            ]
        )
        mock_conn.fetchval = AsyncMock(return_value=99)

        mock_pool = MagicMock()
        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire

        with patch("db.get_pool", AsyncMock(return_value=mock_pool)):
            with patch("chat_templates.matches_trigger", return_value=True):
                with patch("chat_service.admin_send_message", AsyncMock()) as send_mock:
                    await maybe_apply_auto_replies(1, "test message")
                    send_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
