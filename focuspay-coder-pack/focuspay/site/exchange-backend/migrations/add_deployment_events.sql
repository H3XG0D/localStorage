-- Deployment tracking + daily changelog (operator confirmation).
CREATE TABLE IF NOT EXISTS deployment_events (
    id                      BIGSERIAL PRIMARY KEY,
    idempotency_key         TEXT NOT NULL UNIQUE,
    environment             TEXT NOT NULL DEFAULT 'production',
    commit_sha              TEXT,
    build_id                TEXT,
    actor                   TEXT,
    status                  TEXT NOT NULL DEFAULT 'pending',
    title                   TEXT NOT NULL DEFAULT '',
    sectors                 TEXT[] NOT NULL DEFAULT '{}',
    technical_summary       TEXT NOT NULL DEFAULT '',
    user_impact             TEXT NOT NULL DEFAULT '',
    plain_explanation       TEXT NOT NULL DEFAULT '',
    logs_url                TEXT,
    source                  TEXT NOT NULL DEFAULT 'webhook',
    ops_ai_task_id          INT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at            TIMESTAMPTZ,
    confirmed_by_operator_id INT REFERENCES operator_accounts(id),
    notify_sent_at          TIMESTAMPTZ,
    extra                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT deployment_events_status_chk CHECK (
        status IN ('pending', 'success', 'failed', 'unknown', 'confirmed')
    )
);

CREATE INDEX IF NOT EXISTS idx_deployment_events_created
    ON deployment_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_deployment_events_env_status
    ON deployment_events (environment, status);
CREATE INDEX IF NOT EXISTS idx_deployment_events_day
    ON deployment_events ((timezone('UTC', created_at)::date));

CREATE TABLE IF NOT EXISTS deployment_event_audit (
    id          BIGSERIAL PRIMARY KEY,
    event_id    BIGINT NOT NULL REFERENCES deployment_events(id) ON DELETE CASCADE,
    actor_type  TEXT NOT NULL,
    actor_id    INT,
    action      TEXT NOT NULL,
    detail      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deployment_event_audit_event
    ON deployment_event_audit (event_id, created_at DESC);
