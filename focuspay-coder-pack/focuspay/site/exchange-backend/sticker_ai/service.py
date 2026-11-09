"""Sticker AI orchestration (in-memory MVP; HTTP mutations gated by STICKER_AI_MUTATIONS_ENABLED)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from privacy_redaction import content_hash
from sticker_ai.audit import InMemoryAuditLog
from sticker_ai.brand_preset import DEFAULT_BRAND
from sticker_ai.constants import (
    QUEUE_EDIT,
    QUEUE_GENERATE,
    QUEUE_PUBLISH,
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_EDITING,
    STATUS_GENERATING,
    STATUS_PUBLISHED,
    STATUS_PUBLISHING,
    STATUS_QUARANTINED,
    STATUS_REJECTED,
    STATUS_REVIEW,
)
from sticker_ai.cursor_sandbox import CursorSandbox
from sticker_ai.limits import (
    DEFAULT_LIMITS,
    IdempotencyStore,
    RateLimiter,
    StickerLimits,
    validate_prompt_length,
)
from sticker_ai.notify import NotifyAllowlist, StickerNotifier
from sticker_ai.provider import ImageProvider, OfflineMockProvider, ProviderError
from sticker_ai.queue import InMemoryQueue
from sticker_ai.rbac_checks import (
    require_audit_view,
    require_create,
    require_edit_task,
    require_moderate,
    require_publish,
    require_submit_review,
    require_view_task,
)
from sticker_ai.redaction import sanitize_prompt
from sticker_ai.storage import InMemoryAssetStore, StorageError
from sticker_ai.workflow import WorkflowError, transition

logger = logging.getLogger("sticker_ai.service")


def _actor_type(principal: dict) -> str:
    return "admin" if principal.get("is_admin") else "operator"


def _task_asset_keys(task: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for v in task.get("variants") or []:
        if isinstance(v, dict) and v.get("asset_key"):
            keys.add(str(v["asset_key"]))
    for ver in task.get("versions") or []:
        if not isinstance(ver, dict):
            continue
        if ver.get("asset_key"):
            keys.add(str(ver["asset_key"]))
        for v in ver.get("variants") or []:
            if isinstance(v, dict) and v.get("asset_key"):
                keys.add(str(v["asset_key"]))
    return keys


@dataclass
class StickerAiService:
    provider: ImageProvider = field(default_factory=OfflineMockProvider)
    store: InMemoryAssetStore = field(default_factory=InMemoryAssetStore)
    queue: InMemoryQueue = field(default_factory=InMemoryQueue)
    audit: InMemoryAuditLog = field(default_factory=InMemoryAuditLog)
    notifier: StickerNotifier = field(
        default_factory=lambda: StickerNotifier(allowlist=NotifyAllowlist())
    )
    cursor: CursorSandbox = field(default_factory=CursorSandbox)
    limits: StickerLimits = DEFAULT_LIMITS
    tenant_id: str = "focuspay"
    _tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    _rate: RateLimiter | None = None
    _idem: IdempotencyStore | None = None

    def __post_init__(self) -> None:
        if self._rate is None:
            self._rate = RateLimiter(per_minute=self.limits.rate_per_minute)
        if self._idem is None:
            self._idem = IdempotencyStore(ttl_sec=self.limits.idempotency_ttl_sec)
        # Keep store tenant aligned with service tenant.
        if getattr(self.store, "tenant_id", None) != self.tenant_id:
            try:
                self.store.tenant_id = self.tenant_id  # type: ignore[attr-defined]
            except Exception:
                logger.debug("sticker store tenant_id not writable", exc_info=True)

    def _rate_check(self, principal: dict) -> None:
        key = f"actor:{principal.get('id')}"
        if self._rate is None:
            raise HTTPException(status_code=503, detail="rate_limiter_unavailable")
        if not self._rate.check(key):
            raise HTTPException(status_code=429, detail="rate_limited")

    def create_task(
        self,
        principal: dict,
        *,
        idea: str,
        idempotency_key: str | None = None,
        n_variants: int = 2,
    ) -> dict[str, Any]:
        require_create(principal)
        self._rate_check(principal)
        if idempotency_key:
            if self._idem is None:
                raise HTTPException(status_code=503, detail="idempotency_unavailable")
            existing = self._idem.get(idempotency_key)
            if existing and existing in self._tasks:
                return self._tasks[existing]
        idea_s, idea_hash = sanitize_prompt(idea, max_len=self.limits.max_idea_chars)
        if not idea_s:
            raise HTTPException(status_code=400, detail="empty_idea")
        task_id = str(uuid4())
        task = {
            "id": task_id,
            "tenant_id": self.tenant_id,
            "owner_id": int(principal["id"]),
            "status": STATUS_DRAFT,
            "idea_hash": idea_hash,
            "idea_redacted": idea_s[:240],
            "n_variants": max(1, min(int(n_variants), self.limits.max_variants)),
            "variants": [],
            "versions": [],
            "last_job_id": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._tasks[task_id] = task
        if idempotency_key:
            if self._idem is None:
                raise HTTPException(status_code=503, detail="idempotency_unavailable")
            self._idem.put(idempotency_key, task_id)
        self.audit.write(
            actor_type=_actor_type(principal),
            actor_id=int(principal["id"]),
            tenant_id=self.tenant_id,
            event_type="task_created",
            prompt=idea_s,
            meta={"task_id": task_id, "status": STATUS_DRAFT, "change_type": "create"},
        )
        logger.info("sticker_task_created task_id=%s actor=%s", task_id, principal.get("id"))
        return task

    def get_task(self, principal: dict, task_id: str) -> dict[str, Any]:
        return require_view_task(principal, self._tasks.get(task_id))

    def get_asset(self, principal: dict, task_id: str, asset_key: str) -> tuple[bytes, str]:
        """Return image bytes + content-type. IDOR / unknown key → 404."""
        task = require_view_task(principal, self._tasks.get(task_id))
        key = str(asset_key or "").strip()
        if not key or key not in _task_asset_keys(task):
            raise HTTPException(status_code=404, detail="not_found")
        blob = self.store.get(key)
        if not blob:
            raise HTTPException(status_code=404, detail="asset_missing")
        meta = self.store.meta(key) or {}
        ctype = str(meta.get("content_type") or "image/png")
        return blob, ctype

    def list_tasks(self, principal: dict, *, status: str | None = None, limit: int = 50) -> dict[str, Any]:
        from sticker_ai.rbac_checks import can_view_task

        items = []
        for task in self._tasks.values():
            if status and status != "all" and task.get("status") != status:
                continue
            if can_view_task(principal, task):
                items.append(task)
        items.sort(key=lambda t: str(t.get("updated_at") or ""), reverse=True)
        lim = max(1, min(int(limit), 100))
        return {"tasks": items[:lim], "total": len(items)}

    def list_audit(self, principal: dict, *, limit: int = 50) -> dict[str, Any]:
        require_audit_view(principal)
        events = list(getattr(self.audit, "events", []) or [])
        events = events[-max(1, min(int(limit), 200)) :]
        # Events already redacted by InMemoryAuditLog — serialize dataclass safely.
        out = []
        for e in reversed(events):
            out.append(
                {
                    "id": getattr(e, "id", None),
                    "actor_type": getattr(e, "actor_type", None),
                    "actor_id": getattr(e, "actor_id", None),
                    "tenant_id": getattr(e, "tenant_id", None),
                    "event_type": getattr(e, "event_type", None),
                    "prompt_hash": getattr(e, "prompt_hash", None),
                    "redacted_prompt_preview": getattr(e, "redacted_prompt_preview", None),
                    "model_id": getattr(e, "model_id", None),
                    "meta": getattr(e, "meta", {}) or {},
                    "created_at": (
                        e.created_at.isoformat()
                        if getattr(e, "created_at", None) is not None and hasattr(e.created_at, "isoformat")
                        else getattr(e, "created_at", None)
                    ),
                }
            )
        return {"events": out, "total": len(out)}

    async def enqueue_generate(
        self,
        principal: dict,
        task_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        task = require_edit_task(principal, self._tasks.get(task_id))
        self._rate_check(principal)
        try:
            task["status"] = transition(task["status"], STATUS_GENERATING)
        except WorkflowError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        job = self.queue.enqueue(
            QUEUE_GENERATE,
            {"task_id": task_id, "actor_id": int(principal["id"])},
            idempotency_key=idempotency_key or f"generate:{task_id}:{task.get('updated_at')}",
        )
        task["last_job_id"] = job.id
        self.audit.write(
            actor_type=_actor_type(principal),
            actor_id=int(principal["id"]),
            tenant_id=self.tenant_id,
            event_type="generate_enqueued",
            prompt=task.get("idea_redacted"),
            meta={
                "task_id": task_id,
                "from_status": STATUS_DRAFT,
                "to_status": STATUS_GENERATING,
                "queue": QUEUE_GENERATE,
                "job_id": job.id,
                "job_status": job.status,
                "change_type": "generate",
            },
        )
        self.queue.mark_running(job.id)
        await self._process_generate(
            task_id,
            job_id=job.id,
            actor_id=int(principal["id"]),
            actor_is_admin=bool(principal.get("is_admin")),
        )
        return task

    async def _process_generate(
        self, task_id: str, *, job_id: str, actor_id: int, actor_is_admin: bool
    ) -> None:
        task = self._tasks[task_id]
        try:
            from sticker_ai.provider import GenerateRequest

            result = await self.provider.generate(
                GenerateRequest(
                    idea=str(task.get("idea_redacted") or ""),
                    tenant_id=self.tenant_id,
                    task_id=task_id,
                    n_variants=int(task.get("n_variants") or 2),
                    brand=DEFAULT_BRAND,
                )
            )
            assets = result.pop("_assets", {})
            for key, blob in assets.items():
                try:
                    self.store.put(key, blob)
                except StorageError:
                    task["status"] = transition(STATUS_GENERATING, STATUS_QUARANTINED)
                    self.queue.mark_failed(job_id, error="storage_quarantine")
                    return
            version = {
                "id": str(uuid4()),
                "kind": "generate",
                "model_id": result.get("model_id"),
                "variants": result.get("variants"),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            task["variants"] = result.get("variants") or []
            task["versions"].append(version)
            task["status"] = transition(STATUS_GENERATING, STATUS_DRAFT)
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.queue.mark_succeeded(job_id)
            self.audit.write(
                actor_type="admin" if actor_is_admin else "operator",
                actor_id=actor_id,
                tenant_id=self.tenant_id,
                event_type="generate_done",
                model_id=str(result.get("model_id")),
                meta={
                    "task_id": task_id,
                    "version_id": version["id"],
                    "status": STATUS_DRAFT,
                    "result": "ok",
                    "job_id": job_id,
                    "change_type": "generate_done",
                    "params_digest": content_hash(str(result.get("variants"))),
                },
            )
            await self.notifier.notify_admins(
                task_id=task_id,
                status=STATUS_DRAFT,
                actor_type="admin" if actor_is_admin else "operator",
                actor_id=actor_id,
                change_type="generate_done",
            )
        except ProviderError as e:
            task["status"] = transition(STATUS_GENERATING, STATUS_DRAFT)
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.queue.mark_failed(job_id, error=str(e)[:120])
            self.audit.write(
                actor_type="admin" if actor_is_admin else "operator",
                actor_id=actor_id,
                tenant_id=self.tenant_id,
                event_type="generate_failed",
                meta={
                    "task_id": task_id,
                    "status": STATUS_DRAFT,
                    "result": str(e)[:120],
                    "job_id": job_id,
                    "change_type": "generate_failed",
                },
            )
            logger.info("sticker_generate_failed task_id=%s err=%s", task_id, str(e)[:80])

    async def edit_variant(
        self,
        principal: dict,
        task_id: str,
        *,
        source_asset_key: str,
        prompt: str,
        mask_asset_key: str | None = None,
    ) -> dict[str, Any]:
        task = require_edit_task(principal, self._tasks.get(task_id))
        self._rate_check(principal)
        allowed = _task_asset_keys(task)
        if source_asset_key not in allowed:
            raise HTTPException(status_code=400, detail="source_asset_not_in_task")
        if mask_asset_key and mask_asset_key not in allowed:
            raise HTTPException(status_code=400, detail="mask_asset_not_in_task")
        prompt_s = validate_prompt_length(prompt, limits=self.limits)
        prompt_s, _ = sanitize_prompt(prompt_s)
        try:
            task["status"] = transition(task["status"], STATUS_EDITING)
        except WorkflowError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        job = self.queue.enqueue(
            QUEUE_EDIT,
            {"task_id": task_id, "source_asset_key": source_asset_key},
            idempotency_key=f"edit:{task_id}:{content_hash(source_asset_key + ':' + prompt_s)[:16]}",
        )
        task["last_job_id"] = job.id
        self.queue.mark_running(job.id)
        from sticker_ai.provider import EditRequest

        try:
            result = await self.provider.edit(
                EditRequest(
                    prompt=prompt_s,
                    tenant_id=self.tenant_id,
                    task_id=task_id,
                    source_asset_key=source_asset_key,
                    mask_asset_key=mask_asset_key,
                )
            )
            assets = result.pop("_assets", {})
            for key, blob in assets.items():
                self.store.put(key, blob)
            version = {
                "id": str(uuid4()),
                "kind": "edit",
                "model_id": result.get("model_id"),
                "asset_key": result.get("asset_key"),
                "source_asset_key": source_asset_key,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            task["versions"].append(version)
            task["status"] = transition(STATUS_EDITING, STATUS_DRAFT)
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.queue.mark_succeeded(job.id)
            self.audit.write(
                actor_type=_actor_type(principal),
                actor_id=int(principal["id"]),
                tenant_id=self.tenant_id,
                event_type="edit_done",
                prompt=prompt_s,
                model_id=str(result.get("model_id")),
                meta={
                    "task_id": task_id,
                    "version_id": version["id"],
                    "job_id": job.id,
                    "change_type": "edit",
                    "diff_summary": f"edit:{source_asset_key}->{result.get('asset_key')}",
                    "result": "ok",
                },
            )
            await self.notifier.notify_admins(
                task_id=task_id,
                status=STATUS_DRAFT,
                actor_type=_actor_type(principal),
                actor_id=int(principal["id"]),
                change_type="edit_done",
            )
        except (ProviderError, StorageError) as e:
            task["status"] = transition(STATUS_EDITING, STATUS_DRAFT)
            self.queue.mark_failed(job.id, error=str(e)[:120])
            raise HTTPException(status_code=502, detail=str(e)[:200]) from e
        return task

    def submit_review(self, principal: dict, task_id: str) -> dict[str, Any]:
        task = require_submit_review(principal, self._tasks.get(task_id))
        try:
            task["status"] = transition(task["status"], STATUS_REVIEW)
        except WorkflowError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.audit.write(
            actor_type=_actor_type(principal),
            actor_id=int(principal["id"]),
            tenant_id=self.tenant_id,
            event_type="submit_review",
            meta={"task_id": task_id, "to_status": STATUS_REVIEW, "change_type": "submit_review"},
        )
        return task

    async def approve(self, principal: dict, task_id: str) -> dict[str, Any]:
        require_moderate(principal)
        task = require_view_task(principal, self._tasks.get(task_id))
        try:
            task["status"] = transition(task["status"], STATUS_APPROVED)
        except WorkflowError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.audit.write(
            actor_type="admin",
            actor_id=int(principal["id"]),
            tenant_id=self.tenant_id,
            event_type="approved",
            meta={
                "task_id": task_id,
                "to_status": STATUS_APPROVED,
                "approval": "approved",
                "change_type": "approve",
            },
        )
        await self.notifier.notify_admins(
            task_id=task_id,
            status=STATUS_APPROVED,
            actor_type="admin",
            actor_id=int(principal["id"]),
            change_type="approve",
        )
        return task

    def reject(self, principal: dict, task_id: str, *, reason: str = "") -> dict[str, Any]:
        require_moderate(principal)
        task = require_view_task(principal, self._tasks.get(task_id))
        try:
            task["status"] = transition(task["status"], STATUS_REJECTED)
        except WorkflowError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        reason_s, reason_hash = sanitize_prompt(reason or "rejected", max_len=500)
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.audit.write(
            actor_type="admin",
            actor_id=int(principal["id"]),
            tenant_id=self.tenant_id,
            event_type="rejected",
            prompt=reason_s,
            meta={
                "task_id": task_id,
                "to_status": STATUS_REJECTED,
                "approval": "rejected",
                "change_type": "reject",
                "params_digest": reason_hash,
            },
        )
        return task

    async def publish(self, principal: dict, task_id: str) -> dict[str, Any]:
        require_publish(principal)
        task = require_view_task(principal, self._tasks.get(task_id))
        # Hard gate: only approved → publishing (workflow). Draft/review without approve → 409.
        try:
            task["status"] = transition(task["status"], STATUS_PUBLISHING)
        except WorkflowError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        job = self.queue.enqueue(
            QUEUE_PUBLISH,
            {"task_id": task_id},
            idempotency_key=f"publish:{task_id}",
        )
        task["last_job_id"] = job.id
        self.queue.mark_running(job.id)
        # MVP: mark published without calling Telegram (no token / no production side-effect).
        task["status"] = transition(STATUS_PUBLISHING, STATUS_PUBLISHED)
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.queue.mark_succeeded(job.id)
        self.audit.write(
            actor_type="admin",
            actor_id=int(principal["id"]),
            tenant_id=self.tenant_id,
            event_type="published",
            meta={
                "task_id": task_id,
                "to_status": STATUS_PUBLISHED,
                "queue": QUEUE_PUBLISH,
                "job_id": job.id,
                "result": "mock_published",
                "change_type": "publish",
            },
        )
        await self.notifier.notify_admins(
            task_id=task_id,
            status=STATUS_PUBLISHED,
            actor_type="admin",
            actor_id=int(principal["id"]),
            change_type="publish",
        )
        return task
