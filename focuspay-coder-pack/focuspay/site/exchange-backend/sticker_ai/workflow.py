"""Draft → … → published state machine."""
from __future__ import annotations

from sticker_ai.constants import (
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


class WorkflowError(ValueError):
    pass


_ALLOWED: dict[str, frozenset[str]] = {
    STATUS_DRAFT: frozenset(
        {STATUS_GENERATING, STATUS_EDITING, STATUS_REVIEW, STATUS_QUARANTINED}
    ),
    STATUS_GENERATING: frozenset({STATUS_DRAFT, STATUS_QUARANTINED}),
    STATUS_EDITING: frozenset({STATUS_DRAFT, STATUS_QUARANTINED}),
    STATUS_REVIEW: frozenset({STATUS_APPROVED, STATUS_REJECTED}),
    STATUS_APPROVED: frozenset({STATUS_PUBLISHING, STATUS_REJECTED}),
    STATUS_REJECTED: frozenset({STATUS_DRAFT}),
    STATUS_PUBLISHING: frozenset({STATUS_PUBLISHED, STATUS_APPROVED, STATUS_QUARANTINED}),
    STATUS_PUBLISHED: frozenset(),
    STATUS_QUARANTINED: frozenset({STATUS_DRAFT}),
}


def can_transition(src: str, dst: str) -> bool:
    return dst in _ALLOWED.get(src, frozenset())


def transition(src: str, dst: str) -> str:
    if not can_transition(src, dst):
        raise WorkflowError(f"illegal_transition:{src}->{dst}")
    return dst
