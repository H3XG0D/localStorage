-- DRAFT migration for FocusPay Sticker AI (NOT applied to production by default).
-- Apply only on lab/staging after explicit approve. Rollback SQL at bottom.
-- Separate from ops_ai_* tables.

BEGIN;

CREATE TABLE IF NOT EXISTS sticker_ai_tasks (
    id              UUID PRIMARY KEY,
    tenant_id       TEXT NOT NULL DEFAULT 'focuspay',
    owner_id        BIGINT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN (
                        'draft','generating','editing','review','approved',
                        'rejected','publishing','published','quarantined'
                    )),
    idea_hash       TEXT NOT NULL,
    idea_redacted   TEXT NOT NULL DEFAULT '',
    n_variants      INT NOT NULL DEFAULT 2,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sticker_ai_tasks_owner ON sticker_ai_tasks (owner_id);
CREATE INDEX IF NOT EXISTS idx_sticker_ai_tasks_status ON sticker_ai_tasks (status);

CREATE TABLE IF NOT EXISTS sticker_ai_versions (
    id              UUID PRIMARY KEY,
    task_id         UUID NOT NULL REFERENCES sticker_ai_tasks(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL CHECK (kind IN ('generate','edit')),
    model_id        TEXT,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sticker_ai_versions_task ON sticker_ai_versions (task_id);

CREATE TABLE IF NOT EXISTS sticker_ai_audit_events (
    id              BIGSERIAL PRIMARY KEY,
    namespace       TEXT NOT NULL DEFAULT 'sticker_ai',
    actor_type      TEXT NOT NULL,
    actor_id        BIGINT NOT NULL,
    tenant_id       TEXT NOT NULL,
    task_id         UUID,
    event_type      TEXT NOT NULL,
    prompt_hash     TEXT,
    redacted_prompt_preview TEXT,
    model_id        TEXT,
    meta            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sticker_ai_audit_task ON sticker_ai_audit_events (task_id);
CREATE INDEX IF NOT EXISTS idx_sticker_ai_audit_actor ON sticker_ai_audit_events (actor_type, actor_id);

CREATE TABLE IF NOT EXISTS sticker_ai_idempotency (
    idem_key        TEXT PRIMARY KEY,
    task_id         UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;

-- Rollback (lab only):
-- BEGIN;
-- DROP TABLE IF EXISTS sticker_ai_idempotency;
-- DROP TABLE IF EXISTS sticker_ai_audit_events;
-- DROP TABLE IF EXISTS sticker_ai_versions;
-- DROP TABLE IF EXISTS sticker_ai_tasks;
-- COMMIT;
