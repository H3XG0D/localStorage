"""Cursor collaboration sandbox — allowlist paths, diff proposal, no auto-apply/deploy."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from privacy_redaction import content_hash, redact_text


# Repo-relative allowlist for sticker AI Cursor work.
REPO_ALLOWLIST_PREFIXES: tuple[str, ...] = (
    "site/exchange-backend/sticker_ai/",
    "site/exchange-backend/tests/test_sticker_ai",
    "site/exchange-backend/migrations/add_sticker_ai.sql",
    "docs/sticker-ai-architecture.md",
    "docs/PERMISSION_MATRIX.md",
    "focussite/frontend/public/brand-stickers/",
)

FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    ".env",
    "secret",
    "credentials",
    "/opt/exchange-backend",
    "DATABASE_DSN",
    "id_rsa",
    ".ssh/",
    "production",
)


class CursorSandboxError(ValueError):
    pass


def normalize_repo_path(path: str) -> str:
    p = (path or "").replace("\\", "/").lstrip("./")
    while p.startswith("../"):
        raise CursorSandboxError("path_escape")
    if ".." in p.split("/"):
        raise CursorSandboxError("path_escape")
    return p


def is_path_allowed(path: str) -> bool:
    try:
        p = normalize_repo_path(path).lower()
    except CursorSandboxError:
        return False
    for bad in FORBIDDEN_SUBSTRINGS:
        if bad.lower() in p:
            return False
    return any(p.startswith(pref.lower()) or p == pref.rstrip("/").lower() for pref in REPO_ALLOWLIST_PREFIXES)


@dataclass
class CursorProposal:
    id: str
    actor_id: int
    prompt_hash: str
    redacted_prompt_preview: str
    target_paths: list[str]
    diff_text: str
    approved: bool = False
    applied: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: datetime | None = None


@dataclass
class CursorSandbox:
    """Holds proposals only — never executes shell, never deploys, never writes files."""

    proposals: dict[str, CursorProposal] = field(default_factory=dict)

    def propose(
        self,
        *,
        actor_id: int,
        cursor_prompt: str,
        target_paths: list[str],
        diff_text: str,
    ) -> CursorProposal:
        paths = [normalize_repo_path(p) for p in target_paths]
        if not paths:
            raise CursorSandboxError("empty_paths")
        for p in paths:
            if not is_path_allowed(p):
                raise CursorSandboxError(f"path_denied:{p}")
        redacted = redact_text(cursor_prompt or "", keep_short_ids=True)[:2000]
        # Treat cursor_prompt as untrusted text — store hash/preview only.
        pid = hashlib.sha256(f"{actor_id}:{content_hash(redacted)}:{paths}".encode()).hexdigest()[:16]
        prop = CursorProposal(
            id=pid,
            actor_id=int(actor_id),
            prompt_hash=content_hash(redacted),
            redacted_prompt_preview=redacted[:240],
            target_paths=paths,
            diff_text=redact_text(diff_text or "", keep_short_ids=True)[:50_000],
        )
        self.proposals[pid] = prop
        return prop

    def approve(self, proposal_id: str, *, approver_id: int) -> CursorProposal:
        prop = self.proposals.get(proposal_id)
        if not prop:
            raise CursorSandboxError("not_found")
        if prop.approved:
            return prop
        # Approver must be a distinct human step; auto-apply forbidden.
        prop.approved = True
        prop.approved_at = datetime.now(timezone.utc)
        _ = approver_id
        return prop

    def mark_applied_externally(self, proposal_id: str) -> CursorProposal:
        """Record that a human applied the diff outside this process. No I/O here."""
        prop = self.proposals.get(proposal_id)
        if not prop:
            raise CursorSandboxError("not_found")
        if not prop.approved:
            raise CursorSandboxError("not_approved")
        prop.applied = True
        return prop

    def auto_apply_forbidden(self, proposal_id: str) -> dict[str, Any]:
        return {
            "proposal_id": proposal_id,
            "auto_apply": False,
            "auto_deploy": False,
            "reason": "cursor_prompt_is_untrusted_requires_human_approve",
        }
