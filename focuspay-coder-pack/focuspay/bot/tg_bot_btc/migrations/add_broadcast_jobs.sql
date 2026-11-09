CREATE TABLE IF NOT EXISTS broadcast_jobs (
  id              SERIAL PRIMARY KEY,
  sender_role     TEXT NOT NULL,
  sender_id       INT NOT NULL,
  sender_label    TEXT,
  segment         TEXT NOT NULL,
  message_text    TEXT NOT NULL,
  photo_file_id   TEXT,
  status          TEXT NOT NULL DEFAULT 'pending',
  total_count     INT NOT NULL DEFAULT 0,
  sent_count      INT NOT NULL DEFAULT 0,
  failed_count    INT NOT NULL DEFAULT 0,
  error_summary   TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at      TIMESTAMPTZ,
  finished_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_broadcast_jobs_status ON broadcast_jobs (status);
CREATE INDEX IF NOT EXISTS idx_broadcast_jobs_created_at ON broadcast_jobs (created_at DESC);

GRANT ALL PRIVILEGES ON TABLE broadcast_jobs TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE broadcast_jobs_id_seq TO exchange_bot;
