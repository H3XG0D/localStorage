"""Feature flag + list ACL for Sticker AI (no jose/auth import required)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from permissions import (
    PERM_STICKER_VIEW_ANY,
    attach_operator_permissions_sync,
    resolve_admin_permissions,
)
from sticker_ai import runtime as sticker_runtime
from sticker_ai.notify import NotifyAllowlist, StickerNotifier
from sticker_ai.service import StickerAiService


class HealthPayloadTests(unittest.TestCase):
    def test_default_disabled_mutations_false(self):
        with patch.object(sticker_runtime.settings, "sticker_ai_enabled", False):
            with patch.object(sticker_runtime.settings, "sticker_ai_provider", "null"):
                h = sticker_runtime.health_payload()
        self.assertFalse(h["enabled"])
        self.assertFalse(h["mutations"])
        self.assertTrue(h["ops_ai_isolated"])
        self.assertEqual(h["provider"], "null")
        self.assertIn("sticker_ai.generate", h["queues"])


class FeatureFlagTests(unittest.TestCase):
    def test_require_enabled_503(self):
        with patch.object(sticker_runtime, "is_enabled", return_value=False):
            with self.assertRaises(HTTPException) as ctx:
                sticker_runtime.require_enabled()
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertEqual(ctx.exception.detail, "sticker_ai_disabled")

    def test_require_enabled_ok(self):
        with patch.object(sticker_runtime, "is_enabled", return_value=True):
            sticker_runtime.require_enabled()

    def test_require_mutations_503(self):
        with patch.object(sticker_runtime, "is_enabled", return_value=True):
            with patch.object(sticker_runtime, "mutations_enabled", return_value=False):
                with self.assertRaises(HTTPException) as ctx:
                    sticker_runtime.require_mutations()
                self.assertEqual(ctx.exception.status_code, 503)
                self.assertEqual(ctx.exception.detail, "sticker_ai_mutations_disabled")


class ListAclTests(unittest.TestCase):
    def test_list_when_seeded(self):
        svc = StickerAiService(
            notifier=StickerNotifier(allowlist=NotifyAllowlist(chat_ids=frozenset({1})))
        )
        with patch("finance_access.can_view_finance_admin", return_value=True):
            perms = resolve_admin_permissions({"id": 1, "is_admin": True, "telegram_user_id": 1})
        admin = {"id": 1, "is_admin": True, "permissions": sorted(perms)}
        task = svc.create_task(admin, idea="hi sticker")
        out = svc.list_tasks(admin, status="all", limit=50)
        self.assertEqual(out["total"], 1)
        self.assertEqual(out["tasks"][0]["id"], task["id"])

    def test_operator_without_view_sees_empty(self):
        svc = StickerAiService()
        with patch("finance_access.can_view_finance_admin", return_value=True):
            perms = resolve_admin_permissions({"id": 1, "is_admin": True, "telegram_user_id": 1})
        owner = {"id": 1, "is_admin": True, "permissions": sorted(perms)}
        svc.create_task(owner, idea="owned")
        stranger = attach_operator_permissions_sync({"id": 99, "operator_roles": ["client"]})
        self.assertEqual(svc.list_tasks(stranger)["total"], 0)
        stranger["permissions"] = sorted(set(stranger["permissions"]) | {PERM_STICKER_VIEW_ANY})
        self.assertEqual(svc.list_tasks(stranger)["total"], 1)


if __name__ == "__main__":
    unittest.main()
