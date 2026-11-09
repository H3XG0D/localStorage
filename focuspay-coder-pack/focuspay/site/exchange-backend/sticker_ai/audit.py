"""Redacted audit log for Sticker AI (separate namespace from Ops AI)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from privacy_redaction import content_hash, redact_mapping, redact_text
from sticker_ai.constants import AUDIT_NAMESPACE


AUDIT_META_ALLOW = frozenset(
    {
        "task_id",
        "version_id",
        "variant_id",
        "model_id",
        "status",
        "from_status",
        "to_status",
        "change_type",
        "queue",
        "approval",
        "result",
        "diff_summary",
        "params_digest",
        "ui_path",
        "job_id",
        "job_status",
    }
)


@dataclass
class AuditEvent:
    id: str
    actor_type: str
    actor_id: int
    tenant_id: str
    event_type: str
    prompt_hash: str | None
    redacted_prompt_preview: str | None
    model_id: str | None
    meta: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class InMemoryAuditLog:
    events: list[AuditEvent] = field(default_factory=list)

    def write(
        self,
        *,
        actor_type: str,
        actor_id: int,
        tenant_id: str,
        event_type: str,
        prompt: str | None = None,
        model_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AuditEvent:
        preview = None
        ph = None
        if prompt:
            preview = redact_text(prompt, keep_short_ids=True)[:240]
            ph = content_hash(preview)
        safe_meta = redact_mapping(meta or {}, allow=AUDIT_META_ALLOW)
        safe_meta["namespace"] = AUDIT_NAMESPACE
        ev = AuditEvent(
            id=str(uuid4()),
            actor_type=actor_type,
            actor_id=int(actor_id),
            tenant_id=str(tenant_id),
            event_type=str(event_type),
            prompt_hash=ph,
            redacted_prompt_preview=preview,
            model_id=model_id,
            meta=safe_meta,
        )
        self.events.append(ev)
        return ev

    def for_task(self, task_id: str) -> list[AuditEvent]:
        return [e for e in self.events if e.meta.get("task_id") == task_id]
