-- Admin broadcast: store project sticker slugs (never client Telegram file_id).
ALTER TABLE broadcast_jobs
  ADD COLUMN IF NOT EXISTS sticker_ids TEXT;

ALTER TABLE broadcast_jobs
  ADD COLUMN IF NOT EXISTS sticker_mode TEXT;

ALTER TABLE broadcast_jobs
  ADD COLUMN IF NOT EXISTS sticker_status TEXT;

COMMENT ON COLUMN broadcast_jobs.sticker_ids IS 'JSON list of project sticker slugs (01_logo … 12_paid)';
COMMENT ON COLUMN broadcast_jobs.sticker_mode IS 'none | selected | auto';
COMMENT ON COLUMN broadcast_jobs.sticker_status IS 'none | selected | auto | skipped_empty_catalog';
