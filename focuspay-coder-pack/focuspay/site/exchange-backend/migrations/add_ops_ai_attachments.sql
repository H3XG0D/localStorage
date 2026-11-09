-- Ops AI: вложения (скриншоты) к чату и задачам.
-- Идемпотентно.

ALTER TABLE ops_ai_chat_messages
    ADD COLUMN IF NOT EXISTS attachments_json JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE ops_ai_dev_tasks
    ADD COLUMN IF NOT EXISTS attachments_json JSONB NOT NULL DEFAULT '[]'::jsonb;
