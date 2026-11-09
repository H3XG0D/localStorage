-- Nightly SAST self-check runs (bandit + pip-audit). Idempotent.

CREATE TABLE IF NOT EXISTS ops_ai_selfcheck_runs (
    id              BIGSERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    job_status      TEXT NOT NULL,
    exit_code       INT,
    checks_json     JSONB NOT NULL DEFAULT '[]'::jsonb,
    artifact_rel    TEXT,
    source          TEXT NOT NULL DEFAULT 'systemd',
    task_id         BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ops_ai_selfcheck_runs_status_chk CHECK (
        job_status IN ('passed', 'failed', 'error')
    )
);

CREATE INDEX IF NOT EXISTS idx_ops_ai_selfcheck_runs_started
    ON ops_ai_selfcheck_runs (started_at DESC, id DESC);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'ops_ai_dev_tasks'
    ) THEN
        BEGIN
            ALTER TABLE ops_ai_selfcheck_runs
                ADD CONSTRAINT ops_ai_selfcheck_runs_task_fk
                FOREIGN KEY (task_id) REFERENCES ops_ai_dev_tasks(id) ON DELETE SET NULL;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON ops_ai_selfcheck_runs TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE ops_ai_selfcheck_runs_id_seq TO exchange_bot;
    END IF;
END $$;
