"""Unit/security tests: PII redaction, AI audit ACL, news targeting guards."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from permissions import (
    PERM_AI_AUDIT_DELETE,
    PERM_AI_AUDIT_VIEW,
    attach_operator_permissions_sync,
    has_permission,
    permissions_for_operator_roles,
    resolve_admin_permissions,
    require_permission,
)
from privacy_redaction import content_hash, pseudonym, redact_text


class RedactionTests(unittest.TestCase):
    def test_redacts_email_phone_wallet_secrets(self):
        raw = (
            "user a@b.co phone +7 (999) 123-45-67 wallet TXyzabcdefghijklmnopqrsuvwxyz123456 "
            "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd "
            "api_key=sk-live-SECRETTOKEN123 Bearer eyJhbGciOiJIUzI1NiJ9.aaa.bbb "
            "tg_id=1234567890 @focus_user"
        )
        out = redact_text(raw)
        self.assertNotIn("a@b.co", out)
        self.assertNotIn("999", out)
        self.assertNotIn("sk-live-SECRETTOKEN123", out)
        self.assertNotIn("@focus_user", out)
        self.assertIn("[REDACTED]", out)

    def test_pseudonym_stable(self):
        self.assertEqual(pseudonym(42, prefix="op"), pseudonym(42, prefix="op"))
        self.assertNotEqual(pseudonym(42, prefix="op"), pseudonym(43, prefix="op"))

    def test_content_hash_changes(self):
        self.assertNotEqual(content_hash("a"), content_hash("b"))


class AiAuditPermissionTests(unittest.TestCase):
    def test_operator_no_audit_by_default(self):
        perms = permissions_for_operator_roles(["client"])
        self.assertNotIn(PERM_AI_AUDIT_VIEW, perms)
        self.assertNotIn(PERM_AI_AUDIT_DELETE, perms)

    def test_admin_has_audit(self):
        admin = {"id": 1, "is_admin": True, "telegram_user_id": 1097952683}
        with patch("finance_access.can_view_finance_admin", return_value=True):
            perms = resolve_admin_permissions(admin)
        self.assertIn(PERM_AI_AUDIT_VIEW, perms)
        self.assertIn(PERM_AI_AUDIT_DELETE, perms)

    def test_require_audit_blocks_operator(self):
        op = attach_operator_permissions_sync({"id": 7, "operator_roles": ["client"]})
        with self.assertRaises(HTTPException) as ctx:
            require_permission(op, PERM_AI_AUDIT_VIEW)
        self.assertEqual(ctx.exception.status_code, 403)


class NewsCategoryAllowlistTests(unittest.TestCase):
    def test_news_permission_not_on_client(self):
        from permissions import PERM_NEWS_BROADCAST

        perms = permissions_for_operator_roles(["client"])
        self.assertNotIn(PERM_NEWS_BROADCAST, perms)

class OpsAiAuditIdorTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_event_hides_foreign_rows(self):
        import ops_ai_audit

        fake_row = {
            "id": 99,
            "actor_type": "operator",
            "actor_id": 111,
            "tenant_scope": "ops",
            "expires_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            )
            + __import__("datetime").timedelta(days=1),
            "created_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            "correlation_id": "x",
            "event_type": "llm_chat",
            "consent_version": "ops-ai-privacy-v1",
            "request_hash": "a",
            "response_hash": "b",
            "redacted_request": {},
            "redacted_response": {},
            "meta": {},
        }

        class Conn:
            async def fetchrow(self, *a, **k):
                return fake_row

            async def execute(self, *a, **k):
                return "INSERT 0 1"

        class Pool:
            def acquire(self):
                return self

            async def __aenter__(self):
                return Conn()

            async def __aexit__(self, *a):
                return False

        principal = attach_operator_permissions_sync(
            {"id": 222, "operator_roles": ["client"]}
        )
        # grant view for IDOR check of object scope
        principal["permissions"] = sorted(
            set(principal["permissions"]) | {PERM_AI_AUDIT_VIEW}
        )

        with patch("ops_ai_audit.get_pool", new=AsyncMock(return_value=Pool())):
            with self.assertRaises(HTTPException) as ctx:
                await ops_ai_audit.get_event(99, principal=principal)
            self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
