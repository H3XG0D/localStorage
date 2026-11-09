-- Куда слать рассылку: лички бота или один пост в канал новостей.
-- Apply: psql -d exchange_bot -f migrations/add_broadcast_destination.sql

ALTER TABLE broadcast_jobs
  ADD COLUMN IF NOT EXISTS destination TEXT NOT NULL DEFAULT 'bot';

ALTER TABLE broadcast_schedules
  ADD COLUMN IF NOT EXISTS destination TEXT NOT NULL DEFAULT 'bot';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'broadcast_jobs_destination_chk'
    ) THEN
        ALTER TABLE broadcast_jobs
            ADD CONSTRAINT broadcast_jobs_destination_chk
            CHECK (destination IN ('bot', 'news'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'broadcast_schedules_destination_chk'
    ) THEN
        ALTER TABLE broadcast_schedules
            ADD CONSTRAINT broadcast_schedules_destination_chk
            CHECK (destination IN ('bot', 'news'));
    END IF;
END $$;

COMMENT ON COLUMN broadcast_jobs.destination IS 'bot = личные сообщения по сегменту; news = один пост в канал новостей';
COMMENT ON COLUMN broadcast_schedules.destination IS 'bot = личные сообщения по сегменту; news = один пост в канал новостей';
