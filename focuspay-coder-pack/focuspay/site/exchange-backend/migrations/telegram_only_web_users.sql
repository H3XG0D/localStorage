-- Telegram-only accounts: email/password optional
-- psql -h 127.0.0.1 -p 5434 -U exchange_bot -d exchange_bot -f migrations/telegram_only_web_users.sql

ALTER TABLE web_users
    ALTER COLUMN email DROP NOT NULL,
    ALTER COLUMN password_hash DROP NOT NULL;

-- Replace unconditional unique on email with partial unique (NULL emails allowed)
ALTER TABLE web_users DROP CONSTRAINT IF EXISTS web_users_email_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_web_users_email_unique
    ON web_users (email) WHERE email IS NOT NULL;

-- Telegram ID required for new TG-only flow (existing rows may already have it)
COMMENT ON COLUMN web_users.email IS 'Optional; Telegram login does not require email';
