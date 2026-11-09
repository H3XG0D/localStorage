-- Ops AI: память проекта (по людям / времени) + привязка Telegram оператора + расписание дайджеста.
-- Идемпотентно.

ALTER TABLE operator_accounts
    ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT,
    ADD COLUMN IF NOT EXISTS telegram_bind_token TEXT,
    ADD COLUMN IF NOT EXISTS telegram_bind_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ops_ai_digest_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS ops_ai_digest_hour SMALLINT NOT NULL DEFAULT 10;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'operator_accounts_telegram_user_id_key'
    ) THEN
        ALTER TABLE operator_accounts
            ADD CONSTRAINT operator_accounts_telegram_user_id_key UNIQUE (telegram_user_id);
    END IF;
EXCEPTION WHEN others THEN
    NULL;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'operator_accounts_digest_hour_check'
    ) THEN
        ALTER TABLE operator_accounts
            ADD CONSTRAINT operator_accounts_digest_hour_check
            CHECK (ops_ai_digest_hour >= 0 AND ops_ai_digest_hour <= 23);
    END IF;
EXCEPTION WHEN others THEN
    NULL;
END $$;

CREATE TABLE IF NOT EXISTS ops_ai_memories (
    id                      BIGSERIAL PRIMARY KEY,
    kind                    TEXT NOT NULL
                            CHECK (kind IN ('person', 'project', 'shift', 'incident', 'decision')),
    person_key              TEXT,
    person_label            TEXT,
    title                   TEXT NOT NULL,
    body                    TEXT NOT NULL,
    occurred_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source                  TEXT NOT NULL DEFAULT 'manual',
    source_ref              TEXT,
    created_by_operator_id  BIGINT REFERENCES operator_accounts(id) ON DELETE SET NULL,
    importance              SMALLINT NOT NULL DEFAULT 1
                            CHECK (importance >= 1 AND importance <= 5),
    expires_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ops_ai_memories_person_time
    ON ops_ai_memories (person_key, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_ai_memories_occurred
    ON ops_ai_memories (occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_ai_memories_kind
    ON ops_ai_memories (kind, occurred_at DESC);

CREATE TABLE IF NOT EXISTS ops_ai_digest_log (
    id                  BIGSERIAL PRIMARY KEY,
    operator_id         BIGINT REFERENCES operator_accounts(id) ON DELETE SET NULL,
    telegram_user_id    BIGINT,
    kind                TEXT NOT NULL DEFAULT 'daily',
    sent_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload_preview     TEXT
);

CREATE INDEX IF NOT EXISTS idx_ops_ai_digest_log_op_day
    ON ops_ai_digest_log (operator_id, sent_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON ops_ai_memories TO exchange_bot;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ops_ai_digest_log TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE ops_ai_memories_id_seq TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE ops_ai_digest_log_id_seq TO exchange_bot;
        GRANT SELECT, UPDATE ON operator_accounts TO exchange_bot;
    END IF;
END $$;
