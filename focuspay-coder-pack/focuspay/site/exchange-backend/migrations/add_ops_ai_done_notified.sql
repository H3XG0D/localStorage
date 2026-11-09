-- Ops AI: anti-dupe flag for "task done" notify to assigner.
-- Idempotent.

ALTER TABLE ops_ai_dev_tasks
    ADD COLUMN IF NOT EXISTS done_notified_at TIMESTAMPTZ;
