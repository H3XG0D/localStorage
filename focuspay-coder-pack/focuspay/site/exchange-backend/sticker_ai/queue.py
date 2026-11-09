"""In-process job queue (names isolated from Ops AI).

Job statuses: queued → running → succeeded | failed.
Supports idempotent enqueue by key (same key returns existing open job).
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"

JOB_STATUSES = frozenset({JOB_QUEUED, JOB_RUNNING, JOB_SUCCEEDED, JOB_FAILED})


@dataclass
class Job:
    id: str
    queue: str
    payload: dict[str, Any]
    status: str = JOB_QUEUED
    attempts: int = 0
    idempotency_key: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()


@dataclass
class InMemoryQueue:
    max_retries: int = 2
    _queues: dict[str, deque[Job]] = field(default_factory=lambda: defaultdict(deque))
    _by_id: dict[str, Job] = field(default_factory=dict)
    _by_idem: dict[str, str] = field(default_factory=dict)
    _dead: list[Job] = field(default_factory=list)
    _history: list[Job] = field(default_factory=list)

    def enqueue(
        self,
        queue: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> Job:
        if idempotency_key:
            existing_id = self._by_idem.get(idempotency_key)
            if existing_id:
                existing = self._by_id.get(existing_id)
                if existing and existing.status in (JOB_QUEUED, JOB_RUNNING, JOB_SUCCEEDED):
                    return existing
        job = Job(
            id=str(uuid4()),
            queue=queue,
            payload=dict(payload),
            status=JOB_QUEUED,
            idempotency_key=idempotency_key,
        )
        self._queues[queue].append(job)
        self._by_id[job.id] = job
        if idempotency_key:
            self._by_idem[idempotency_key] = job.id
        return job

    def dequeue(self, queue: str) -> Job | None:
        q = self._queues.get(queue)
        if not q:
            return None
        job = q.popleft()
        job.status = JOB_RUNNING
        job.touch()
        return job

    def mark_running(self, job_id: str) -> Job | None:
        job = self._by_id.get(job_id)
        if not job:
            return None
        job.status = JOB_RUNNING
        job.touch()
        return job

    def mark_succeeded(self, job_id: str) -> Job | None:
        job = self._by_id.get(job_id)
        if not job:
            return None
        job.status = JOB_SUCCEEDED
        job.error = None
        job.touch()
        self._history.append(job)
        return job

    def mark_failed(self, job_id: str, *, error: str = "") -> Job | None:
        job = self._by_id.get(job_id)
        if not job:
            return None
        job.status = JOB_FAILED
        job.error = (error or "")[:200]
        job.touch()
        self._history.append(job)
        return job

    def retry_or_dead(self, job: Job) -> None:
        job.attempts += 1
        job.touch()
        if job.attempts > self.max_retries:
            job.status = JOB_FAILED
            self._dead.append(job)
            return
        job.status = JOB_QUEUED
        self._queues[job.queue].append(job)

    def get(self, job_id: str) -> Job | None:
        return self._by_id.get(job_id)

    def depth(self, queue: str) -> int:
        return len(self._queues.get(queue) or ())

    def snapshot(self) -> dict[str, Any]:
        """Safe queue summary for health/UI — no payloads with secrets."""
        counts: dict[str, dict[str, int]] = {}
        for name, q in self._queues.items():
            bucket = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0}
            for job in q:
                if job.status in bucket:
                    bucket[job.status] += 1
            counts[name] = bucket
        for job in self._history[-50:]:
            bucket = counts.setdefault(job.queue, {"queued": 0, "running": 0, "succeeded": 0, "failed": 0})
            if job.status in bucket:
                bucket[job.status] += 1
        return {
            "depths": {k: self.depth(k) for k in sorted(self._queues.keys())},
            "by_status": counts,
            "dead_letter": len(self._dead),
        }
