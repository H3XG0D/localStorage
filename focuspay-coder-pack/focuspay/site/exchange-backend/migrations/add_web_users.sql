-- Migration: web_users table for site authentication
-- Run: psql -U exchange_bot -d exchange_bot -f migrations/add_web_users.sql

CREATE TABLE IF NOT EXISTS web_users (
    id                SERIAL PRIMARY KEY,
    email             VARCHAR(255) NOT NULL UNIQUE,
    password_hash     VARCHAR(255) NOT NULL,
    telegram_user_id  BIGINT UNIQUE REFERENCES bot_users(user_id) ON DELETE SET NULL,
    display_name      VARCHAR(255),
    is_admin          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_web_users_email ON web_users (email);
CREATE INDEX IF NOT EXISTS idx_web_users_tg_id ON web_users (telegram_user_id);

COMMENT ON TABLE web_users IS 'Accounts for the React web dashboard; optionally linked to a Telegram bot_users row.';
