-- Общий Telegram-бот внештатников: токен в админке, доступ по telegram id.
-- psql -h 127.0.0.1 -p 5434 -U exchange_bot -d exchange_bot -f migrations/add_exchanger_bot.sql

CREATE TABLE IF NOT EXISTS exchanger_bot_config (
    id              INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    token           TEXT,
    bot_id          BIGINT,
    bot_username    VARCHAR(64),
    webhook_secret  TEXT,
    webhook_url     TEXT,
    configured_at   TIMESTAMPTZ,
    last_error      TEXT,
    updated_by      INT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO exchanger_bot_config (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS exchanger_bot_members (
    id                SERIAL PRIMARY KEY,
    telegram_user_id  BIGINT NOT NULL UNIQUE,
    exchanger_id      INT NOT NULL REFERENCES external_exchangers(id) ON DELETE CASCADE,
    role              VARCHAR(16) NOT NULL DEFAULT 'clerk'
                      CHECK (role IN ('owner', 'clerk')),
    label             VARCHAR(128),
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    invited_by        BIGINT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_exchanger_bot_members_exchanger
    ON exchanger_bot_members (exchanger_id);

CREATE TABLE IF NOT EXISTS exchanger_bot_broadcasts (
    id              SERIAL PRIMARY KEY,
    audience        TEXT NOT NULL,
    message_text    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    total_count     INT NOT NULL DEFAULT 0,
    sent_count      INT NOT NULL DEFAULT 0,
    failed_count    INT NOT NULL DEFAULT 0,
    error_summary   TEXT,
    created_by      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ
);

ALTER TABLE external_deals
    ADD COLUMN IF NOT EXISTS created_by_tg_id BIGINT;

COMMENT ON TABLE exchanger_bot_config IS
    'Одна строка: токен общего TG-бота внештатников и параметры вебхука';
COMMENT ON TABLE exchanger_bot_members IS
    'Whitelist telegram_user_id → магазин + роль (owner/clerk)';
COMMENT ON COLUMN external_deals.created_by_tg_id IS
    'Telegram id кассира, который запросил реквизит из бота';
