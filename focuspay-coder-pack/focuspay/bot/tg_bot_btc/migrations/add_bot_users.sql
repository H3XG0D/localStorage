-- Пользователи бота (для рассылки). Выполнить один раз:
-- psql -U exchange_bot -d exchange_bot -f migrations/add_bot_users.sql

CREATE TABLE IF NOT EXISTS bot_users (
    user_id    BIGINT PRIMARY KEY,
    username   VARCHAR(255),
    first_name VARCHAR(255),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE bot_users IS 'Пользователи, хотя бы раз запустившие бота (/start); для рассылки';

CREATE INDEX IF NOT EXISTS idx_bot_users_last_seen ON bot_users (last_seen_at DESC);
