-- Ops AI: чат-подсказки операторам + задачи на разработку (промпт → Approve).
-- Идемпотентно. Применять: psql -d exchange_bot -f migrations/add_ops_ai.sql

CREATE TABLE IF NOT EXISTS ops_ai_chat_sessions (
    id              BIGSERIAL PRIMARY KEY,
    operator_id     BIGINT NOT NULL,
    title           TEXT NOT NULL DEFAULT 'Чат',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ops_ai_chat_sessions_op
    ON ops_ai_chat_sessions (operator_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS ops_ai_chat_messages (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT NOT NULL REFERENCES ops_ai_chat_sessions(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT NOT NULL,
    sources_json    JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ops_ai_chat_messages_session
    ON ops_ai_chat_messages (session_id, id);

CREATE TABLE IF NOT EXISTS ops_ai_dev_tasks (
    id                  BIGSERIAL PRIMARY KEY,
    operator_id         BIGINT,
    source_session_id   BIGINT REFERENCES ops_ai_chat_sessions(id) ON DELETE SET NULL,
    source_message_id   BIGINT REFERENCES ops_ai_chat_messages(id) ON DELETE SET NULL,
    title               TEXT NOT NULL,
    request_text        TEXT NOT NULL,
    priority            TEXT NOT NULL DEFAULT 'normal'
                        CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    status              TEXT NOT NULL DEFAULT 'new'
                        CHECK (status IN (
                            'new', 'drafting', 'review', 'approved', 'rejected', 'done'
                        )),
    summary             TEXT,
    file_list_json      JSONB NOT NULL DEFAULT '[]'::jsonb,
    freeze_hit          BOOLEAN NOT NULL DEFAULT FALSE,
    cursor_prompt       TEXT,
    smoke_plan          TEXT,
    risks               TEXT,
    reject_reason       TEXT,
    reviewed_by_admin_id BIGINT,
    reviewed_at         TIMESTAMPTZ,
    done_at             TIMESTAMPTZ,
    telegram_message_id BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ops_ai_dev_tasks_status
    ON ops_ai_dev_tasks (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS ops_ai_learning_notes (
    id              BIGSERIAL PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('task_done', 'chat_useful', 'incident')),
    ref_task_id     BIGINT REFERENCES ops_ai_dev_tasks(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON ops_ai_chat_sessions TO exchange_bot;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ops_ai_chat_messages TO exchange_bot;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ops_ai_dev_tasks TO exchange_bot;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ops_ai_learning_notes TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE ops_ai_chat_sessions_id_seq TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE ops_ai_chat_messages_id_seq TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE ops_ai_dev_tasks_id_seq TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE ops_ai_learning_notes_id_seq TO exchange_bot;
    END IF;
END $$;
