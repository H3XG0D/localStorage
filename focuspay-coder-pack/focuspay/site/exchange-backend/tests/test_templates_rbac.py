"""Object ACL / IDOR / system / optimistic lock для shared templates."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from chat_templates import assert_can_mutate_template, update_global_template
from permissions import attach_operator_permissions_sync


def _op(oid: int, roles=("client",), **extra):
    row = {"id": oid, "operator_roles": list(roles), "operator_role": roles[0], **extra}
    return attach_operator_permissions_sync(row)


def _admin(aid: int = 1):
    return {
        "id": aid,
        "is_admin": True,
        "permissions": [
            "templates.view",
            "templates.create",
            "templates.edit_own",
            "templates.edit_any",
            "templates.delete_own",
            "templates.delete_any",
            "templates.edit_system",
            "templates.manage_priority",
        ],
        "rbac_role": "ADMIN",
    }


class TemplateObjectAclTests(unittest.TestCase):
    def test_owner_can_edit_own_non_system(self):
        row = {
            "id": 10,
            "operator_id": None,
            "created_by_operator_id": 5,
            "is_system": False,
            "version": 1,
        }
        assert_can_mutate_template(_op(5), row, action="update")

    def test_other_operator_cannot_edit(self):
        row = {
            "id": 10,
            "operator_id": None,
            "created_by_operator_id": 5,
            "is_system": False,
            "version": 1,
        }
        with self.assertRaises(HTTPException) as ctx:
            assert_can_mutate_template(_op(9), row, action="update")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_system_blocked_without_edit_system(self):
        row = {
            "id": 1,
            "operator_id": None,
            "created_by_operator_id": None,
            "is_system": True,
            "version": 1,
        }
        with self.assertRaises(HTTPException) as ctx:
            assert_can_mutate_template(_op(5), row, action="update")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_can_edit_system(self):
        row = {
            "id": 1,
            "operator_id": None,
            "created_by_operator_id": None,
            "is_system": True,
            "version": 1,
        }
        # admin via edit_system in permissions list
        principal = {
            "id": 1,
            "is_admin": True,
            "permissions": ["templates.edit_system", "templates.edit_any", "templates.delete_any"],
        }
        assert_can_mutate_template(principal, row, action="update")
        assert_can_mutate_template(principal, row, action="delete")


class TemplateOptimisticLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_version_mismatch_returns_409(self):
        fake_row = {
            "id": 7,
            "operator_id": None,
            "title": "t",
            "body": "b",
            "trigger_phrase": None,
            "sort_order": 10,
            "is_active": True,
            "created_at": None,
            "updated_at": None,
            "is_system": False,
            "version": 3,
            "created_by_operator_id": 5,
        }
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)
        mock_conn.execute = AsyncMock()
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
                await update_global_template(
                    7,
                    title="new",
                    version=2,
                    principal=_op(5),
                )
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
