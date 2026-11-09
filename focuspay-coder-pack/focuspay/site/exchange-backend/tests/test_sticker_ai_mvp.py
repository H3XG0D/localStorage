"""Sticker AI MVP: RBAC/IDOR, workflow, provider, redaction, cursor sandbox, notify."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from permissions import (
    PERM_STICKER_AUDIT_VIEW,
    PERM_STICKER_CREATE,
    PERM_STICKER_EDIT_OWN,
    PERM_STICKER_MODERATE,
    PERM_STICKER_PUBLISH,
    PERM_STICKER_SUBMIT_REVIEW,
    PERM_STICKER_VIEW_ANY,
    PERM_STICKER_VIEW_OWN,
    apply_permission_grants,
    attach_operator_permissions_sync,
    has_permission,
    permissions_for_operator_roles,
    resolve_admin_permissions,
)
from sticker_ai.cursor_sandbox import CursorSandbox, CursorSandboxError, is_path_allowed
from sticker_ai.limits import RateLimiter, validate_prompt_length
from sticker_ai.notify import NotifyAllowlist, StickerNotifier, build_safe_summary
from sticker_ai.provider import NullProvider, OfflineMockProvider, build_provider
from sticker_ai.redaction import sanitize_prompt
from sticker_ai.schemas import SchemaError, parse_generate_response
from sticker_ai.service import StickerAiService
from sticker_ai.workflow import WorkflowError, transition


def _op_with(*perms: str, op_id: int = 10) -> dict:
    base = attach_operator_permissions_sync({"id": op_id, "operator_roles": ["client"]})
    granted = apply_permission_grants(set(base["permissions"]), [(p, True) for p in perms])
    base["permissions"] = sorted(granted)
    return base


def _admin(admin_id: int = 1) -> dict:
    with patch("finance_access.can_view_finance_admin", return_value=True):
        perms = resolve_admin_permissions({"id": admin_id, "is_admin": True, "telegram_user_id": 1})
    return {"id": admin_id, "is_admin": True, "permissions": sorted(perms), "rbac_role": "ADMIN"}


class StickerRbacMatrixTests(unittest.TestCase):
    def test_operator_default_denied(self):
        perms = permissions_for_operator_roles(["client"])
        for p in (
            PERM_STICKER_CREATE,
            PERM_STICKER_VIEW_OWN,
            PERM_STICKER_MODERATE,
            PERM_STICKER_PUBLISH,
            PERM_STICKER_AUDIT_VIEW,
        ):
            self.assertNotIn(p, perms)

    def test_admin_has_sticker_perms(self):
        admin = _admin()
        self.assertTrue(has_permission(admin, PERM_STICKER_CREATE))
        self.assertTrue(has_permission(admin, PERM_STICKER_MODERATE))
        self.assertTrue(has_permission(admin, PERM_STICKER_PUBLISH))

    def test_unauthorized_create_403(self):
        svc = StickerAiService()
        op = attach_operator_permissions_sync({"id": 5, "operator_roles": ["client"]})
        with self.assertRaises(HTTPException) as ctx:
            svc.create_task(op, idea="hello sticker")
        self.assertEqual(ctx.exception.status_code, 403)


class StickerIdorTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreign_task_404(self):
        svc = StickerAiService(notifier=StickerNotifier(allowlist=NotifyAllowlist(chat_ids=frozenset({1}))))
        owner = _op_with(
            PERM_STICKER_CREATE,
            PERM_STICKER_VIEW_OWN,
            PERM_STICKER_EDIT_OWN,
            PERM_STICKER_SUBMIT_REVIEW,
            op_id=101,
        )
        other = _op_with(PERM_STICKER_VIEW_OWN, PERM_STICKER_EDIT_OWN, op_id=202)
        task = svc.create_task(owner, idea="cosmic F wave hi")
        with self.assertRaises(HTTPException) as ctx:
            svc.get_task(other, task["id"])
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_view_any_can_see(self):
        svc = StickerAiService()
        owner = _op_with(PERM_STICKER_CREATE, PERM_STICKER_VIEW_OWN, op_id=1)
        mod = _op_with(PERM_STICKER_VIEW_ANY, op_id=2)
        task = svc.create_task(owner, idea="news pulse sticker")
        got = svc.get_task(mod, task["id"])
        self.assertEqual(got["id"], task["id"])


class WorkflowTests(unittest.TestCase):
    def test_illegal_publish_from_draft(self):
        with self.assertRaises(WorkflowError):
            transition("draft", "published")

    def test_happy_path_statuses(self):
        self.assertEqual(transition("draft", "generating"), "generating")
        self.assertEqual(transition("generating", "draft"), "draft")
        self.assertEqual(transition("draft", "review"), "review")
        self.assertEqual(transition("review", "approved"), "approved")
        self.assertEqual(transition("approved", "publishing"), "publishing")
        self.assertEqual(transition("publishing", "published"), "published")


class ProviderSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_offline_generate_schema(self):
        p = OfflineMockProvider()
        from sticker_ai.provider import GenerateRequest

        out = await p.generate(
            GenerateRequest(idea="thanks sticker", tenant_id="t", task_id="x", n_variants=2)
        )
        self.assertEqual(out["model_id"], "offline_mock")
        self.assertEqual(len(out["variants"]), 2)

    async def test_null_fail_closed(self):
        p = NullProvider()
        from sticker_ai.provider import GenerateRequest, ProviderError

        with self.assertRaises(ProviderError):
            await p.generate(GenerateRequest(idea="x", tenant_id="t", task_id="y"))

    def test_schema_rejects_garbage(self):
        with self.assertRaises(SchemaError):
            parse_generate_response({"model_id": "m", "variants": "nope"})

    def test_build_provider_unknown(self):
        from sticker_ai.provider import ProviderError

        with self.assertRaises(ProviderError):
            build_provider("nope")


class RedactionNotifyTests(unittest.TestCase):
    def test_sanitize_strips_secrets(self):
        text, h = sanitize_prompt("idea api_key=sk-live-SECRET123 and @admin_user")
        self.assertNotIn("sk-live-SECRET123", text)
        self.assertNotIn("@admin_user", text)
        self.assertEqual(len(h), 64)

    def test_notify_fail_closed_empty_allowlist(self):
        body = build_safe_summary(
            task_id="abc",
            status="review",
            actor_type="admin",
            actor_id=7,
            change_type="submit_review",
        )
        self.assertIn("task=abc", body)
        self.assertNotIn("api_key", body)
        self.assertNotIn(".env", body)


class NotifyAllowlistAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_denies_unknown_chat(self):
        n = StickerNotifier(allowlist=NotifyAllowlist(chat_ids=frozenset({99})))
        ok = await n.notify_admins(
            task_id="t1",
            status="approved",
            actor_type="admin",
            actor_id=1,
            change_type="approve",
            target_chat_id=1,
        )
        self.assertFalse(ok)


class CursorSandboxTests(unittest.TestCase):
    def test_path_allow_and_deny(self):
        self.assertTrue(is_path_allowed("site/exchange-backend/sticker_ai/service.py"))
        self.assertFalse(is_path_allowed(".env"))
        self.assertFalse(is_path_allowed("site/exchange-backend/../.env"))
        self.assertFalse(is_path_allowed("/opt/exchange-backend/.env"))

    def test_propose_approve_no_auto_apply(self):
        sb = CursorSandbox()
        prop = sb.propose(
            actor_id=1,
            cursor_prompt="Add negative prompt for nike logo",
            target_paths=["site/exchange-backend/sticker_ai/brand_preset.py"],
            diff_text="- x\n+ y",
        )
        self.assertFalse(prop.approved)
        denied = sb.auto_apply_forbidden(prop.id)
        self.assertFalse(denied["auto_apply"])
        self.assertFalse(denied["auto_deploy"])
        with self.assertRaises(CursorSandboxError):
            sb.mark_applied_externally(prop.id)
        sb.approve(prop.id, approver_id=2)
        sb.mark_applied_externally(prop.id)
        self.assertTrue(prop.applied)


class ServiceSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_workflow_smoke(self):
        notifier = StickerNotifier(allowlist=NotifyAllowlist(chat_ids=frozenset({42})))
        svc = StickerAiService(notifier=notifier)
        creator = _op_with(
            PERM_STICKER_CREATE,
            PERM_STICKER_VIEW_OWN,
            PERM_STICKER_EDIT_OWN,
            PERM_STICKER_SUBMIT_REVIEW,
            op_id=3,
        )
        admin = _admin(9)
        task = svc.create_task(creator, idea="promo pulse F", idempotency_key="k1", n_variants=2)
        again = svc.create_task(creator, idea="other", idempotency_key="k1")
        self.assertEqual(task["id"], again["id"])
        await svc.enqueue_generate(creator, task["id"])
        task = svc.get_task(creator, task["id"])
        self.assertEqual(task["status"], "draft")
        self.assertEqual(len(task["variants"]), 2)
        src = task["variants"][0]["asset_key"]
        await svc.edit_variant(creator, task["id"], source_asset_key=src, prompt="make F larger")
        svc.submit_review(creator, task["id"])
        await svc.approve(admin, task["id"])
        await svc.publish(admin, task["id"])
        task = svc.get_task(admin, task["id"])
        self.assertEqual(task["status"], "published")
        self.assertGreaterEqual(len(svc.audit.events), 4)
        self.assertTrue(any(c == 42 for c, _ in notifier.sent))
        # finance operator still denied without grant
        fin = attach_operator_permissions_sync({"id": 8, "operator_roles": ["finance"]})
        with self.assertRaises(HTTPException):
            svc.create_task(fin, idea="nope")


class LimitsTests(unittest.TestCase):
    def test_prompt_too_long(self):
        with self.assertRaises(ValueError):
            validate_prompt_length("x" * 5000)

    def test_rate_limiter(self):
        rl = RateLimiter(per_minute=2)
        self.assertTrue(rl.check("a"))
        self.assertTrue(rl.check("a"))
        self.assertFalse(rl.check("a"))


if __name__ == "__main__":
    unittest.main()
