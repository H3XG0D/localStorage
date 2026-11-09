"""Shared constants — queues, storage, statuses (separate from Ops AI)."""
from __future__ import annotations

STORAGE_PREFIX = "sticker_ai"
QUARANTINE_PREFIX = "sticker_ai/_quarantine"

QUEUE_GENERATE = "sticker_ai.generate"
QUEUE_EDIT = "sticker_ai.edit"
QUEUE_PUBLISH = "sticker_ai.publish"

AUDIT_NAMESPACE = "sticker_ai"

STATUS_DRAFT = "draft"
STATUS_GENERATING = "generating"
STATUS_EDITING = "editing"
STATUS_REVIEW = "review"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_PUBLISHING = "publishing"
STATUS_PUBLISHED = "published"
STATUS_QUARANTINED = "quarantined"

STATUSES: frozenset[str] = frozenset(
    {
        STATUS_DRAFT,
        STATUS_GENERATING,
        STATUS_EDITING,
        STATUS_REVIEW,
        STATUS_APPROVED,
        STATUS_REJECTED,
        STATUS_PUBLISHING,
        STATUS_PUBLISHED,
        STATUS_QUARANTINED,
    }
)

# UI deep-link template (no secrets). Admin panel path is conventional.
UI_TASK_PATH_TMPL = "/x8/sticker-ai/tasks/{task_id}"
