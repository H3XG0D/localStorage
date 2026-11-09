-- Scheduled one-shot jobs + recurring broadcast templates.
-- Apply: psql -d exchange_bot -f migrations/add_broadcast_schedule.sql

ALTER TABLE broadcast_jobs
  ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ;

ALTER TABLE broadcast_jobs
  ADD COLUMN IF NOT EXISTS schedule_id INT;

COMMENT ON COLUMN broadcast_jobs.scheduled_at IS 'When to send; NULL = as soon as the worker is idle';
COMMENT ON COLUMN broadcast_jobs.schedule_id IS 'Recurring template that spawned this job';

CREATE TABLE IF NOT EXISTS broadcast_schedules (
    id                  SERIAL PRIMARY KEY,
    sender_role         TEXT NOT NULL,
    sender_id           INT NOT NULL,
    sender_label        TEXT,
    segment             TEXT NOT NULL,
    message_text        TEXT NOT NULL,
    photo_file_id       TEXT,
    sticker_ids         TEXT,
    sticker_mode        TEXT,
    sticker_status      TEXT,
    time_local          TIME NOT NULL,
    days_of_week        INT[] NOT NULL DEFAULT '{1,2,3,4,5,6,7}',
    timezone            TEXT NOT NULL DEFAULT 'Europe/Moscow',
    enabled             BOOLEAN NOT NULL DEFAULT true,
    last_enqueued_date  DATE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'broadcast_jobs_schedule_id_fkey'
    ) THEN
        ALTER TABLE broadcast_jobs
            ADD CONSTRAINT broadcast_jobs_schedule_id_fkey
            FOREIGN KEY (schedule_id) REFERENCES broadcast_schedules(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_broadcast_jobs_queue
    ON broadcast_jobs (status, scheduled_at);

CREATE INDEX IF NOT EXISTS idx_broadcast_schedules_enabled
    ON broadcast_schedules (enabled, last_enqueued_date);

COMMENT ON TABLE broadcast_schedules IS 'Recurring broadcast templates; worker enqueues one job per Moscow day';
