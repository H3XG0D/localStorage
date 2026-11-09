-- Ops AI privacy audit + consent; news subscriptions / targeted broadcast.
-- Idempotent. No secrets. Apply: psql "$DATABASE_DSN" -f migrations/add_ops_ai_audit_and_news.sql

-- ---------------------------------------------------------------------------
-- Ops AI consent (versioned)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_ai_consent (
    id               BIGSERIAL PRIMARY KEY,
    subject_type     TEXT NOT NULL CHECK (subject_type IN ('operator', 'admin', 'user')),
    subject_id       BIGINT NOT NULL,
    consent_version  TEXT NOT NULL,
    scopes           JSONB NOT NULL DEFAULT '["llm"]'::jsonb,
    source           TEXT NOT NULL DEFAULT 'api',
    actor_id         BIGINT,
    granted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ops_ai_consent_subject
    ON ops_ai_consent (subject_type, subject_id, granted_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_ai_consent_active
    ON ops_ai_consent (subject_type, subject_id)
    WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------------
-- Protected AI audit (redacted payloads only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_ai_audit_events (
    id                 BIGSERIAL PRIMARY KEY,
    correlation_id     TEXT NOT NULL,
    actor_type         TEXT NOT NULL,
    actor_id           BIGINT NOT NULL,
    tenant_scope       TEXT NOT NULL DEFAULT 'global',
    event_type         TEXT NOT NULL,
    consent_version    TEXT,
    request_hash       TEXT NOT NULL,
    response_hash      TEXT,
    redacted_request   JSONB NOT NULL DEFAULT '{}'::jsonb,
    redacted_response  JSONB NOT NULL DEFAULT '{}'::jsonb,
    meta               JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at         TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ops_ai_audit_actor
    ON ops_ai_audit_events (actor_type, actor_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_ops_ai_audit_expires
    ON ops_ai_audit_events (expires_at);

CREATE INDEX IF NOT EXISTS idx_ops_ai_audit_corr
    ON ops_ai_audit_events (correlation_id);

CREATE TABLE IF NOT EXISTS ops_ai_audit_access_log (
    id             BIGSERIAL PRIMARY KEY,
    audit_id       BIGINT REFERENCES ops_ai_audit_events(id) ON DELETE SET NULL,
    accessor_type  TEXT NOT NULL,
    accessor_id    BIGINT NOT NULL,
    action         TEXT NOT NULL,
    detail         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ops_ai_audit_access_created
    ON ops_ai_audit_access_log (created_at DESC);

-- ---------------------------------------------------------------------------
-- News chat allowlist (owner-confirmed)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS news_chat_allowlist (
    chat_id        BIGINT PRIMARY KEY,
    title          TEXT,
    confirmed_by   BIGINT NOT NULL,
    confirmed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    notes          TEXT
);

-- ---------------------------------------------------------------------------
-- News subscription preferences (opt-in / opt-out)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS news_subscriptions (
    user_id            BIGINT PRIMARY KEY,
    opted_in           BOOLEAN NOT NULL DEFAULT FALSE,
    categories         JSONB NOT NULL DEFAULT '[]'::jsonb,
    consent_version    TEXT NOT NULL DEFAULT 'news-privacy-v1',
    consent_source     TEXT NOT NULL DEFAULT 'bot',
    consented_at       TIMESTAMPTZ,
    opted_out_at       TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_news_subscriptions_opted_in
    ON news_subscriptions (opted_in)
    WHERE opted_in = TRUE;

-- ---------------------------------------------------------------------------
-- Targeted news broadcast jobs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS news_broadcast_jobs (
    id                 BIGSERIAL PRIMARY KEY,
    idempotency_key    TEXT NOT NULL UNIQUE,
    category           TEXT NOT NULL DEFAULT 'general',
    title              TEXT,
    body_html          TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'queued'
                       CHECK (status IN ('queued', 'running', 'done', 'failed', 'cancelled')),
    created_by         BIGINT NOT NULL,
    locked_at          TIMESTAMPTZ,
    lock_token         TEXT,
    total              INT NOT NULL DEFAULT 0,
    sent               INT NOT NULL DEFAULT 0,
    failed             INT NOT NULL DEFAULT 0,
    skipped            INT NOT NULL DEFAULT 0,
    error_summary      TEXT,
    started_at         TIMESTAMPTZ,
    finished_at        TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS news_broadcast_deliveries (
    id             BIGSERIAL PRIMARY KEY,
    job_id         BIGINT NOT NULL REFERENCES news_broadcast_jobs(id) ON DELETE CASCADE,
    user_id        BIGINT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('sent', 'failed', 'skipped')),
    error          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_news_broadcast_deliveries_job
    ON news_broadcast_deliveries (job_id);

CREATE TABLE IF NOT EXISTS news_broadcast_audit (
    id             BIGSERIAL PRIMARY KEY,
    job_id         BIGINT REFERENCES news_broadcast_jobs(id) ON DELETE SET NULL,
    actor_id       BIGINT NOT NULL,
    action         TEXT NOT NULL,
    detail         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON ops_ai_consent TO exchange_bot;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ops_ai_audit_events TO exchange_bot;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ops_ai_audit_access_log TO exchange_bot;
        GRANT SELECT, INSERT, UPDATE, DELETE ON news_chat_allowlist TO exchange_bot;
        GRANT SELECT, INSERT, UPDATE, DELETE ON news_subscriptions TO exchange_bot;
        GRANT SELECT, INSERT, UPDATE, DELETE ON news_broadcast_jobs TO exchange_bot;
        GRANT SELECT, INSERT, UPDATE, DELETE ON news_broadcast_deliveries TO exchange_bot;
        GRANT SELECT, INSERT, UPDATE, DELETE ON news_broadcast_audit TO exchange_bot;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO exchange_bot;
    END IF;
END $$;
