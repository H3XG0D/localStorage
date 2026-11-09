-- Ops AI multi-agent findings on dev tasks.
ALTER TABLE ops_ai_dev_tasks
    ADD COLUMN IF NOT EXISTS agents_json JSONB NOT NULL DEFAULT '{}'::jsonb;
