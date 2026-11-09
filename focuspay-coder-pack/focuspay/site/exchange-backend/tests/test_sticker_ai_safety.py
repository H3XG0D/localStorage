"""Extra Sticker AI safety tests: approve gate, queue, storage, redaction, mutations flag."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from permissions import (
    PERM_STICKER_CREATE,
    PERM_STICKER_EDIT_OWN,
    PERM_STICKER_PUBLISH,
    PERM_STICKER_SUBMIT_REVIEW,
    PERM_STICKER_VIEW_OWN,
    apply_permission_grants,
    attach_operator_permissions_sync,
    resolve_admin_permissions,
)
from privacy_redaction import redact_text
from sticker_ai import runtime as sticker_runtime
from sticker_ai.notify import NotifyAllowlist, StickerNotifier
from sticker_ai.provider import NullProvider, OfflineMockProvider
from sticker_ai.queue import JOB_FAILED, JOB_QUEUED, JOB_SUCCEEDED, InMemoryQueue
from sticker_ai.service import StickerAiService
from sticker_ai.storage import InMemoryAssetStore, StorageError


def _op_with(*perms: str, op_id: int = 10) -> dict:
    base = attach_operator_permissions_sync({"id": op_id, "operator_roles": ["client"]})
    granted = apply_permission_grants(set(base["permissions"]), [(p, True) for p in perms])
    base["permissions"] = sorted(granted)
    return base


def _admin(admin_id: int = 1) -> dict:
    with patch("finance_access.can_view_finance_admin", return_value=True):
        perms = resolve_admin_permissions({"id": admin_id, "is_admin": True, "telegram_user_id": 1})
    return {"id": admin_id, "is_admin": True, "permissions": sorted(perms), "rbac_role": "ADMIN"}


class ApproveGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_without_approve_409(self):
        svc = StickerAiService(notifier=StickerNotifier(allowlist=NotifyAllowlist()))
        creator = _op_with(
            PERM_STICKER_CREATE,
            PERM_STICKER_VIEW_OWN,
            PERM_STICKER_EDIT_OWN,
            PERM_STICKER_SUBMIT_REVIEW,
            op_id=3,
        )
        admin = _admin(9)
        task = svc.create_task(creator, idea="need approve first")
        await svc.enqueue_generate(creator, task["id"])
        svc.submit_review(creator, task["id"])
        # Still in review — publish must fail
        with self.assertRaises(HTTPException) as ctx:
            await svc.publish(admin, task["id"])
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_publish_perm_required(self):
        svc = StickerAiService()
        admin = _admin(1)
        task = svc.create_task(admin, idea="x")
        await svc.enqueue_generate(admin, task["id"])
        svc.submit_review(admin, task["id"])
        await svc.approve(admin, task["id"])
        no_pub = _op_with(PERM_STICKER_VIEW_OWN, PERM_STICKER_CREATE, op_id=55)
        # grant view any via copying task visibility won't help — need publish perm
        with self.assertRaises(HTTPException) as ctx:
            await svc.publish(no_pub, task["id"])
        self.assertEqual(ctx.exception.status_code, 403)


class QueueIdempotencyTests(unittest.TestCase):
    def test_statuses_and_idempotent_enqueue(self):
        q = InMemoryQueue()
        j1 = q.enqueue("sticker_ai.generate", {"task_id": "a"}, idempotency_key="k1")
        self.assertEqual(j1.status, JOB_QUEUED)
        j2 = q.enqueue("sticker_ai.generate", {"task_id": "a"}, idempotency_key="k1")
        self.assertEqual(j1.id, j2.id)
        q.mark_running(j1.id)
        q.mark_succeeded(j1.id)
        self.assertEqual(q.get(j1.id).status, JOB_SUCCEEDED)
        snap = q.snapshot()
        self.assertIn("depths", snap)
        self.assertNotIn("api_token", str(snap))


class ProviderFailureServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_null_provider_marks_failed_job(self):
        svc = StickerAiService(provider=NullProvider(), notifier=StickerNotifier(allowlist=NotifyAllowlist()))
        admin = _admin()
        task = svc.create_task(admin, idea="will fail generate")
        await svc.enqueue_generate(admin, task["id"])
        task = svc.get_task(admin, task["id"])
        self.assertEqual(task["status"], "draft")
        job = svc.queue.get(task["last_job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.status, JOB_FAILED)
        self.assertTrue(any(getattr(e, "event_type", None) == "generate_failed" for e in svc.audit.events))


class StorageIsolationTests(unittest.TestCase):
    def test_rejects_path_traversal(self):
        store = InMemoryAssetStore(tenant_id="focuspay")
        with self.assertRaises(StorageError):
            store.put("../etc/passwd.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)

    def test_quarantine_bad_magic(self):
        store = InMemoryAssetStore(tenant_id="focuspay")
        with self.assertRaises(StorageError) as ctx:
            store.put("focuspay/t1/bad.bin", b"not-an-image")
        self.assertIn("quarantined:", str(ctx.exception))

    def test_tenant_mismatch(self):
        store = InMemoryAssetStore(tenant_id="focuspay")
        with self.assertRaises(StorageError):
            store.put("sticker_ai/other_tenant/x.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)

class AssetAclEditTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreign_asset_key_rejected(self):
        svc = StickerAiService(provider=OfflineMockProvider())
        admin = _admin()
        task = svc.create_task(admin, idea="asset acl")
        await svc.enqueue_generate(admin, task["id"])
        with self.assertRaises(HTTPException) as ctx:
            await svc.edit_variant(
                admin,
                task["id"],
                source_asset_key="focuspay/other-task/v0/var_0.png",
                prompt="hack",
            )
        self.assertEqual(ctx.exception.status_code, 400)


class SecretRedactionExtraTests(unittest.TestCase):
    def test_internal_token_and_urls(self):
        text = redact_text(
            "X-Internal-Token: supersecretvalue123 "
            "sticker_ai_worker_token=tok_ABCDEF123456 "
            "http://127.0.0.1:8000/api?access_token=abc.def.ghi "
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaa.bbb"
        )
        self.assertNotIn("supersecretvalue123", text)
        self.assertNotIn("tok_ABCDEF123456", text)
        self.assertNotIn("access_token=abc.def.ghi", text)
        self.assertIn("[REDACTED]", text)
        self.assertIn("[INTERNAL_URL]", text)


class MutationsFlagTests(unittest.TestCase):
    def test_mutations_require_both_flags(self):
        with patch.object(sticker_runtime.settings, "sticker_ai_enabled", True):
            with patch.object(sticker_runtime.settings, "sticker_ai_mutations_enabled", False):
                self.assertTrue(sticker_runtime.is_enabled())
                self.assertFalse(sticker_runtime.mutations_enabled())
                with self.assertRaises(HTTPException) as ctx:
                    sticker_runtime.require_mutations()
                self.assertEqual(ctx.exception.status_code, 503)
                self.assertEqual(ctx.exception.detail, "sticker_ai_mutations_disabled")

    def test_health_observation_reasons(self):
        with patch.object(sticker_runtime.settings, "sticker_ai_enabled", False):
            with patch.object(sticker_runtime.settings, "sticker_ai_mutations_enabled", False):
                with patch.object(sticker_runtime.settings, "sticker_ai_provider", "null"):
                    h = sticker_runtime.health_payload(principal={"permissions": ["sticker.view_own"]})
        self.assertFalse(h["enabled"])
        self.assertFalse(h["mutations"])
        self.assertFalse(h["secrets_exposed"])
        self.assertIn("flag_disabled", h["observation_reasons"])
        self.assertIn("sticker.view_own", h["my_permissions"])
        self.assertNotIn("worker_token", str(h).lower())


class FullMockLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_controlled_lifecycle_offline_mock(self):
        svc = StickerAiService(
            provider=OfflineMockProvider(),
            notifier=StickerNotifier(allowlist=NotifyAllowlist(chat_ids=frozenset({7}))),
        )
        admin = _admin(2)
        task = svc.create_task(admin, idea="brand hello", idempotency_key="life-1")
        await svc.enqueue_generate(admin, task["id"])
        task = svc.get_task(admin, task["id"])
        self.assertEqual(task["status"], "draft")
        self.assertTrue(task["variants"])
        svc.submit_review(admin, task["id"])
        await svc.approve(admin, task["id"])
        await svc.publish(admin, task["id"])
        self.assertEqual(svc.get_task(admin, task["id"])["status"], "published")
        # second publish of same idempotency succeeds via queue idempotency but status already published → 409
        with self.assertRaises(HTTPException) as ctx:
            await svc.publish(admin, task["id"])
        self.assertEqual(ctx.exception.status_code, 409)


class AssetServeTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_can_fetch_generated_asset(self):
        svc = StickerAiService(provider=OfflineMockProvider())
        admin = _admin()
        task = svc.create_task(admin, idea="show sticker")
        await svc.enqueue_generate(admin, task["id"])
        task = svc.get_task(admin, task["id"])
        key = task["variants"][0]["asset_key"]
        blob, ctype = svc.get_asset(admin, task["id"], key)
        self.assertTrue(blob.startswith(b"\x89PNG"))
        self.assertIn("image/", ctype)

    async def test_foreign_asset_404(self):
        svc = StickerAiService(provider=OfflineMockProvider())
        admin = _admin()
        task = svc.create_task(admin, idea="acl asset")
        await svc.enqueue_generate(admin, task["id"])
        with self.assertRaises(HTTPException) as ctx:
            svc.get_asset(admin, task["id"], "focuspay/other/v0/var_0.png")
        self.assertEqual(ctx.exception.status_code, 404)


class LelouchProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_from_b64_png_no_token_in_error(self):
        import base64
        import json

        from sticker_ai.provider import LelouchImageProvider, _png_bytes

        blob = _png_bytes(64, 64, (20, 20, 22, 255))
        body = json.dumps({"data": [{"b64_json": base64.b64encode(blob).decode()}]}).encode()
        secret = "sk-live-SUPERSECRET-TOKEN-DO-NOT-LEAK"

        class _Resp:
            status = 200

            async def read(self):
                return body

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class _Session:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def post(self, url, json=None, headers=None):
                self.url = url
                self.headers = headers
                self.payload = json
                return _Resp()

        p = LelouchImageProvider(
            base_url="https://example.invalid/v1",
            api_token=secret,
            model="gpt-image-2",
            session_factory=_Session,
        )
        from sticker_ai.provider import GenerateRequest

        out = await p.generate(GenerateRequest(idea="hi sticker", tenant_id="t", task_id="x", n_variants=1))
        self.assertTrue(out["model_id"].startswith("lelouch:"))
        self.assertEqual(len(out["variants"]), 1)
        asset = out["_assets"][out["variants"][0]["asset_key"]]
        self.assertTrue(asset.startswith(b"\x89PNG"))
        dumped = json.dumps(out["variants"]) + str(out["model_id"])
        self.assertNotIn(secret, dumped)

    def test_missing_token_fail_closed(self):
        from sticker_ai.provider import ProviderError, build_provider

        with self.assertRaises(ProviderError):
            build_provider("lelouch", base_url="https://example.invalid/v1", api_token="")


if __name__ == "__main__":
    unittest.main()
